// xsim cross-check for the formal results: real signal_gen_top with the real XPM FIFO,
// real XPM BRAM and the real VHDL data_writer (GEN_DDS="FALSE", so no DDS IP needed).
// Same cycle convention as sg_v6_formal.sv: cyc counts clock edges from 0,
// aresetn = (cyc >= 4), inputs are sampled at the rising edge.
`timescale 1ns/1ps
module tb_sg_char;

localparam N_DDS = 16;

logic clk = 0;
always #1 clk = ~clk;

integer cyc = 0;
always @(posedge clk) cyc <= cyc + 1;
integer rst_at = 0;                       // cycle where the current reset started
wire rstn = (cyc >= rst_at + 4);

logic [159:0]       s1_tdata  = 0;
logic               s1_tvalid = 0;
wire                s1_tready;
wire                m_tvalid;
wire [N_DDS*16-1:0] m_tdata;

signal_gen_top #(.N(12), .N_DDS(N_DDS), .GEN_DDS("FALSE"), .ENVELOPE_TYPE("COMPLEX")) dut (
   .aresetn(rstn), .aclk(clk),
   .s0_axis_aresetn(rstn), .s0_axis_aclk(clk),
   .s0_axis_tdata_i(32'd0), .s0_axis_tvalid_i(1'b0), .s0_axis_tready_o(),
   .s1_axis_tdata_i(s1_tdata), .s1_axis_tvalid_i(s1_tvalid), .s1_axis_tready_o(s1_tready),
   .m_axis_tready_i(1'b1), .m_axis_tvalid_o(m_tvalid), .m_axis_tdata_o(m_tdata),
   .START_ADDR_REG(32'd0), .WE_REG(1'b0)
);

function automatic [159:0] cmd(input [15:0] nsamp, input [15:0] gain);
   cmd = '0;
   cmd[111:96]  = gain;
   cmd[143:128] = nsamp;
   cmd[145:144] = 2'd1;     // outsel = DDS only (constant 0x7FFF when GEN_DDS=FALSE)
endfunction

task automatic tick; @(posedge clk); #0.1; endtask

// Present a command and hold it until accepted (AXIS).
task automatic send(input [159:0] d);
   s1_tdata = d; s1_tvalid = 1;
   @(posedge clk);
   while (!s1_tready) @(posedge clk);
   #0.1; s1_tvalid = 0;
endtask

// ---- Monitors: handshakes and output pulses (split on sample change). ----
integer p_start = -1;
logic [15:0] p_samp;
always @(posedge clk) begin
   if (s1_tvalid && s1_tready)
      $display("HS    cyc=%0d nsamp=%0d gain=%0d", cyc, s1_tdata[143:128], s1_tdata[111:96]);
   if (m_tvalid) begin
      for (int i = 1; i < N_DDS; i++)
         if (m_tdata[i*16 +: 16] !== m_tdata[15:0]) $display("LANE_MISMATCH cyc=%0d lane=%0d", cyc, i);
      if (p_start < 0) begin p_start = cyc; p_samp = m_tdata[15:0]; end
      else if (m_tdata[15:0] !== p_samp) begin
         $display("PULSE start=%0d end=%0d len=%0d samp=%0d", p_start, cyc-1, cyc-p_start, p_samp);
         p_start = cyc; p_samp = m_tdata[15:0];
      end
   end else if (p_start >= 0) begin
      $display("PULSE start=%0d end=%0d len=%0d samp=%0d", p_start, cyc-1, cyc-p_start, p_samp);
      p_start = -1;
   end
end

task automatic do_reset;
   rst_at = cyc;
   repeat (4) tick();
endtask

integer i, n_acc;
initial begin
   // 1. Idle start, isolated pulse (same timing as the formal quiet window: first
   //    command presented at cyc 8).
   $display("=== S1 idle start");
   repeat (8) tick();
   send(cmd(5, 16'd4));
   repeat (60) tick();

   // 2. Three commands back to back (queued), then one late enough to leave a gap.
   $display("=== S2 back-to-back + gap");
   send(cmd(3, 16'd8)); send(cmd(4, 16'd16)); send(cmd(6, 16'd32));
   repeat (40) tick();
   send(cmd(2, 16'd64));
   repeat (60) tick();

   // 3. nsamp = 1 and nsamp = 0.
   $display("=== S3 nsamp=1");
   send(cmd(1, 16'd2));
   repeat (70000) tick();
   $display("=== S3b nsamp=0");
   send(cmd(0, 16'd128));
   repeat (70000) tick();

   // 4. Commands right after reset release: one per trial at offset k.
   $display("=== S4 post-reset drop");
   for (i = 0; i < 6; i++) begin
      do_reset();
      repeat (i) tick();
      $display("TRIAL offset=%0d cyc=%0d", i, cyc);
      send(cmd(3, 16'd256));
      repeat (60) tick();
   end

   // 5. Queue capacity: long pulses sent back to back until tready drops.
   $display("=== S5 capacity");
   do_reset(); repeat (8) tick();
   n_acc = 0;
   s1_tvalid = 1; s1_tdata = cmd(1000, 16'd1);
   for (i = 0; i < 40; i++) begin
      @(posedge clk);
      if (s1_tready) n_acc++;
      else begin $display("CAPACITY tready_low_after=%0d accepted cyc=%0d", n_acc, cyc); break; end
   end
   #0.1; s1_tvalid = 0;
   // Time until tready comes back while the generator plays 1000-cycle pulses.
   i = cyc;
   while (!s1_tready) @(posedge clk);
   $display("CAPACITY tready_back_at cyc=%0d (low for %0d)", cyc, cyc - i);
   $finish;
end

endmodule
