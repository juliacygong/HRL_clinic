// Characterizes the real fifo_xpm wrapper (xpm_fifo_sync, FWFT, depth 16) in xsim.
`timescale 1ns/1ps
module tb_fifo_char;

localparam B = 8;
localparam N = 16;

logic clk = 0;
logic rstn = 0;
logic wr_en = 0;
logic [B-1:0] din = 0;
logic rd_en = 0;
logic [B-1:0] dout;
logic full, empty;

always #1 clk = ~clk;

fifo_xpm #(.B(B), .N(N)) dut (
   .rstn (rstn), .clk (clk),
   .wr_en(wr_en), .din(din),
   .rd_en(rd_en), .dout(dout),
   .full (full), .empty(empty)
);

integer cyc = 0;
always @(posedge clk) cyc <= cyc + 1;

task automatic tick; @(posedge clk); #0.1; endtask

integer i, t0, accepted, first_ok;
initial begin
   // --- 1. For each offset k after reset release, do a single write and see if it lands.
   first_ok = -1;
   for (i = 0; i < 40 && first_ok < 0; i++) begin
      rstn = 0; repeat (4) tick();
      rstn = 1;
      repeat (i) tick();
      din = 8'hA0; wr_en = 1;
      if (full) $display("RESULT full_high_at_offset=%0d", i);
      tick(); wr_en = 0;
      repeat (8) tick();
      if (!empty) begin
         first_ok = i;
         $display("RESULT post_reset_first_accepted_write_offset=%0d", i);
      end
   end
   rstn = 0; repeat (4) tick(); rstn = 1; repeat (40) tick();

   // --- 2. Write -> empty deassert latency (FIFO idle and empty).
   repeat (4) tick();
   din = 8'h55; wr_en = 1; t0 = cyc; tick(); wr_en = 0;
   while (empty) tick();
   rd_en = 1; #0.01;
   $display("RESULT write_to_not_empty_cycles=%0d dout_matches=%0d", cyc - t0, dout == 8'h55);
   tick(); rd_en = 0;
   $display("RESULT empty_after_pop=%0d", empty);

   // --- 3. Capacity: write until full, no reads.
   repeat (4) tick();
   accepted = 0;
   for (i = 0; i < 40; i++) begin
      din = i; wr_en = 1;
      if (!full) accepted++;
      tick();
   end
   wr_en = 0;
   repeat (4) tick();
   $display("RESULT capacity_words=%0d full=%0d", accepted, full);

   // --- 4. Read one word from full: cycles until full deasserts.
   rd_en = 1; t0 = cyc; tick(); rd_en = 0;
   while (full) tick();
   $display("RESULT read_to_not_full_cycles=%0d", cyc - t0);

   // --- 5. Drain and check ordering (word 0 was popped in step 4).
   i = 1;
   while (!empty) begin
      // fifo_xpm only presents the head word on dout while rd_en is high.
      rd_en = 1; #0.01;
      if (dout !== i[B-1:0]) $display("RESULT order_mismatch at %0d got %0d", i, dout);
      tick(); rd_en = 0; i++;
      tick();
   end
   $display("RESULT drained=%0d", i);
   $finish;
end

endmodule
