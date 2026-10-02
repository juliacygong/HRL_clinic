// Formal-only stand-ins for blocks that are not on the command/timing path of
// axis_signal_gen_v6. The FIFO (fifo_xpm -> xpm_fifo_sync) is NOT stubbed: the real
// Xilinx XPM source is read through yosys-slang.

// Envelope loader (data_writer.vhd). The s0 envelope-load path is tied off in the
// formal wrapper, so this never writes the envelope memories.
module data_writer #(
   parameter NT = 16,
   parameter N  = 16,
   parameter B  = 32
) (
   input  wire            rstn,
   input  wire            clk,
   output wire            s_axis_tready,
   input  wire [B-1:0]    s_axis_tdata,
   input  wire            s_axis_tvalid,
   output wire [NT-1:0]   mem_en,
   output wire            mem_we,
   output wire [N-1:0]    mem_addr,
   output wire [B-1:0]    mem_di,
   input  wire [31:0]     START_ADDR_REG,
   input  wire            WE_REG
);
assign s_axis_tready = 1'b0;
assign mem_en        = '0;
assign mem_we        = 1'b0;
assign mem_addr      = '0;
assign mem_di        = '0;
endmodule

// Envelope BRAM (bram_dp_xpm -> xpm_memory_tdpram). Envelope values only feed the
// data path, never the control/valid path, so port B returns unconstrained data.
module bram_dp_xpm #(
   integer OUT_REG_ENA = 0,
   integer N   = 16,
   integer B   = 16
) (
   input  wire          clka,
   input  wire          clkb,
   input  wire          ena,
   input  wire          enb,
   input  wire          wea,
   input  wire          web,
   input  wire [N-1:0]  addra,
   input  wire [N-1:0]  addrb,
   input  wire [B-1:0]  dia,
   input  wire [B-1:0]  dib,
   output logic [B-1:0] doa,
   output wire [B-1:0]  dob
);
assign doa = '0;
// dob left undriven: the .sby script turns undriven nets into free inputs.
endmodule

// DDS compiler IP (Xilinx, encrypted). Its output only feeds the data path, so it
// returns unconstrained data. Timing-path checks with GEN_DDS="TRUE" use this.
module dds_compiler_0 (
   input  wire         aclk,
   input  wire         s_axis_phase_tvalid,
   input  wire [71:0]  s_axis_phase_tdata,
   output wire         m_axis_data_tvalid,
   output wire [31:0]  m_axis_data_tdata
);
assign m_axis_data_tvalid = 1'b1;
// m_axis_data_tdata left undriven (free input, see .sby).
endmodule
