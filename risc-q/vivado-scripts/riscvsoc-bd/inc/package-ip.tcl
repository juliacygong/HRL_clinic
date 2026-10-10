# ---- Package the SpinalHDL top as a user IP -------------------------------------------------------
# Vivado infers the AXI / AXI-Stream / clock bus interfaces from the X_INTERFACE_INFO attributes the
# `vivado=true` RTL carries; here we only have to (a) stamp the clock FREQ_HZ and reset POLARITY bus
# parameters and (b) bind each bus interface to its clock — S_AXIS to the 100 MHz hostClk, every
# DAC{i}_AXIS / ADC{i}_AXIS to the 500 MHz dspClk. Ported from the RISC-Q `plip.tcl`.

# OOC synthesis clocks for the packaged IP. Vivado gives a packaged user IP NO clocks in its
# out-of-context child synth run, so that run maps UNTIMED — measured on the 14q SoC: the DSP
# mapper then leaves the ComplexMul MREG stage empty (108 DSP48s at DRC DPOP-4, mult→ALU→P
# combinational at 500 MHz) and the pg-cordic cone collapses the whole build; the identical
# netlist synthesized WITH these clocks maps MREG correctly (DPOP-4 = 0). The XDC must be a
# project source BEFORE ipx::package_project -import_files, or the packager drops it
# (IP_Flow 19-5109); the `out_of_context` USED_IN tag scopes it to the OOC child run only —
# in-context, the BD's real clocks rule.
set fh [open $SOURCE_PATH/PulseTableSoc_ooc.xdc w]
puts $fh "create_clock -name dspClk -period [format %.3f [expr {1e9 / $DSP_FREQ}]] \[get_ports dspClk\]"
puts $fh "create_clock -name hostClk -period [format %.3f [expr {1e9 / $HOST_FREQ}]] \[get_ports hostClk\]"
if {$QICK} {
  puts $fh "create_clock -name genClk -period [format %.3f [expr {1e9 / $GEN_FREQ}]] \[get_ports genClk\]"
  puts $fh "set_clock_groups -asynchronous -group dspClk -group hostClk -group genClk"
}
close $fh
add_files -fileset constrs_1 $SOURCE_PATH/PulseTableSoc_ooc.xdc
set_property USED_IN {synthesis implementation out_of_context} [get_files $SOURCE_PATH/PulseTableSoc_ooc.xdc]

ipx::package_project -root_dir $IP_REPO -vendor user.org -library user -taxonomy /UserIP \
  -import_files -set_current false -force -quiet
ipx::open_ipxact_file $IP_REPO/component.xml

# ensure the packaged copy keeps the OOC scoping, then drop the project-side entry (the IP holds
# its own imported copy; the outer BD project must not carry an IP-port create_clock).
foreach _g [ipx::get_file_groups -of_objects [ipx::current_core]] {
  foreach _f [ipx::get_files -of_objects $_g "*PulseTableSoc_ooc.xdc"] {
    set_property USED_IN {synthesis implementation out_of_context} $_f
  }
}
remove_files [get_files $SOURCE_PATH/PulseTableSoc_ooc.xdc]

# the packager writes the .bin ROM inits as fileType "unknown"; mark them mem so the IP's OOC synth run
# reads them as $readmemb data
foreach _g [ipx::get_file_groups -of_objects [ipx::current_core]] {
  foreach _f [ipx::get_files -of_objects $_g "*.bin"] { set_property type mem $_f }
}

# QICK: the gen's scoped XDC now lives in the IP (applied in its OOC run); drop the project-side copy,
# or the BD wrapper's synth_1 — where the IP is a black box — warns it cannot find axis_signal_gen_v6.
if {$QICK} { remove_files [get_files -of_objects [get_filesets constrs_1] *signal_gen_v6.xdc] }

# clock frequencies
ipx::add_bus_parameter FREQ_HZ [ipx::get_bus_interfaces hostClk -of_objects [ipx::current_core]]
set_property value $HOST_FREQ [ipx::get_bus_parameters FREQ_HZ \
  -of_objects [ipx::get_bus_interfaces hostClk -of_objects [ipx::current_core]]]
ipx::add_bus_parameter FREQ_HZ [ipx::get_bus_interfaces dspClk -of_objects [ipx::current_core]]
set_property value $DSP_FREQ [ipx::get_bus_parameters FREQ_HZ \
  -of_objects [ipx::get_bus_interfaces dspClk -of_objects [ipx::current_core]]]

# bus<->clock associations
ipx::associate_bus_interfaces -busif S_AXIS -clock hostClk [ipx::current_core]
ipx::associate_bus_interfaces -busif S_AXIS -clock dspClk -remove [ipx::current_core]
for {set i 0} {$i < 16} {incr i} {
  ipx::associate_bus_interfaces -busif DAC${i}_AXIS -clock dspClk [ipx::current_core]
  ipx::associate_bus_interfaces -busif DAC${i}_AXIS -clock hostClk -remove [ipx::current_core]
  ipx::associate_bus_interfaces -busif ADC${i}_AXIS -clock dspClk [ipx::current_core]
  ipx::associate_bus_interfaces -busif ADC${i}_AXIS -clock hostClk -remove [ipx::current_core]
}

# QICK variant: genClk (the gens' DAC fabric clock) carries every QICKDAC{d}_AXIS gen sample stream; the
# gens' AXI-Lite registers and envelope streams (QICKGEN{c}_{GATE,RO}_{S_AXI,S0_AXIS}) are on hostClk.
if {$QICK} {
  ipx::add_bus_parameter FREQ_HZ [ipx::get_bus_interfaces genClk -of_objects [ipx::current_core]]
  set_property value $GEN_FREQ [ipx::get_bus_parameters FREQ_HZ \
    -of_objects [ipx::get_bus_interfaces genClk -of_objects [ipx::current_core]]]
  foreach _b [ipx::get_bus_interfaces QICKDAC*_AXIS -of_objects [ipx::current_core]] {
    set _n [get_property NAME $_b]
    ipx::associate_bus_interfaces -busif $_n -clock genClk [ipx::current_core]
    ipx::associate_bus_interfaces -busif $_n -clock dspClk  -remove [ipx::current_core]
    ipx::associate_bus_interfaces -busif $_n -clock hostClk -remove [ipx::current_core]
  }
  foreach _b [ipx::get_bus_interfaces QICKGEN* -of_objects [ipx::current_core]] {
    set _n [get_property NAME $_b]
    ipx::associate_bus_interfaces -busif $_n -clock hostClk [ipx::current_core]
    ipx::associate_bus_interfaces -busif $_n -clock dspClk -remove [ipx::current_core]
    ipx::associate_bus_interfaces -busif $_n -clock genClk -remove [ipx::current_core]
  }
  ipx::add_bus_parameter POLARITY [ipx::get_bus_interfaces genRst -of_objects [ipx::current_core]]
  set_property value ACTIVE_HIGH [ipx::get_bus_parameters POLARITY \
    -of_objects [ipx::get_bus_interfaces genRst -of_objects [ipx::current_core]]]
}

# reset polarities
ipx::add_bus_parameter POLARITY [ipx::get_bus_interfaces hostRst -of_objects [ipx::current_core]]
set_property value ACTIVE_HIGH [ipx::get_bus_parameters POLARITY \
  -of_objects [ipx::get_bus_interfaces hostRst -of_objects [ipx::current_core]]]
ipx::add_bus_parameter POLARITY [ipx::get_bus_interfaces dspRst -of_objects [ipx::current_core]]
set_property value ACTIVE_HIGH [ipx::get_bus_parameters POLARITY \
  -of_objects [ipx::get_bus_interfaces dspRst -of_objects [ipx::current_core]]]

# QICK: skipped — with the QICK VHDL sources in the IP it re-parses a VHDL file as the top (IP_Flow 19-262);
# the ports were just imported by package_project, so there is nothing to merge.
if {!$QICK} { ipx::merge_project_changes ports [ipx::current_core] }
ipx::create_xgui_files [ipx::current_core]
ipx::update_checksums [ipx::current_core]
ipx::check_integrity [ipx::current_core]
ipx::save_core [ipx::current_core]
set_property ip_repo_paths $IP_REPO [current_project]
update_ip_catalog

# ClockInterface is a plain BD module reference (instantiated as `clkifc`), not part of the user IP —
# add it now, after packaging, so it does not get swept into the IP archive.
add_files $SOURCE_PATH/ClockInterface.v
update_compile_order -fileset sources_1
