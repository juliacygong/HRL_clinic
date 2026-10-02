// Formal harness: tProc v2 wave-port output path -> axis_signal_gen_v6.
//
// Real RTL, wired as in projects/qick_tprocv2_*:
//   qproc_dispatcher (timed wave FIFOs, XPM async FIFOs)
//     -> cdcsync (axis_cdcsync_v1 core, 2 channels)
//     -> sg_translator (OUT_TYPE 0)
//     -> signal_gen_top (axis_signal_gen_v6)
//
// Abstractions:
//   - The tProc core is replaced by free port-write inputs (c_we / c_time / c_addr /
//     c_data): any sequence of wave-port writes the CPU could issue.
//   - time_abs is a plain counter that starts at 0 when reset is released
//     (qproc_time_ctrl uses a Xilinx DSP macro).
//   - One clock for c_clk, t_clk, the cdcsync sides and the generator.
//   - The AXIS register slices between translator and generator are omitted.
//   - Channel 0 (tProc wave port 0) goes to "another generator", modelled as a
//     consumer with a free tready (m0_tready). Channel 1 goes to the real sg_v6.
//
// Defines (set per task in tp_sg.sby):
//   BLOCK0     - channel 0 consumer may drop tready at any time (else always ready)
//   DISP_AXIS  - check the dispatcher's own output: port 1 tready is free and the
//                cdcsync/generator are not in the loop
//   TIMING     - check the generator output against the tProc timestamps
`include "_qproc_defines.svh"

module tp_sg_formal #(
   parameter      N_DDS      = 16,
   parameter      K          = 3,     // port-1 commands tracked
   parameter      D          = 12,    // tProc time T -> generator accept (TIMING)
   parameter      NMIN       = 2,     // nsamp range allowed for commands
   parameter      NMAX       = 6,
   parameter      TMAX       = 120,   // largest timestamp used
   parameter      TGAP       = 3,     // min spacing of port-1 timestamps
   parameter      LEAD       = 2,     // core writes a command more than LEAD cycles before T
   parameter      RST_CYC    = 4,     // resets low for cycles [0, RST_CYC)
   parameter      RST_QUIET  = 8,     // no core writes for this many cycles after reset
   parameter      FIFO_DEPTH = 4      // dispatcher FIFO address bits (hardware: 9)
) (
   input  wire                clk,
   // tProc core side: one port write per cycle at most
   input  wire                c_we,
   input  wire [31:0]         c_time,
   input  wire                c_addr,     // wave port 0 or 1
   input  wire [167:0]        c_data,
   // consumers
   input  wire                m0_tready,  // channel 0 ("another generator")
   input  wire                d_tready1,  // DISP_AXIS only: port 1 tready
   input  wire                m_tready    // DAC side of the generator
);

// ---- Clock ----
reg [9:0] cyc = 0;
always @(posedge clk) if (cyc != 10'h3ff) cyc <= cyc + 1;

wire rstn = (cyc >= RST_CYC);

// tProc absolute time: 0 at the first cycle out of reset.
reg [47:0] time_abs = 0;
always @(posedge clk) if (rstn) time_abs <= time_abs + 1;

// ---- tProc v2 ----
PORT_DT out_port_data;
always @* begin
   out_port_data.p_time = c_time;
   out_port_data.p_type = 1'b0;          // wave port
   out_port_data.p_addr = {5'd0, c_addr};
   out_port_data.p_data = c_data;
end

wire [167:0] d_tdata  [2];
wire         d_tvalid [2];
wire         d_tready [2];
wire         all_fifo_full, some_fifo_full;

// Core run control, as in qproc_ctrl.sv (core_st path C_RST_RUN -> C_RST_RUN_WAIT
// -> C_RUN, TPROC_CFG[11] = 0): the core flushes the dispatcher FIFOs, waits for
// them to report full (in reset) and then not full, and only then runs. While it
// runs, it pauses whenever any dispatcher FIFO is full.
localparam C_RST_RUN = 2'd0, C_RST_RUN_WAIT = 2'd1, C_RUN = 2'd2;
reg [1:0] core_st = C_RST_RUN;
always @(posedge clk)
   if (!rstn) core_st <= C_RST_RUN;
   else case (core_st)
      C_RST_RUN:      if ( all_fifo_full) core_st <= C_RST_RUN_WAIT;
      C_RST_RUN_WAIT: if (!all_fifo_full) core_st <= C_RUN;
      default:        ;
   endcase
wire core_rst = rstn && (core_st == C_RST_RUN);
wire core_en  = rstn && (core_st == C_RUN) && !some_fifo_full;

qproc_dispatcher #(
   .FIFO_DEPTH    (FIFO_DEPTH),
   .IN_PORT_QTY   (1),
   .OUT_TRIG_QTY  (2),     // debug outputs index [1]
   .OUT_DPORT_QTY (2),
   .OUT_DPORT_DW  (4),
   .OUT_WPORT_QTY (2)
) disp (
   .c_clk_i        (clk          ),
   .c_rst_ni       (rstn         ),
   .t_clk_i        (clk          ),
   .t_rst_ni       (rstn         ),
   .core_en        (core_en      ),
   .core_rst       (core_rst     ),
   .time_en        (rstn         ),
   .time_rst       (1'b0         ),
   .c_time_ref_dt  (48'd0        ),
   .time_abs_i     (time_abs     ),
   .port_we        (c_we         ),
   .out_port_data  (out_port_data),
   .all_fifo_full  (all_fifo_full ),
   .some_fifo_full (some_fifo_full),
   .port_trig_o    (             ),
   .port_tvalid_o  (             ),
   .port_tdata_o   (             ),
   .m_axis_tdata   (d_tdata      ),
   .m_axis_tvalid  (d_tvalid     ),
   .m_axis_tready  (d_tready     ),
   .fifo_dt_do     (             ),
   .axi_fifo_do    (             ),
   .c_fifo_do      (             ),
   .t_fifo_do      (             )
);

// ---- cdcsync, translator ----
wire         c0_tvalid, c1_tvalid;
wire [167:0] c0_tdata,  c1_tdata;
wire         c0_tready, c1_tready;
wire         s0_tready, s1_tready_c;

cdcsync #(
   .N (2  ),
   .B (168)
) cdc (
   .s_axis_aresetn (rstn), .s_axis_aclk (clk),
   .s0_axis_tready (s0_tready  ), .s0_axis_tvalid (d_tvalid[0]), .s0_axis_tdata (d_tdata[0]),
   .s1_axis_tready (s1_tready_c), .s1_axis_tvalid (d_tvalid[1]), .s1_axis_tdata (d_tdata[1]),
   .s2_axis_tready (), .s2_axis_tvalid (1'b0), .s2_axis_tdata (168'd0),
   .s3_axis_tready (), .s3_axis_tvalid (1'b0), .s3_axis_tdata (168'd0),
   .s4_axis_tready (), .s4_axis_tvalid (1'b0), .s4_axis_tdata (168'd0),
   .s5_axis_tready (), .s5_axis_tvalid (1'b0), .s5_axis_tdata (168'd0),
   .s6_axis_tready (), .s6_axis_tvalid (1'b0), .s6_axis_tdata (168'd0),
   .s7_axis_tready (), .s7_axis_tvalid (1'b0), .s7_axis_tdata (168'd0),
   .s8_axis_tready (), .s8_axis_tvalid (1'b0), .s8_axis_tdata (168'd0),
   .s9_axis_tready (), .s9_axis_tvalid (1'b0), .s9_axis_tdata (168'd0),
   .s10_axis_tready(), .s10_axis_tvalid(1'b0), .s10_axis_tdata(168'd0),
   .s11_axis_tready(), .s11_axis_tvalid(1'b0), .s11_axis_tdata(168'd0),
   .s12_axis_tready(), .s12_axis_tvalid(1'b0), .s12_axis_tdata(168'd0),
   .s13_axis_tready(), .s13_axis_tvalid(1'b0), .s13_axis_tdata(168'd0),
   .s14_axis_tready(), .s14_axis_tvalid(1'b0), .s14_axis_tdata(168'd0),
   .s15_axis_tready(), .s15_axis_tvalid(1'b0), .s15_axis_tdata(168'd0),
   .m_axis_aresetn (rstn), .m_axis_aclk (clk),
   .m0_axis_tready (c0_tready), .m0_axis_tvalid (c0_tvalid), .m0_axis_tdata (c0_tdata),
   .m1_axis_tready (c1_tready), .m1_axis_tvalid (c1_tvalid), .m1_axis_tdata (c1_tdata),
   .m2_axis_tready (1'b1), .m2_axis_tvalid (), .m2_axis_tdata (),
   .m3_axis_tready (1'b1), .m3_axis_tvalid (), .m3_axis_tdata (),
   .m4_axis_tready (1'b1), .m4_axis_tvalid (), .m4_axis_tdata (),
   .m5_axis_tready (1'b1), .m5_axis_tvalid (), .m5_axis_tdata (),
   .m6_axis_tready (1'b1), .m6_axis_tvalid (), .m6_axis_tdata (),
   .m7_axis_tready (1'b1), .m7_axis_tvalid (), .m7_axis_tdata (),
   .m8_axis_tready (1'b1), .m8_axis_tvalid (), .m8_axis_tdata (),
   .m9_axis_tready (1'b1), .m9_axis_tvalid (), .m9_axis_tdata (),
   .m10_axis_tready(1'b1), .m10_axis_tvalid(), .m10_axis_tdata(),
   .m11_axis_tready(1'b1), .m11_axis_tvalid(), .m11_axis_tdata(),
   .m12_axis_tready(1'b1), .m12_axis_tvalid(), .m12_axis_tdata(),
   .m13_axis_tready(1'b1), .m13_axis_tvalid(), .m13_axis_tdata(),
   .m14_axis_tready(1'b1), .m14_axis_tvalid(), .m14_axis_tdata(),
   .m15_axis_tready(1'b1), .m15_axis_tvalid(), .m15_axis_tdata()
);

`ifdef BLOCK0
assign c0_tready = m0_tready;
`else
assign c0_tready = 1'b1;
`endif

`ifdef DISP_AXIS
assign d_tready[0] = 1'b1;
assign d_tready[1] = d_tready1;
`else
assign d_tready[0] = s0_tready;
assign d_tready[1] = s1_tready_c;
`endif

wire [159:0] s1_tdata;
wire         s1_tvalid;
wire         s1_tready;

sg_translator #(
   .OUT_TYPE (0)
) tr (
   .aresetn               (rstn     ),
   .aclk                  (clk      ),
   .s_axis_tdata          (c1_tdata ),
   .s_axis_tvalid         (c1_tvalid),
   .s_axis_tready         (c1_tready),
   .m_gen_v6_axis_tdata   (s1_tdata ),
   .m_gen_v6_axis_tvalid  (s1_tvalid),
   .m_gen_v6_axis_tready  (s1_tready),
   .m_int4_axis_tdata     (),
   .m_int4_axis_tvalid    (),
   .m_int4_axis_tready    (1'b0),
   .m_mux4_axis_tdata     (),
   .m_mux4_axis_tvalid    (),
   .m_mux4_axis_tready    (1'b0),
   .m_readout_axis_tdata  (),
   .m_readout_axis_tvalid (),
   .m_readout_axis_tready (1'b0)
);

// ---- Signal generator (channel 1) ----
wire                   m_tvalid;
wire [N_DDS*16-1:0]    m_tdata;

signal_gen_top #(
   .N             (4          ),
   .N_DDS         (N_DDS      ),
   .GEN_DDS       ("FALSE"    ),
   .ENVELOPE_TYPE ("COMPLEX"  )
) dut (
   .aresetn          (rstn       ),
   .aclk             (clk        ),
   .s0_axis_aresetn  (rstn       ),
   .s0_axis_aclk     (clk        ),
   .s0_axis_tdata_i  (32'd0      ),
   .s0_axis_tvalid_i (1'b0       ),
   .s0_axis_tready_o (           ),
   .s1_axis_tdata_i  (s1_tdata   ),
   .s1_axis_tvalid_i (s1_tvalid  ),
   .s1_axis_tready_o (s1_tready  ),
   .m_axis_tready_i  (m_tready   ),
   .m_axis_tvalid_o  (m_tvalid   ),
   .m_axis_tdata_o   (m_tdata    ),
   .START_ADDR_REG   (32'd0      ),
   .WE_REG           (1'b0       )
);

// ---- Core-side inputs ----
// tProc v2 wave word -> axis_signal_gen_v6 word, as sg_translator documents it.
function automatic [159:0] tr_word (input [167:0] d);
   tr_word = {11'd0, d[156], d[155], d[154], d[153:152], d[135:120],
              16'd0, d[103:88], 16'd0, d[79:64], d[63:32], d[31:0]};
endfunction

wire [15:0] w_nsamp = c_data[135:120];
wire [15:0] w_gain  = c_data[103:88];
wire        w_mode  = c_data[154];

// Port-1 writes, in program order.
reg [167:0] w1_data [0:K-1];
reg [31:0]  w1_time [0:K-1];
reg [3:0]   n_w1 = 0;
reg [31:0]  last_t1 = 0;
wire        we1 = c_we && c_addr;

integer j;
initial for (j = 0; j < K; j = j + 1) begin w1_data[j] = 0; w1_time[j] = 0; end

always @(posedge clk) if (we1 && n_w1 < K) begin
   w1_data[n_w1] <= c_data;
   w1_time[n_w1] <= c_time;
   n_w1          <= n_w1 + 1;
   last_t1       <= c_time;
end

always @* begin
   // No core writes during reset or the quiet window after it, and only while
   // the core runs (it is paused, not issuing writes, when core_en is low).
   if (cyc < RST_CYC + RST_QUIET) assume (!c_we);
   if (!core_en) assume (!c_we);
   if (c_we) begin
      assume (c_time <= TMAX);
      // Scheduled ahead of time, as a tProc program normally does.
      assume (c_time > time_abs[31:0] + LEAD);
      assume (w_mode == 1'b0);                                   // one-shot pulses
`ifdef LEN32
      // Any 32-bit tProc length from NMIN up.
      assume (c_data[151:120] >= NMIN);
`else
      assume (c_data[151:136] == 16'd0);                         // nsamp < 65536
      assume (w_nsamp >= NMIN && w_nsamp <= NMAX);
`endif
   end
   if (we1) begin
      assume (n_w1 < K);
      // Port-1 timestamps in program order, TGAP apart.
      if (n_w1 != 0) assume (c_time >= last_t1 + TGAP);
   end
end

// ---- Delivery: exactly once, in order, unchanged ----
`ifdef DISP_AXIS
// Dispatcher port 1 output, with an arbitrary consumer.
wire        o_valid = d_tvalid[1];
wire        o_ready = d_tready1;
wire [167:0] o_data = d_tdata[1];
wire [167:0] o_exp  [0:K-1];
generate for (genvar g = 0; g < K; g = g + 1) begin : GEN_exp
   assign o_exp[g] = w1_data[g];
end endgenerate
`else
// Generator input (after cdcsync and translator).
wire        o_valid = s1_tvalid;
wire        o_ready = s1_tready;
wire [159:0] o_data = s1_tdata;
wire [159:0] o_exp  [0:K-1];
generate for (genvar g = 0; g < K; g = g + 1) begin : GEN_exp
   assign o_exp[g] = tr_word(w1_data[g]);
end endgenerate
`endif

wire       o_hs = o_valid && o_ready;
reg  [3:0] n_hs = 0;
always @(posedge clk) if (o_hs && n_hs != 4'hf) n_hs <= n_hs + 1;

reg        past_valid = 0;
reg        p_ovalid   = 0;
reg        p_oready   = 0;
reg [$bits(o_data)-1:0] p_odata = 0;
always @(posedge clk) begin
   past_valid <= 1;
   p_ovalid   <= o_valid;
   p_oready   <= o_ready;
   p_odata    <= o_data;
end

always @(posedge clk) if (rstn) begin
   if (o_hs) begin
      // Nothing is delivered that was not written, and nothing twice.
      assert (n_hs < n_w1);
      // Delivered in program order, with the data the core wrote.
      if (n_hs < n_w1) assert (o_data == o_exp[n_hs]);
   end
`ifdef LEN32
   // The generator receives the pulse length the program asked for.
   if (o_hs && n_hs < n_w1) assert ({16'd0, o_data[143:128]} == w1_data[n_hs][151:120]);
`endif
`ifdef DISP_AXIS
   // AXIS: once valid, tvalid and tdata hold until accepted.
   if (past_valid && p_ovalid && !p_oready) begin
      assert (o_valid);
      assert (o_data == p_odata);
   end
`endif
end

// ---- Timing: generator accept vs tProc time (TIMING) ----
// The generator's own timing (accept -> output) is proven by sg_v6_timing:
//   start[k] = max(accept[k] + 32, end[k-1] + 1).
// Here: every port-1 command is accepted by the generator exactly D cycles
// after tProc time reaches its timestamp T, never earlier and never later.
// time_abs == T in cycle T + RST_CYC, so accept[k] = T[k] + RST_CYC + D, and
// end to end: start[k] = max(T[k] + RST_CYC + D + 32, end[k-1] + 1).
`ifdef TIMING
wire [9:0] due [0:K-1];
generate for (genvar g = 0; g < K; g = g + 1) begin : GEN_due
   assign due[g] = w1_time[g][9:0] + RST_CYC + D;
end endgenerate

always @(posedge clk) if (rstn) begin
   // Accepted exactly on time.
   if (o_hs && n_hs < n_w1) assert (cyc == due[n_hs]);
   // Not late: once a command is due, it has been accepted.
   for (j = 0; j < K; j = j + 1)
      if (j < n_w1 && cyc > due[j]) assert (n_hs > j);
end
`endif

// ---- Cover ----
reg       p_mtvalid = 0;
reg [3:0] n_rise    = 0;   // output pulses started
reg [7:0] n_on      = 0;   // output cycles with tvalid high
always @(posedge clk) begin
   p_mtvalid <= m_tvalid;
   if (m_tvalid && !p_mtvalid && n_rise != 4'hf) n_rise <= n_rise + 1;
   if (m_tvalid && n_on != 8'hff)                n_on   <= n_on + 1;
end
wire m_rise = m_tvalid && !p_mtvalid;
wire m_fall = !m_tvalid && p_mtvalid;

always @(posedge clk) if (rstn) begin
`ifdef DISP_AXIS
   // Non-vacuity for tp_disp: the dispatcher hands over K commands, one of them
   // after the consumer held it off.
   cover (o_hs && n_hs == K - 1);
   cover (o_hs && past_valid && p_ovalid && !p_oready);
`else
   // Non-vacuity for tp_order / tp_xchan: K commands reach the generator.
   cover (o_hs && n_hs == K - 1);
`endif
   // A port-1 command reaches the generator and the DAC output starts.
   cover (n_w1 == 1 && m_rise);
   // Two port-1 commands play back to back: one unbroken output burst
   // as long as both commands together.
   cover (n_w1 == 2 && n_hs == 2 && m_fall && n_rise == 1
          && n_on == w1_data[0][127:120] + w1_data[1][127:120]);
end

endmodule
