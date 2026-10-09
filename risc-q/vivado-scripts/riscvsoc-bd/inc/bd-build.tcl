# ===========================================================================================
# Assemble the block design: ClockInterface + Zynq PS + user top IP + proc_sys_resets + RF Data
# Converter + AXI SmartConnect. Cell handles ($CLKIFC / $ZYNQ_PS / $TOP / $RFDC) are published at
# script scope for bd-finalize.tcl. Mirrors the RISC-Q utils/*.tcl, merged and proc-free.
# ===========================================================================================

create_bd_design -dir $BUILD_DIR/bd $BD_NAME

# ---- ClockInterface: three external LVDS clock pairs -> single-ended dspClk / hostClk / user_sysref ----
set CLKIFC [create_bd_cell -type module -reference ClockInterface clkifc]

create_bd_intf_port -mode Slave -vlnv xilinx.com:interface:diff_clock_rtl:1.0 dspClk
connect_bd_intf_net [get_bd_intf_ports dspClk] [get_bd_intf_pins $CLKIFC/dspClk_diff]
create_bd_intf_port -mode Slave -vlnv xilinx.com:interface:diff_clock_rtl:1.0 hostClk
connect_bd_intf_net [get_bd_intf_ports hostClk] [get_bd_intf_pins $CLKIFC/hostClk_diff]
create_bd_intf_port -mode Slave -vlnv xilinx.com:interface:diff_clock_rtl:1.0 user_sysref
connect_bd_intf_net [get_bd_intf_ports user_sysref] [get_bd_intf_pins $CLKIFC/user_sysref_diff]

set_property -dict [list CONFIG.FREQ_HZ $DSP_FREQ]  [get_bd_intf_ports dspClk]
set_property -dict [list CONFIG.FREQ_HZ $HOST_FREQ] [get_bd_intf_ports hostClk]
set_property -dict [list CONFIG.FREQ_HZ $DSP_FREQ]  [get_bd_pins $CLKIFC/dspClk]
set_property -dict [list CONFIG.FREQ_HZ $HOST_FREQ] [get_bd_pins $CLKIFC/hostClk]

# ---- Zynq UltraScale+ PS: supplies pl_clk0 / pl_resetn0 / M_AXI_HPM0_LPD ----
set ZYNQ_PS [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:3.5 zynq_ps]
apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e -config {apply_board_preset "1"} \
  [get_bd_cells zynq_ps]
connect_bd_net [get_bd_pins zynq_ps/pl_clk0] [get_bd_pins zynq_ps/maxihpm0_lpd_aclk]

# ---- User top IP ----
set TOP [create_bd_cell -type ip -vlnv user.org:user:${TOP_MODULE}:1.0 top]
connect_bd_net [get_bd_pins $CLKIFC/hostClk] [get_bd_pins $TOP/hostClk]
connect_bd_net [get_bd_pins $CLKIFC/dspClk]  [get_bd_pins $TOP/dspClk]

# ---- proc_sys_reset for each clock domain ----
set PS_RST  [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 ps_rst]
set DSP_RST [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 dsp_rst]
connect_bd_net [get_bd_pins zynq_ps/pl_resetn0] [get_bd_pins ps_rst/ext_reset_in] [get_bd_pins dsp_rst/ext_reset_in]
connect_bd_net [get_bd_pins dsp_rst/peripheral_reset] [get_bd_pins $TOP/dspRst]
connect_bd_net [get_bd_pins ps_rst/peripheral_reset]  [get_bd_pins $TOP/hostRst]
connect_bd_net [get_bd_pins $CLKIFC/hostClk] [get_bd_pins ps_rst/slowest_sync_clk]
connect_bd_net [get_bd_pins $CLKIFC/dspClk]  [get_bd_pins dsp_rst/slowest_sync_clk]

# ---- RF Data Converter (16 DAC + 16 ADC), config verbatim from the RISC-Q reference ----
set RFDC [create_bd_cell -type ip -vlnv xilinx.com:ip:usp_rf_data_converter:2.6 rf_data_converter]
set RFDC_TARGET [get_bd_cells rf_data_converter]
source $INC/rfdc-config.tcl
source $INC/rfdc-connect.tcl

# ---- Optional XCOM board-link IP (RISCQ_WITH_XCOM) ------------------------------------------------
# One xcom BESIDE the SoC rather than inside it. Its AXI-Lite slave carries the only link
# configuration register — xcom_cfg, the bit-rate tick, which resets to 0 and leaves the serializer
# stopped until something writes it — plus board_id / status / debug / rx_dt / tx_dt, which are the
# only instrument available on hardware (there is no VCD on silicon). Hanging that slave off the PS
# SmartConnect makes all of it reachable from Python with no change to PulseTableSoc.
#
# The RISC-V command port (i_core_*) is deliberately NOT connected at this stage: this milestone
# proves the IP synthesises, clocks and links on real silicon, driven entirely from the PS. Wiring
# the core port through XcomMemMap is the next step.
if {$WITH_XCOM} {
  set XCOM [create_bd_cell -type ip -vlnv QICK:QICK:xcom:1.0 xcom]
  set_property -dict [list CONFIG.NCH $XCOM_NCH CONFIG.SYNC 1 CONFIG.DEBUG 1] $XCOM

  # Clocks. The AXI slave sits on hostClk, the same domain as the SoC's S_AXIS, so the SmartConnect
  # still needs only two clocks. The command and link sides sit on dspClk because the time counter
  # xcom ultimately drives (refTime + timeOffset, PulseTableSoc.scala:145) lives there, and reaching
  # it across a domain is what we are trying to avoid.
  connect_bd_net [get_bd_pins $CLKIFC/hostClk] [get_bd_pins $XCOM/i_ps_clk]
  connect_bd_net [get_bd_pins $CLKIFC/dspClk]  [get_bd_pins $XCOM/i_core_clk]
  connect_bd_net [get_bd_pins $CLKIFC/dspClk]  [get_bd_pins $XCOM/i_time_clk]

  # Resets are ACTIVE LOW. peripheral_aresetn, NOT the peripheral_reset nets the SoC uses — driving
  # these from the active-high nets holds xcom in reset forever and every register reads back 0.
  connect_bd_net [get_bd_pins ps_rst/peripheral_aresetn]  [get_bd_pins $XCOM/i_ps_rstn]
  connect_bd_net [get_bd_pins dsp_rst/peripheral_aresetn] [get_bd_pins $XCOM/i_core_rstn]
  connect_bd_net [get_bd_pins dsp_rst/peripheral_aresetn] [get_bd_pins $XCOM/i_time_rstn]

  # Core command port + i_sync tied off for now. i_sync is the external reference tick QRST_SYNC
  # aligns to; nothing in this milestone uses it, and it is the one signal with no fallback once two
  # boards are involved, so it stays an explicit open item rather than an accident.
  set XCOM_GND1  [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 xcom_gnd1]
  set XCOM_GND5  [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 xcom_gnd5]
  set XCOM_GND32 [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 xcom_gnd32]
  set_property -dict [list CONFIG.CONST_WIDTH 1  CONFIG.CONST_VAL 0] $XCOM_GND1
  set_property -dict [list CONFIG.CONST_WIDTH 5  CONFIG.CONST_VAL 0] $XCOM_GND5
  set_property -dict [list CONFIG.CONST_WIDTH 32 CONFIG.CONST_VAL 0] $XCOM_GND32
  connect_bd_net [get_bd_pins $XCOM_GND1/dout]  [get_bd_pins $XCOM/i_core_en]
  connect_bd_net [get_bd_pins $XCOM_GND1/dout]  [get_bd_pins $XCOM/i_sync]
  connect_bd_net [get_bd_pins $XCOM_GND5/dout]  [get_bd_pins $XCOM/i_core_op]
  connect_bd_net [get_bd_pins $XCOM_GND32/dout] [get_bd_pins $XCOM/i_core_data1]
  connect_bd_net [get_bd_pins $XCOM_GND32/dout] [get_bd_pins $XCOM/i_core_data2]

  if {$XCOM_LOOPBACK} {
    # In-fabric loopback: tx straight back to rx, one clock source, no pins, no cable. This is the
    # closest hardware analogue of the passing simulation (which also ran both ends off one clock),
    # so a failure here is synthesis / clocking / constraints and nothing else. Widths only match at
    # NCH=1.
    if {$XCOM_NCH != 1} { error "RISCQ_XCOM_LOOPBACK=1 requires RISCQ_XCOM_NCH=1 (got $XCOM_NCH)" }
    connect_bd_net [get_bd_pins $XCOM/o_xcom_clk]  [get_bd_pins $XCOM/i_xcom_clk]
    connect_bd_net [get_bd_pins $XCOM/o_xcom_data] [get_bd_pins $XCOM/i_xcom_data]
  } else {
    # Out to real pins — PMOD0 drives, PMOD1 listens. Pin assignment in constraints-xcom-zcu216.xdc.
    if {$XCOM_NCH != 1} { error "the pin-out branch is written for RISCQ_XCOM_NCH=1 (got $XCOM_NCH)" }
    create_bd_port -dir O xcom_clk_out
    create_bd_port -dir O xcom_data_out
    create_bd_port -dir I xcom_clk_in
    create_bd_port -dir I xcom_data_in
    connect_bd_net [get_bd_pins $XCOM/o_xcom_clk]  [get_bd_ports xcom_clk_out]
    connect_bd_net [get_bd_pins $XCOM/o_xcom_data] [get_bd_ports xcom_data_out]
    connect_bd_net [get_bd_pins $XCOM/i_xcom_clk]  [get_bd_ports xcom_clk_in]
    connect_bd_net [get_bd_pins $XCOM/i_xcom_data] [get_bd_ports xcom_data_in]
  }
}

# ---- AXI SmartConnect: PS HPM0_LPD -> { top S_AXIS, rfdc s_axi [, QICK gen_v6 s_axi ...] [, xcom s_axi] } ----
# QICK variant: one more manager port per gen's AXI-Lite registers (START_ADDR / WE), on hostClk like
# S_AXIS. The gens' envelope streams (QICKGEN*_S0_AXIS) are left unconnected for now (no envelope DMA
# yet), so the gens can play DDS-only pulses (outsel = 1) but not envelope-shaped ones.
#
# XCOM, when enabled, takes one FURTHER manager port after the gens. Both features add ports, so the
# index comes from the shared $_mi counter below rather than a hardcoded M02 — with RISCQ_QICK=1 and
# RISCQ_WITH_XCOM=1 together, a hardcoded M02 would collide with the first gen.
set _qick_saxi [expr {$QICK ? [get_bd_intf_pins -quiet $TOP/QICKGEN*_S_AXI] : {}}]
set AXI_CONNECT [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 smartconnect]
set_property CONFIG.NUM_SI 1 $AXI_CONNECT
set_property CONFIG.NUM_MI [expr {2 + [llength $_qick_saxi] + ($WITH_XCOM ? 1 : 0)}] $AXI_CONNECT
set_property CONFIG.NUM_CLKS {2} $AXI_CONNECT
set_property CONFIG.HAS_ARESETN {0} $AXI_CONNECT

connect_bd_intf_net [get_bd_intf_pins $AXI_CONNECT/M00_AXI]      [get_bd_intf_pins $TOP/S_AXIS]
connect_bd_intf_net [get_bd_intf_pins $AXI_CONNECT/M01_AXI]      [get_bd_intf_pins rf_data_converter/s_axi]
connect_bd_intf_net [get_bd_intf_pins zynq_ps/M_AXI_HPM0_LPD]    [get_bd_intf_pins $AXI_CONNECT/S00_AXI]

# Manager ports beyond M01 are handed out by a SINGLE counter shared between the optional features,
# because both of them add ports: the QICK gens take one each, then xcom takes the next. Assigning
# xcom a hardcoded M02 works with RISCQ_QICK=0 and silently collides with the first gen when both
# features are on.
set _mi 2
foreach _p $_qick_saxi {
  connect_bd_intf_net [get_bd_intf_pins $AXI_CONNECT/M[format %02d $_mi]_AXI] $_p
  incr _mi
}
if {$WITH_XCOM} {
  connect_bd_intf_net [get_bd_intf_pins $AXI_CONNECT/M[format %02d $_mi]_AXI] [get_bd_intf_pins $XCOM/s_axi]
  incr _mi
}
connect_bd_net      [get_bd_pins zynq_ps/pl_clk0]                [get_bd_pins $AXI_CONNECT/aclk]
connect_bd_net      [get_bd_pins $CLKIFC/hostClk]                [get_bd_pins $AXI_CONNECT/aclk1]

assign_bd_address -offset 0x80000000 -range 0x10000000 \
  -target_address_space [get_bd_addr_spaces zynq_ps/Data] [get_bd_addr_segs $TOP/S_AXIS/reg0] -force
if {$WITH_XCOM} {
  assign_bd_address -offset $XCOM_BASEADDR -range 0x1000 \
    -target_address_space [get_bd_addr_spaces zynq_ps/Data] [get_bd_addr_segs xcom/s_axi/reg0] -force
}
assign_bd_address
