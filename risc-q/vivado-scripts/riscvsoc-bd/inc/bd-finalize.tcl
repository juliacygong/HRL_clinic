# ---- Validate, generate the HDL wrapper, add constraints, set the top ------------------------------
validate_bd_design

make_wrapper -files [get_files $BD_NAME.bd] -top -import -force
generate_target all [get_files $BD_NAME.bd]
close_bd_design $BD_NAME

set_property top ${BD_NAME}_wrapper [current_fileset]

# constraints-zcu216.xdc times dspClk and the board adc_clk at 500 MHz. A build at another dsp clock or ADC
# rate (the QICK-clock build: dspClk 307.2 MHz, adc_clk = QICK's 245.76 MHz ADC PLL reference, rfdc-config.tcl)
# gets a copy in the build dir with those two periods replaced; the default build adds the file unchanged.
set _xdc $SCRIPT_DIR/constraints-zcu216.xdc
set _adc_ref_mhz [expr {$ADC_FS != 2000000000 ? 245.76 : 500.0}]
if {[file exists $_xdc] && ($DSP_FREQ != 500000000 || $_adc_ref_mhz != 500.0)} {
  set _fh [open $_xdc r]; set _txt [read $_fh]; close $_fh
  foreach {_name _mhz} [list dspClk_clk_p [expr {$DSP_FREQ / 1e6}] adc_clk_clk_p $_adc_ref_mhz] {
    set _old "create_clock -period 2.000 -name $_name"
    set _new "create_clock -period [format %.3f [expr {1000.0 / $_mhz}]] -name $_name"
    if {[string first $_old $_txt] < 0} { error "bd-finalize: no '$_old' in $_xdc to retime" }
    set _txt [string map [list $_old $_new] $_txt]
    puts "\[bd-finalize\] $_name: $_new"
  }
  set _xdc $BUILD_DIR/constraints-zcu216.xdc
  set _fh [open $_xdc w]; puts -nonewline $_fh $_txt; close $_fh
}
if {[file exists $_xdc]} {
  add_files -fileset constrs_1 -norecurse $_xdc
}

# The board DAC reference clock: 500 MHz for the RISC-Q DACs (tile-2 PLL ref, rfdc-config.tcl), or QICK's
# 245.76 MHz for a QICK variant at its own gen rate (× 39 = 9.58464 GS/s). Generated here because it depends
# on the variant.
set _dac_ref_mhz [expr {$QICK && $GEN_FREQ != $DSP_FREQ ? 245.76 : 500.0}]
set _fh [open $BUILD_DIR/constraints-dacclk.xdc w]
puts $_fh "create_clock -period [format %.3f [expr {1000.0 / $_dac_ref_mhz}]] -name dac_clk_clk_p \[get_ports {dac_clk_clk_p}\]"
close $_fh
add_files -fileset constrs_1 -norecurse $BUILD_DIR/constraints-dacclk.xdc
update_compile_order -fileset sources_1
