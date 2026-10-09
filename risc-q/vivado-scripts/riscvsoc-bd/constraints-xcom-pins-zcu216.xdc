# XCOM link pinout for the ZCU216, used only when RISCQ_XCOM_LOOPBACK=0.
#
# Pin numbers are taken from QICK's own ZCU216 project
# (firmware/projects/qick_tprocv2_216_standard/ios.xdc) rather than re-derived from the board file.
# PMOD0 transmits, PMOD1 listens, so a single-board cable loopback is a two-wire jumper between the
# two headers and a two-board link is the same cable between boards.
#
#   xcom_clk_out  -> PMOD0_0  G15
#   xcom_data_out -> PMOD0_1  G16
#   xcom_clk_in   <- PMOD1_0  L17
#   xcom_data_in  <- PMOD1_1  M17
#
# Both headers are 1.8 V banks on this board: LVCMOS18, not LVCMOS33.

set_property -dict {PACKAGE_PIN G15 IOSTANDARD LVCMOS18} [get_ports xcom_clk_out]
set_property -dict {PACKAGE_PIN G16 IOSTANDARD LVCMOS18} [get_ports xcom_data_out]
set_property -dict {PACKAGE_PIN L17 IOSTANDARD LVCMOS18} [get_ports xcom_clk_in]
set_property -dict {PACKAGE_PIN M17 IOSTANDARD LVCMOS18} [get_ports xcom_data_in]

# The received clock and data are asynchronous to this board's time clock — that is the whole point
# of the 2-FF synchronizers downstream. Without these exceptions Vivado times a path from an
# unrelated external source and reports unfixable violations. The link's real timing budget is cable
# clk-to-data skew, which belongs on a scope, not in the static timing report.
set_false_path -from [get_ports xcom_clk_in]
set_false_path -from [get_ports xcom_data_in]

# The transmit pair is source-synchronous and read by the far end on its own received clock, so the
# tool has no meaningful destination to time these against either.
set_false_path -to [get_ports xcom_clk_out]
set_false_path -to [get_ports xcom_data_out]
