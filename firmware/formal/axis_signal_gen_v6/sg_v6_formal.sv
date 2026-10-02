// Formal harness for axis_signal_gen_v6 command timing (signal_gen_top, no tProc).
//
// Free inputs: s1_tdata / s1_tvalid (command stream) and m_tready.
// Reference timing model, checked every cycle against the real output:
//   start[k] = max(accept[k] + L, end[k-1] + 1)
//   end[k]   = start[k] + nsamp[k] - 1
//   m_axis_tvalid is high exactly on [start[k], end[k]] for some k.
// With CHECK_DATA, the sample on every lane is also checked against the gain of
// the command that should be playing (outsel=1 and GEN_DDS="FALSE" make the
// output a known function of gain), which proves ordering and alignment.
//
// Defines (set per task in sg_v6.sby):
//   USE_DDS     - build with GEN_DDS="TRUE" (DDS IP replaced by a free-output stub)
//   CHECK_DATA  - compare output samples, not just tvalid timing
//   ACCEPT      - queue-capacity checks instead of the timing model
module sg_v6_formal #(
   parameter      N_DDS     = 16,
`ifdef USE_DDS
   parameter      GEN_DDS   = "TRUE",
`else
   parameter      GEN_DDS   = "FALSE",
`endif
   parameter      K         = 3,     // commands tracked by the timing model
   parameter      L         = 32,    // accept -> first valid sample, idle generator
   parameter      NMIN      = 2,     // nsamp range allowed for commands
   parameter      NMAX      = 6,
   parameter      RST_CYC   = 4,     // aresetn low for cycles [0, RST_CYC)
   parameter      RST_QUIET = 4,     // no commands for this many cycles after reset
   parameter      QDEPTH    = 19     // expected accepted-but-not-started capacity
) (
   input  wire                clk,
   input  wire [159:0]        s1_tdata,
   input  wire                s1_tvalid,
   input  wire                m_tready
);

// ---- Clock ----
reg [9:0] cyc = 0;
always @(posedge clk) if (cyc != 10'h3ff) cyc <= cyc + 1;

wire rstn = (cyc >= RST_CYC);

// ---- DUT ----
wire                   s1_tready;
wire                   m_tvalid;
wire [N_DDS*16-1:0]    m_tdata;

signal_gen_top #(
   .N             (4          ),
   .N_DDS         (N_DDS      ),
   .GEN_DDS       (GEN_DDS    ),
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

// ---- Command fields ----
wire [15:0] f_gain   = s1_tdata[111:96];
wire [15:0] f_nsamp  = s1_tdata[143:128];
wire [1:0]  f_outsel = s1_tdata[145:144];
wire        f_mode   = s1_tdata[146];
wire        hs       = s1_tvalid && s1_tready;

// Output sample for outsel=1 with GEN_DDS="FALSE": the DDS path is the constant 0x7FFF,
// times gain, rounded as in signal_gen.v (round = prod[30:15]). Gains are restricted
// to powers of two 2^k (k < 15) to act as tags: 0x7FFF * 2^k = 2^(15+k) - 2^k, so
// prod[30:15] = 2^k - 1. This keeps the solver from having to prove two multipliers
// equal, which SAT-based engines handle very poorly.
wire        [15:0] f_samp = f_gain - 16'd1;

// ---- AXIS master behaviour ----
reg          past_valid  = 0;
reg          p_tvalid    = 0;
reg          p_tready    = 0;
reg [159:0]  p_tdata     = 0;
always @(posedge clk) begin
   past_valid <= 1;
   p_tvalid   <= s1_tvalid;
   p_tready   <= s1_tready;
   p_tdata    <= s1_tdata;
end

reg [5:0] n_acc = 0;   // accepted commands (saturating)
always @(posedge clk) if (hs && n_acc != 6'h3f) n_acc <= n_acc + 1;

always @* begin
   // No commands during reset or the quiet window after it.
   if (cyc < RST_CYC + RST_QUIET) assume (!s1_tvalid);

   // AXIS: once valid, hold valid and data until accepted.
   if (past_valid && p_tvalid && !p_tready) assume (s1_tvalid && s1_tdata == p_tdata);

   if (s1_tvalid) begin
      assume (f_mode == 1'b0);                         // one-shot pulses
      assume (f_nsamp >= NMIN && f_nsamp <= NMAX);
`ifdef CHECK_DATA
      assume (f_outsel == 2'd1);                       // DDS-only source (constant)
      // Power-of-two gain tags (one-hot in [14:0]).
      assume (!f_gain[15] && f_gain != 0 && (f_gain & (f_gain - 16'd1)) == 0);
`endif
   end
end

`ifdef ACCEPT
// ---- Queue capacity / acceptance ----
// Counts rising edges of tvalid; only used to know whether any pulse has started.
reg [5:0] n_started = 0;
reg       p_mtvalid = 0;
always @(posedge clk) p_mtvalid <= m_tvalid;
always @(posedge clk) if (m_tvalid && !p_mtvalid && n_started != 6'h3f) n_started <= n_started + 1;

always @(posedge clk) if (rstn && cyc >= RST_CYC + RST_QUIET) begin
   // tready only drops once QDEPTH commands are waiting (none has started yet).
   if (!s1_tready && n_started == 0) assert (n_acc >= QDEPTH);
   cover (!s1_tready);
   // Tight: the queue fills after exactly QDEPTH accepted commands.
   cover (!s1_tready && n_acc == QDEPTH);
   // tready recovers after the queue drains by one.
   cover (past_valid && !p_tready && s1_tready);
end

`else
// ---- Reference timing ----
reg [9:0]  m_start [0:K-1];
reg [9:0]  m_end   [0:K-1];
reg [15:0] m_samp  [0:K-1];
reg [9:0]  last_end = 0;
reg        have_last = 0;

integer j;
initial for (j = 0; j < K; j = j + 1) begin
   m_start[j] = 0; m_end[j] = 0; m_samp[j] = 0;
end

wire [9:0] earliest = cyc + L;
wire [9:0] after    = last_end + 1;
wire [9:0] nstart   = (have_last && after > earliest) ? after : earliest;
wire [9:0] nend     = nstart + f_nsamp[9:0] - 1;

always @(posedge clk) if (hs && n_acc < K) begin
   m_start[n_acc] <= nstart;
   m_end  [n_acc] <= nend;
   m_samp [n_acc] <= f_samp;
   last_end       <= nend;
   have_last      <= 1;
end

// Only K commands are tracked.
always @* if (n_acc >= K) assume (!s1_tvalid);

reg        exp_valid;
reg [15:0] exp_samp;
always @* begin
   exp_valid = 0;
   exp_samp  = 0;
   for (j = 0; j < K; j = j + 1)
      if (j < n_acc && cyc >= m_start[j] && cyc <= m_end[j]) begin
         exp_valid = 1;
         exp_samp  = m_samp[j];
      end
end

genvar g;
always @(posedge clk) if (cyc >= 1) begin
   assert (m_tvalid == exp_valid);
end

`ifdef CHECK_DATA
generate for (g = 0; g < N_DDS; g = g + 1) begin : GEN_lane
   always @(posedge clk) if (cyc >= 1 && exp_valid)
      assert (m_tdata[g*16 +: 16] == exp_samp);
end endgenerate

// Kept so cover traces show the samples (otherwise optimized out of the VCD).
(* keep *) wire [15:0] w_lane0   = m_tdata[15:0];
(* keep *) wire [15:0] w_lane1   = m_tdata[N_DDS*16-1 -: 16];
(* keep *) wire [15:0] w_exp     = exp_samp;
(* keep *) wire        w_expv    = exp_valid;
`endif

// Scenarios the checks must actually exercise (non-vacuity).
always @(posedge clk)
   // Idle start: first pulse begins L cycles after acceptance.
   cover (n_acc >= 1 && cyc == m_start[0] && m_tvalid);

generate if (K >= 3) begin : GEN_cov
always @(posedge clk) begin
   // Back-to-back: pulse 1 starts the cycle after pulse 0 ends (no gap).
   cover (n_acc >= 2 && m_start[1] == m_end[0] + 1 && cyc == m_start[1] && m_tvalid);
   // Gap: pulse 1 was accepted too late to follow pulse 0 directly.
   cover (n_acc >= 2 && m_start[1] >  m_end[0] + 1 && cyc == m_start[1] && m_tvalid);
   // Three queued pulses played gaplessly.
   cover (n_acc >= 3 && m_start[1] == m_end[0] + 1 && m_start[2] == m_end[1] + 1
          && cyc == m_end[2] && m_tvalid);
`ifdef CHECK_DATA
   // Same, with three different gain tags, so the samples show the playing order.
   cover (n_acc >= 3 && m_start[1] == m_end[0] + 1 && m_start[2] == m_end[1] + 1
          && m_samp[0] != m_samp[1] && m_samp[1] != m_samp[2] && m_samp[0] != m_samp[2]
          && cyc == m_end[2] && m_tvalid);
`endif
end
end endgenerate
`endif

endmodule
