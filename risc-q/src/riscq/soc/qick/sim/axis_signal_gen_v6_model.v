// SIM-ONLY behavioural stand-in for QICK axis_signal_gen_v6 (firmware/ip/axis_signal_gen_v6), with the
// same module name and ports so the SpinalHDL BlackBox binds to it under Verilator. The real IP is VHDL +
// a DDS Compiler sub-core and only runs in Vivado.
//
// Timing (from the xsim characterisation in firmware/formal/README.md, branch formal/sg-v6-tproc-v2):
//   - s1 accept -> first m_axis_tvalid = LATENCY (32) aclk on an idle generator;
//   - each pulse is valid for exactly nsamp cycles; queued pulses play back to back with no gap;
//   - s1_axis_tready = command FIFO not full.
// Datapath (from signal_gen.v / ctrl_sg_v6.sv), per output sample s of a pulse, lane i of a cycle:
//   theta    = phase + freq * n            n = free-running sample count (0 at start when phrst = 1)
//   dds      = 32767 * (cos, sin)(2*pi*theta / 2^32)                (DDS Compiler, 16-bit full range)
//   env      = table[addr*N_DDS + 16*cycle + i]  {Q[31:16], I[15:0]} loaded through s0_axis while WE = 1
//   x        = outsel 0: (dds.re*env.I - dds.im*env.Q) >> 16  |  1: dds.re  |  2: env.I  |  3: 0
//   sample   = (x * gain) >> 15              (16-bit)
//   idle     = stdysel 0: hold the last sample of the pulse  |  1: 0
// NOT modelled: mode = 1 (periodic replay), DDS phase dithering/quantisation (the model uses real cos).
module axis_signal_gen_v6 #(
   parameter N             = 12,
   parameter N_DDS         = 16,
   parameter GEN_DDS       = "TRUE",
   parameter ENVELOPE_TYPE = "COMPLEX",
   parameter LATENCY       = 32,
   parameter DEPTH         = 16
) (
   input  wire                s_axi_aclk,
   input  wire                s_axi_aresetn,
   input  wire [5:0]          s_axi_awaddr,
   input  wire [2:0]          s_axi_awprot,
   input  wire                s_axi_awvalid,
   output wire                s_axi_awready,
   input  wire [31:0]         s_axi_wdata,
   input  wire [3:0]          s_axi_wstrb,
   input  wire                s_axi_wvalid,
   output wire                s_axi_wready,
   output wire [1:0]          s_axi_bresp,
   output reg                 s_axi_bvalid,
   input  wire                s_axi_bready,
   input  wire [5:0]          s_axi_araddr,
   input  wire [2:0]          s_axi_arprot,
   input  wire                s_axi_arvalid,
   output wire                s_axi_arready,
   output reg  [31:0]         s_axi_rdata,
   output wire [1:0]          s_axi_rresp,
   output reg                 s_axi_rvalid,
   input  wire                s_axi_rready,
   input  wire                s0_axis_aclk,
   input  wire                s0_axis_aresetn,
   input  wire [31:0]         s0_axis_tdata,
   input  wire                s0_axis_tvalid,
   output wire                s0_axis_tready,
   input  wire                aclk,
   input  wire                aresetn,
   input  wire [159:0]        s1_axis_tdata,
   input  wire                s1_axis_tvalid,
   output wire                s1_axis_tready,
   input  wire                m_axis_tready,
   output wire                m_axis_tvalid,
   output wire [N_DDS*16-1:0] m_axis_tdata
);
   // ---------------- AXI-Lite registers (s_axi_aclk) ----------------
   reg [31:0] start_addr_reg, we_reg;
   wire       aw_fire = s_axi_awvalid & s_axi_wvalid & ~s_axi_bvalid;
   assign s_axi_awready = aw_fire;
   assign s_axi_wready  = aw_fire;
   assign s_axi_bresp   = 2'b00;
   assign s_axi_arready = ~s_axi_rvalid;
   assign s_axi_rresp   = 2'b00;
   always @(posedge s_axi_aclk) begin
      if (!s_axi_aresetn) begin
         start_addr_reg <= 0; we_reg <= 0; s_axi_bvalid <= 0; s_axi_rvalid <= 0; s_axi_rdata <= 0;
      end else begin
         if (aw_fire) begin
            if (s_axi_awaddr[5:2] == 4'd0) start_addr_reg <= s_axi_wdata;
            if (s_axi_awaddr[5:2] == 4'd1) we_reg         <= s_axi_wdata;
            s_axi_bvalid <= 1;
         end else if (s_axi_bready) s_axi_bvalid <= 0;
         if (s_axi_arvalid & ~s_axi_rvalid) begin
            s_axi_rvalid <= 1;
            s_axi_rdata  <= (s_axi_araddr[5:2] == 4'd0) ? start_addr_reg :
                            (s_axi_araddr[5:2] == 4'd1) ? we_reg : 32'd0;
         end else if (s_axi_rready) s_axi_rvalid <= 0;
      end
   end

   // ---------------- envelope table: s0_axis writes while WE = 1, from START_ADDR ----------------
   localparam TABLE = (1 << N) * N_DDS;
   reg [31:0] env [0:TABLE-1];
   reg [31:0] wr_ptr, s0_words;
   reg        we_r;
   assign s0_axis_tready = 1'b1;
   always @(posedge s0_axis_aclk)
      if (!s0_axis_aresetn) begin s0_words <= 0; wr_ptr <= 0; we_r <= 0; end
      else begin
         we_r <= we_reg[0];
         if (we_reg[0] && !we_r) wr_ptr <= start_addr_reg;          // WE rising edge reloads the pointer
         else if (we_reg[0] && s0_axis_tvalid) begin
            env[wr_ptr % TABLE] <= s0_axis_tdata;
            wr_ptr <= wr_ptr + 1;
            s0_words <= s0_words + 1;
         end
      end

   // ---------------- command queue (aclk) ----------------
   reg [63:0]  cyc;
   reg [159:0] q_word [0:DEPTH-1];
   reg [63:0]  q_due  [0:DEPTH-1];
   reg [$clog2(DEPTH):0]   q_cnt;
   reg [$clog2(DEPTH)-1:0] q_wp, q_rp;
   wire accept   = s1_axis_tvalid & s1_axis_tready;
   wire head_due = (q_cnt != 0) && (cyc >= q_due[q_rp]);
   assign s1_axis_tready = (q_cnt != DEPTH);

   // ---------------- player ----------------
   reg         playing;
   reg [15:0]  left;
   reg [31:0]  pinc, theta0;      // theta of lane 0 this cycle
   reg [15:0]  gain, waddr;
   reg [1:0]   outsel;
   reg         stdysel;
   reg [31:0]  samp_cnt;          // free-running sample counter (+N_DDS per cycle)
   reg [15:0]  out   [0:N_DDS-1];
   reg [15:0]  last;
   wire start = head_due && (!playing || left == 16'd1);
   wire [159:0] hw = q_word[q_rp];

   assign m_axis_tvalid = playing;
   genvar gi;
   generate for (gi = 0; gi < N_DDS; gi = gi + 1) begin : lanes
      assign m_axis_tdata[gi*16 +: 16] = playing ? out[gi] : (stdysel ? 16'h0000 : last);
   end endgenerate

   function automatic [15:0] sample(input [31:0] theta, input [31:0] e, input [1:0] sel, input [15:0] g);
      real    ang;
      integer dre, dim, ei, eq, x;
      longint y;
      begin
         ang = 6.283185307179586 * $itor(theta) / 4294967296.0;
         dre = $rtoi(32767.0 * $cos(ang) + (($cos(ang) >= 0) ? 0.5 : -0.5));
         dim = $rtoi(32767.0 * $sin(ang) + (($sin(ang) >= 0) ? 0.5 : -0.5));
         ei  = $signed(e[15:0]);
         eq  = $signed(e[31:16]);
         case (sel)
            2'd0: x = (dre * ei - dim * eq) >>> 16;
            2'd1: x = dre;
            2'd2: x = ei;
            default: x = 0;
         endcase
         y = (longint'(x) * longint'($signed(g))) >>> 15;
         sample = y[15:0];
      end
   endfunction

   integer li;
   reg [31:0] th;
   always @(posedge aclk) begin
      if (!aresetn) begin
         cyc <= 0; q_cnt <= 0; q_wp <= 0; q_rp <= 0; playing <= 0; left <= 0; samp_cnt <= 0; last <= 0;
         stdysel <= 1; outsel <= 0; gain <= 0; pinc <= 0; theta0 <= 0; waddr <= 0;
         for (li = 0; li < N_DDS; li = li + 1) out[li] <= 0;
      end else begin
         cyc      <= cyc + 1;
         samp_cnt <= samp_cnt + N_DDS;
         if (accept) begin
            q_word[q_wp] <= s1_axis_tdata;
            q_due[q_wp]  <= cyc + LATENCY - 1;   // tvalid rises LATENCY cycles after the accept edge
            q_wp         <= q_wp + 1;
         end
         if (start) begin
            // fields: freq[31:0] phase[63:32] addr[79:64] gain[111:96] nsamp[143:128] outsel[145:144] mode[146] stdysel[147] phrst[148]
            th = hw[63:32] + hw[31:0] * (hw[148] ? 32'd0 : samp_cnt);
            for (li = 0; li < N_DDS; li = li + 1)
               out[li] <= sample(th + hw[31:0] * li, env[(hw[79:64] * N_DDS + li) % TABLE], hw[145:144], hw[111:96]);
            pinc    <= hw[31:0];
            theta0  <= th + hw[31:0] * N_DDS;
            waddr   <= hw[79:64] + 1;
            gain    <= hw[111:96];
            outsel  <= hw[145:144];
            stdysel <= hw[147];
            left    <= hw[143:128];
            playing <= 1;
            q_rp    <= q_rp + 1;
         end else if (playing) begin
            if (left == 16'd1) begin
               playing <= 0;
               last    <= out[N_DDS-1];
            end else begin
               for (li = 0; li < N_DDS; li = li + 1)
                  out[li] <= sample(theta0 + pinc * li, env[(waddr * N_DDS + li) % TABLE], outsel, gain);
               theta0 <= theta0 + pinc * N_DDS;
               waddr  <= waddr + 1;
            end
            left <= left - 1;
         end
         q_cnt <= q_cnt + (accept ? 1 : 0) - (start ? 1 : 0);
      end
   end
endmodule
