// Formal harness for WaveWordBridge (pulse path: RfCmd writes -> 168-bit QICK wave word).
//
// Pattern follows main:firmware/formal/tproc_sg_v6/tp_sg_formal.sv: record what was fired
// (w_word / w_time), then check the io_wave output handshake against that record.
//
// DUT: WaveWordBridge.v (frozen copy: leadTime=32 as in QickGenParams, TimedQueue depth=8).
// One clock; io_time is a counter that advances by 1 every cycle (the SoC batch-time counter).
// The readout-trigger path (io_trig) is not checked.
//
// Free inputs (chosen by the solver every cycle): cmd_valid/cmd_addr/cmd_data (any register
// write the CPU could issue), wave_ready_in (consumer ready, used with READY_FREE),
// rst_in (extra resets, used with RESET_FREE).
//
// Defines (set per task in bridge.sby):
//   TIMING       check release time against startTime (P1/P2/P3/P4)
//   NO_DATA      skip the 168-bit word comparison (faster; p5_data checks it)
//   ANY_ORDER    startTimes may be fired in any order; default: increasing, >= TGAP apart
//   REVERSE_ORDER each startTime is >= TGAP cycles EARLIER than the previous one (P3)
//   READY_FREE   consumer tready is free; check AXIS hold rule (P7)
//   RESET_FREE   reset may be re-asserted at any time (P8)
//   NSAMP_CHECK  every word handed to the generator has nsamp >= NSAMP_MIN (B4)
//   TRANSLATOR   put QICK's sg_translator (OUT_TYPE 0) behind the bridge and check that the 160-bit
//                command SGv6 receives decodes (ctrl_sg_v6.sv:427-435) to the values the CPU wrote
//   TR_FIT       CPU writes only values that fit SGv6's fields (nsamp/env < 2^16, gain a sign-
//                extended 16-bit value, conf bits [31:5] zero); without it, truncation is checked
//   CAPACITY     every fire is accepted by the wave TimedQueue (white-box: dut.q_io_push_ready) (P6)
module bridge_formal #(
   parameter LEAD      = 32,   // WaveWordBridgeParams.leadTime (QickGenParams default)
   parameter MARGIN    = 3,    // rule of use: fire >= LEAD+MARGIN cycles before startTime
   parameter LATE_TOL  = 0,    // allowed lateness in cycles (0 = exact)
   parameter K         = 3,    // fires tracked
   parameter TMAX      = 44,   // largest startTime used
   parameter TGAP      = 3,    // min spacing of startTimes (when in order)
   parameter RST_CYC   = 2,    // reset high for cycles [0, RST_CYC)
   parameter NSAMP_MIN = 3,    // smallest nsamp the kept SGv6 path handles (finding F9)
`ifdef TR_FIT
   parameter [3:0] FIT = 4'hf  // TRANSLATOR: which fields the CPU keeps in SGv6's range (see below)
`else
   parameter [3:0] FIT = 4'h0
`endif
)(
   input        clk,
   input        cmd_valid,
   input [15:0] cmd_addr,
   input [31:0] cmd_data,
   input        wave_ready_in,
   input        rst_in
);
   // ---------------- cycle counter, reset, time ----------------
   reg [7:0]  cyc = 0;      always @(posedge clk) if (cyc != 8'hff) cyc <= cyc + 1;
`ifdef RESET_FREE
   wire       reset = (cyc < RST_CYC) || rst_in;
`else
   wire       reset = (cyc < RST_CYC);
`endif
   reg [31:0] time_ctr = 0; always @(posedge clk) time_ctr <= time_ctr + 1;

`ifdef READY_FREE
   wire sink_ready = wave_ready_in;     // consumer (SGv6) ready, chosen freely by the solver
`else
   wire sink_ready = 1'b1;
`endif
   wire wave_ready;                     // ready seen by the bridge

   // ---------------- DUT ----------------
   wire         wave_valid;
   wire [167:0] wave_data;
   WaveWordBridge dut (
      .clk(clk), .reset(reset),
      .io_cmd_valid(cmd_valid), .io_cmd_payload_address(cmd_addr), .io_cmd_payload_data(cmd_data),
      .io_time(time_ctr),
      .io_wave_valid(wave_valid), .io_wave_ready(wave_ready), .io_wave_payload(wave_data),
      .io_trig()
   );

`ifdef TRANSLATOR
   // ---------------- QICK sg_translator behind the bridge (as in QickGen.scala on claude-newdesign) ----
   wire [159:0] gen_data;
   wire         gen_valid;
   sg_translator #(.OUT_TYPE(0)) tr (
      .aresetn(!reset), .aclk(clk),
      .s_axis_tdata(wave_data), .s_axis_tvalid(wave_valid), .s_axis_tready(wave_ready),
      .m_gen_v6_axis_tdata(gen_data), .m_gen_v6_axis_tvalid(gen_valid), .m_gen_v6_axis_tready(sink_ready),
      .m_int4_axis_tdata(), .m_int4_axis_tvalid(), .m_int4_axis_tready(1'b0),
      .m_mux4_axis_tdata(), .m_mux4_axis_tvalid(), .m_mux4_axis_tready(1'b0),
      .m_readout_axis_tdata(), .m_readout_axis_tvalid(), .m_readout_axis_tready(1'b0)
   );
`else
   assign wave_ready = sink_ready;
`endif

   // ---------------- reference model: shadow registers + record of each fire ----------------
   localparam A_FREQ = 16'h00, A_PHASE = 16'h04, A_ENV  = 16'h08, A_GAIN = 16'h0c,
              A_NSAMP = 16'h10, A_CONF = 16'h14, A_START = 16'h18, A_FIRE = 16'h1c;
   wire wr   = cmd_valid && !reset;
   wire fire = wr && cmd_addr == A_FIRE;

   reg [31:0] sh_freq = 0, sh_phase = 0, sh_gain = 0, sh_nsamp = 0, sh_start = 0;
   reg [23:0] sh_env  = 0;
   reg [15:0] sh_conf = 0;
   reg [31:0] sh_env32 = 0, sh_conf32 = 0;   // full 32-bit values the CPU wrote
   always @(posedge clk)
      if (reset) begin
         sh_freq <= 0; sh_phase <= 0; sh_env <= 0; sh_gain <= 0;
         sh_nsamp <= 0; sh_conf <= 0; sh_start <= 0; sh_env32 <= 0; sh_conf32 <= 0;
      end else if (wr) begin
         if (cmd_addr == A_FREQ)  sh_freq  <= cmd_data;
         if (cmd_addr == A_PHASE) sh_phase <= cmd_data;
         if (cmd_addr == A_ENV)   begin sh_env <= cmd_data[23:0]; sh_env32 <= cmd_data; end
         if (cmd_addr == A_GAIN)  sh_gain  <= cmd_data;
         if (cmd_addr == A_NSAMP) sh_nsamp <= cmd_data;
         if (cmd_addr == A_CONF)  begin sh_conf <= cmd_data[15:0]; sh_conf32 <= cmd_data; end
         if (cmd_addr == A_START) sh_start <= cmd_data;
      end
   // Expected word, same layout as sg_translator's input (conf|nsamp|gain|env|phase|freq).
   wire [167:0] sh_word = {sh_conf, sh_nsamp, sh_gain, sh_env, sh_phase, sh_freq};

   reg [167:0] w_word [0:K-1];
   reg [31:0]  w_time [0:K-1];
   // CPU-intended values per fired word: {conf, nsamp, gain, env, phase, freq}, 32 bits each
   reg [191:0] w_cpu  [0:K-1];
   reg [4:0]   n_w = 0;            // words fired (since the last reset)
   reg [4:0]   n_hs = 0;           // words handed over on io_wave (since the last reset)
   reg [31:0]  last_t = 0;
   integer j;
   initial for (j = 0; j < K; j = j + 1) begin w_word[j] = 0; w_time[j] = 0; w_cpu[j] = 0; end

   wire o_hs = wave_valid && wave_ready;

   always @(posedge clk)
      if (reset) begin
         n_w <= 0; n_hs <= 0; last_t <= 0;
      end else begin
         if (fire && n_w < K) begin
            w_word[n_w] <= sh_word;
            w_time[n_w] <= sh_start;
            w_cpu[n_w]  <= {sh_conf32, sh_nsamp, sh_gain, sh_env32, sh_phase, sh_freq};
            n_w         <= n_w + 1;
            last_t      <= sh_start;
         end
         if (o_hs && n_hs != 5'h1f) n_hs <= n_hs + 1;
      end

   // ---------------- rules of use (assumptions) ----------------
   always @* begin
      if (reset) assume (!cmd_valid);
`ifdef RESET_FREE
      // Extra resets only after the initial one, and not on the cycle right after it
      // (keeps traces readable; any later cycle is allowed).
      if (cyc < RST_CYC + 1) assume (!rst_in);
`else
      assume (!rst_in);
`endif
      if (fire) begin
         assume (n_w < K);
         assume (sh_start <= TMAX);
         assume (sh_start >= time_ctr + LEAD + MARGIN);           // fired far enough ahead
`ifdef TRANSLATOR
         // FIT bit set = that field is kept within SGv6's range (TR_FIT sets all four):
         // 1 nsamp < 2^16, 2 env < 2^16, 4 gain signed 16-bit, 8 conf[31:5] == 0.
         if (FIT[0]) assume (sh_nsamp < 32'h10000);
         if (FIT[1]) assume (sh_env32 < 32'h10000);
         if (FIT[2]) assume (sh_gain[31:15] == 17'h00000 || sh_gain[31:15] == 17'h1ffff);
         if (FIT[3]) assume (sh_conf32[31:5] == 0);
`endif
`ifdef REVERSE_ORDER
         if (n_w != 0) assume (sh_start + TGAP <= last_t);        // later-fired word is due earlier
`elsif ANY_ORDER
`else
         if (n_w != 0) assume (sh_start >= last_t + TGAP);        // in time order, spaced
`endif
      end
   end

   // ---------------- checks ----------------
   always @(posedge clk) if (!reset) begin
      // P5: nothing comes out that was not fired, nothing twice, in fire order, unchanged.
      if (o_hs) assert (n_hs < n_w);
`ifndef NO_DATA
      if (o_hs && n_hs < n_w) assert (wave_data == w_word[n_hs]);
`endif
`ifdef TIMING
      // P1: never early, and at most LATE_TOL cycles late (exact when LATE_TOL = 0).
      if (o_hs && n_hs < n_w) begin
         assert (time_ctr >= w_time[n_hs] - LEAD);
         assert (time_ctr <= w_time[n_hs] - LEAD + LATE_TOL);
      end
`endif
      // Not lost / not late: once a word's release time (+ tolerance) has passed, it is out.
`ifndef READY_FREE
      for (j = 0; j < K; j = j + 1)
         if (j < n_w && time_ctr > w_time[j] - LEAD + LATE_TOL) assert (n_hs > j);
`endif
`ifdef TRANSLATOR
      // Translator: SGv6 command valid/ready follow the bridge handshake, reserved bits are zero,
      // and every field SGv6 decodes equals what the CPU wrote for that word.
      assert (gen_valid == wave_valid);
      if (o_hs && n_hs < n_w) begin
         assert (gen_data[31:0]    == w_cpu[n_hs][31:0]);            // freq   (pinc_int)
         assert (gen_data[63:32]   == w_cpu[n_hs][63:32]);           // phase  (phase_int)
         assert ({16'd0, gen_data[79:64]}   == w_cpu[n_hs][95:64]);  // env    (addr_int, 16-bit)
         assert ({{16{gen_data[111]}}, gen_data[111:96]} == w_cpu[n_hs][127:96]);  // gain (signed 16)
         assert ({16'd0, gen_data[143:128]} == w_cpu[n_hs][159:128]); // nsamp (16-bit)
         assert ({27'd0, gen_data[148:144]} == w_cpu[n_hs][191:160]); // phrst,stdysel,mode,outsel
         assert (gen_data[159:149] == 0 && gen_data[127:112] == 0 && gen_data[95:80] == 0);
      end
`endif
`ifdef CAPACITY
      // P6: the bridge ties push.valid to the fire strobe and ignores push.ready, so a fire
      // while the queue is full is dropped without any signal. Check that never happens.
      if (fire) assert (dut.q_io_push_ready);
`endif
`ifdef NSAMP_CHECK
      // B4: the kept SGv6 path needs nsamp >= 3 (nsamp 0/1 play ~65536 cycles).
      if (o_hs) assert (wave_data[151:120] >= NSAMP_MIN);
`endif
   end

`ifdef READY_FREE
   // P7: AXI-Stream rule -- once tvalid is high it stays high, with the same tdata,
   // until tready accepts it.
   reg         past_ok = 0;
   reg         p_valid = 0, p_ready = 0;
   reg [167:0] p_data  = 0;
   always @(posedge clk) begin
      past_ok <= !reset;
      p_valid <= wave_valid;
      p_ready <= wave_ready;
      p_data  <= wave_data;
   end
   always @(posedge clk) if (!reset && past_ok && p_valid && !p_ready) begin
      assert (wave_valid);
      assert (wave_data == p_data);
   end
`endif

   // ---------------- covers (non-vacuity / example traces) ----------------
   reg [7:0] t_first = 0;
   always @(posedge clk) if (!reset && o_hs && n_hs == 0) t_first <= cyc;
   always @(posedge clk) if (!reset) begin
      cover (o_hs && n_hs == 0);                                // one word out
      cover (o_hs && n_hs == 1);                                // two words out
      cover (o_hs && n_hs == 1 && cyc == t_first + 2);          // two words back to back (II=2)
      cover (n_w == K && n_hs == 0);                            // K words pending at once
`ifdef READY_FREE
      cover (wave_valid && !wave_ready);                        // consumer not ready on release
`endif
   end
`ifdef RESET_FREE
   // Outside the !reset block: the cover is about the reset cycle itself.
   reg had_reset = 0;
   always @(posedge clk) if (rst_in) had_reset <= 1;
   always @(posedge clk) begin
      cover (rst_in && n_w != n_hs);                            // reset with words pending
      cover (had_reset && !reset && o_hs);                      // a word fired after that reset comes out
   end
`endif
endmodule
