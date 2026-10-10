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
update_compile_order -fileset sources_1
