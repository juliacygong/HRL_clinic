# ---- Validate, generate the HDL wrapper, add constraints, set the top ------------------------------
validate_bd_design

make_wrapper -files [get_files $BD_NAME.bd] -top -import -force
generate_target all [get_files $BD_NAME.bd]
close_bd_design $BD_NAME

set_property top ${BD_NAME}_wrapper [current_fileset]

if {[file exists $SCRIPT_DIR/constraints-zcu216.xdc]} {
  add_files -fileset constrs_1 -norecurse $SCRIPT_DIR/constraints-zcu216.xdc
}

# The board DAC reference clock: 500 MHz for the RISC-Q DACs (tile-2 PLL ref, rfdc-config.tcl), or QICK's
# 245.76 MHz for the QICK variant (× 39 = 9.58464 GS/s). Generated here because it depends on the variant.
set _dac_ref_mhz [expr {$QICK ? 245.76 : 500.0}]
set _fh [open $BUILD_DIR/constraints-dacclk.xdc w]
puts $_fh "create_clock -period [format %.3f [expr {1000.0 / $_dac_ref_mhz}]] -name dac_clk_clk_p \[get_ports {dac_clk_clk_p}\]"
close $_fh
add_files -fileset constrs_1 -norecurse $BUILD_DIR/constraints-dacclk.xdc

# XCOM constraints: the CDC exceptions whenever the IP is in the design, the pinout only when the
# link actually leaves the die (in-fabric loopback creates no ports for those pins to attach to, and
# an xdc referencing non-existent ports is a hard error).
if {$WITH_XCOM} {
  add_files -fileset constrs_1 -norecurse $SCRIPT_DIR/constraints-xcom.xdc
  if {!$XCOM_LOOPBACK} {
    add_files -fileset constrs_1 -norecurse $SCRIPT_DIR/constraints-xcom-pins-zcu216.xdc
  }
}
update_compile_order -fileset sources_1
