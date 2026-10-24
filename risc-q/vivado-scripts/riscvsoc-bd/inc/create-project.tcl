# ---- Create the Vivado project and add the top RTL (+ ROM init) ------------------------------------
# Only the top (plus, for the QICK variant, the QICK IP sources it instantiates) is added here; ClockInterface.v is added *after* the top is packaged as IP (so it stays a
# plain BD module reference and is not swept into the user IP). The .bin is the register-file ROM init
# that PulseTableSoc.v `$readmemb`s — it must accompany the sources into synthesis.

create_project $PRJ $BUILD_DIR -part $PART -force

add_files $SOURCE_PATH/$TOP_MODULE.v
# Typed as Memory File so ipx::package_project imports them into the user IP (an Unknown-type file is
# "ignored by IP packager", and the IP's OOC synth run then cannot find the $readmemb data).
foreach b [glob -nocomplain $SOURCE_PATH/*.bin] { add_files $b; set_property FILE_TYPE {Memory File} [get_files $b] }

# QICK variant: the sources behind PulseTableSoc's QICK BlackBoxes (sg_translator, axis_cdcsync_v1,
# axis_signal_gen_v6), taken from each IP's component.xml file set minus testbenches. They are packaged into
# the PulseTableSoc IP with the top. The gen's DDS Compiler sub-core is an .xci saved by Vivado 2023.1
# (QICK's version), so it is imported into the project and upgraded to this Vivado.
if {$QICK} {
  set _ip $QICK_FW/ip
  add_files [list \
    $_ip/qick_sg_translator/src/sg_translator.v \
    $_ip/axis_cdcsync_v1/src/axis_cdcsync_v1.sv \
    $_ip/axis_cdcsync_v1/src/cdcsync.sv \
    $QICK_FW/hdl/fifo_dc_axi_xpm.sv \
    $_ip/axis_signal_gen_v6/src/axis_signal_gen_v6.v \
    $_ip/axis_signal_gen_v6/src/signal_gen_top.v \
    $_ip/axis_signal_gen_v6/src/signal_gen.v \
    $_ip/axis_signal_gen_v6/src/ctrl_sg_v6.sv \
    $_ip/axis_signal_gen_v6/src/latency_reg.v \
    $_ip/axis_signal_gen_v6/src/axi_slv_sg_v6.vhd \
    $_ip/axis_signal_gen_v6/src/data_writer.vhd \
    $_ip/axis_signal_gen_v6/src/synchronizer_n.vhd \
    $QICK_FW/hdl/bram_dp_xpm.sv \
    $QICK_FW/hdl/fifo_xpm.sv]
  import_ip $_ip/axis_signal_gen_v6/src/dds_compiler_0/dds_compiler_0.xci
  upgrade_ip -quiet [get_ips dds_compiler_0]
  # the gen's own CDC false paths (synchronizers, s_axi regs -> s0_axis_aclk), scoped to each gen instance
  add_files -fileset constrs_1 $_ip/axis_signal_gen_v6/src/signal_gen_v6.xdc
  set_property SCOPED_TO_REF axis_signal_gen_v6 [get_files signal_gen_v6.xdc]
}

set_property top $TOP_MODULE [current_fileset]
update_compile_order -fileset sources_1
