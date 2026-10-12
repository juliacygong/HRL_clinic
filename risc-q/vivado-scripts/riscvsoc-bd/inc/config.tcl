# ---- riscvsoc-bd configuration (script-scope; override any of these from the environment) -----------

set PART          xczu49dr-ffvf1760-2-e
set TOP_MODULE    PulseTableSoc
set BD_NAME       riscq_bd
set DSP_FREQ      500000000
set HOST_FREQ     100000000

# Run stages. Synthesis is on by default; implementation / bitstream are long, so opt-in.
set RUN_SYNTH     1
set RUN_IMPL      0
set RUN_BITSTREAM 0

if {[info exists ::env(RISCQ_DEVICE)]}        { set PART          $::env(RISCQ_DEVICE) }
if {[info exists ::env(RISCQ_TOP)]}           { set TOP_MODULE    $::env(RISCQ_TOP) }
if {[info exists ::env(RISCQ_DSP_FREQ)]}      { set DSP_FREQ      $::env(RISCQ_DSP_FREQ) }
if {[info exists ::env(RISCQ_HOST_FREQ)]}     { set HOST_FREQ     $::env(RISCQ_HOST_FREQ) }
if {[info exists ::env(RISCQ_RUN_SYNTH)]}     { set RUN_SYNTH     $::env(RISCQ_RUN_SYNTH) }
if {[info exists ::env(RISCQ_RUN_IMPL)]}      { set RUN_IMPL      $::env(RISCQ_RUN_IMPL) }
if {[info exists ::env(RISCQ_RUN_BITSTREAM)]} { set RUN_BITSTREAM $::env(RISCQ_RUN_BITSTREAM) }

# Bitstream implies implementation.
if {$RUN_BITSTREAM} { set RUN_IMPL 1 }

# QICK gen_v6 variant (RTL generated with `qick`, see build-riscvsoc-bd.sh): adds the QICK IP sources, runs
# the DAC tiles at QICK's 9.58464 GS/s (599.04 MHz fabric clock = genClk, 245.76 MHz reference), and
# wires each QICKDAC{d}_AXIS gen stream to RFDC DAC d. QICK_FW is the repo's QICK firmware tree.
set QICK          0
set GEN_FREQ      599040000
set QICK_FW       [file normalize $SCRIPT_DIR/../../../firmware]
if {[info exists ::env(RISCQ_QICK)]}          { set QICK          $::env(RISCQ_QICK) }
if {[info exists ::env(RISCQ_QICK_FW)]}       { set QICK_FW       $::env(RISCQ_QICK_FW) }
if {$QICK && ![file exists $QICK_FW/ip/axis_signal_gen_v6]} {
  error "RISCQ_QICK=1 but no QICK IP under $QICK_FW/ip — set RISCQ_QICK_FW to the QICK firmware dir"
}

# Paths. One folder per project under the repo-root build/ (git-ignored), so several designs build in
# parallel without clobbering each other. The RTL (PulseTableSoc.v + ClockInterface.v + register-file
# .bin) is emitted into that same folder by build-riscvsoc-bd.sh's GenPulseTableSocJson, so SOURCE_PATH
# is the build dir itself. RISCQ_PROJ_NAME names the folder; RISCQ_BUILD_DIR overrides the full path.
set PROJ_NAME   riscvsoc-bd
if {[info exists ::env(RISCQ_PROJ_NAME)]}     { set PROJ_NAME   $::env(RISCQ_PROJ_NAME) }
set BUILD_DIR   [file normalize $SCRIPT_DIR/../../build/$PROJ_NAME]
if {[info exists ::env(RISCQ_BUILD_DIR)]}     { set BUILD_DIR   $::env(RISCQ_BUILD_DIR) }
set SOURCE_PATH $BUILD_DIR
if {[info exists ::env(RISCQ_RTL_DIR)]}       { set SOURCE_PATH $::env(RISCQ_RTL_DIR) }
set IP_REPO     $BUILD_DIR/ip
# Vivado project name (the .xpr / .runs / .gen prefix) — sanitise the folder name to the underscore-safe
# subset create_project accepts.
set PRJ         [regsub -all {[^A-Za-z0-9_]} $PROJ_NAME _]

# ---- optional XCOM board-link IP ------------------------------------------------------------------
# OFF by default: a build without it is identical to the pre-XCOM flow, so enabling XCOM can never be
# the reason a known-good bitstream stops working. See docs/soc/XcomBringup.md.
#   RISCQ_WITH_XCOM=1      instantiate QICK's xcom beside the SoC, AXI-Lite on the SmartConnect
#   RISCQ_XCOM_LOOPBACK=1  (default) tie the link's tx back to its rx IN FABRIC — no pins, no cable
#   RISCQ_XCOM_LOOPBACK=0  bring the link out to PMOD pins (constraints-xcom-zcu216.xdc)
#   RISCQ_XCOM_NCH         receive channels; 1 = point-to-point or loopback
# THIS BRANCH (comm-module-xcom) DEFAULTS XCOM ON. It is the paired test point to `comm-module`,
# which defaults it off: the two branches differ in this one value and nothing else, so the same
# build command on each isolates the link's effect on resources, timing and behaviour. Set
# RISCQ_WITH_XCOM=0 here to get the comm-module build without switching branches.
set WITH_XCOM     1
set XCOM_LOOPBACK 1
set XCOM_NCH      1
set XCOM_BASEADDR 0x90000000
set XCOM_IP_DIR   [file normalize $SCRIPT_DIR/../../../firmware/ip/xcom]

if {[info exists ::env(RISCQ_WITH_XCOM)]}     { set WITH_XCOM     $::env(RISCQ_WITH_XCOM) }
if {[info exists ::env(RISCQ_XCOM_LOOPBACK)]} { set XCOM_LOOPBACK $::env(RISCQ_XCOM_LOOPBACK) }
if {[info exists ::env(RISCQ_XCOM_NCH)]}      { set XCOM_NCH      $::env(RISCQ_XCOM_NCH) }
if {[info exists ::env(RISCQ_XCOM_BASEADDR)]} { set XCOM_BASEADDR $::env(RISCQ_XCOM_BASEADDR) }

if {$WITH_XCOM && ![file exists $XCOM_IP_DIR/component.xml]} {
  error "RISCQ_WITH_XCOM=1 but no packaged xcom IP at $XCOM_IP_DIR (expected component.xml)"
}

puts "\[config\] top=$TOP_MODULE part=$PART dsp=${DSP_FREQ}Hz host=${HOST_FREQ}Hz  synth=$RUN_SYNTH impl=$RUN_IMPL bit=$RUN_BITSTREAM"
if {$QICK} { puts "\[config\] QICK gen_v6 variant: gen=${GEN_FREQ}Hz  qick_fw=$QICK_FW" }
puts "\[config\] rtl=$SOURCE_PATH  build=$BUILD_DIR"
if {$WITH_XCOM} {
  puts "\[config\] xcom=ON nch=$XCOM_NCH loopback=$XCOM_LOOPBACK base=$XCOM_BASEADDR ip=$XCOM_IP_DIR"
} else {
  puts "\[config\] xcom=off (set RISCQ_WITH_XCOM=1 to include the board link)"
}

if {![file exists $SOURCE_PATH/$TOP_MODULE.v]} {
  error "missing $SOURCE_PATH/$TOP_MODULE.v — run ./build-riscvsoc-bd.sh (it generates the RTL first)"
}
file mkdir $BUILD_DIR
