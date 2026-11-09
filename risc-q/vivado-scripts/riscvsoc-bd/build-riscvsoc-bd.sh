#!/bin/bash
# ============================================================================================
# riscvsoc-bd — BLOCK-DESIGN implementation of the floorplan, to evaluate the gap vs the
# out-of-context bench in ../riscvsoc.
#
# Same SoC, same floorplan, same recipe — but built in a REAL device context: PulseTableSoc packaged as
# a user IP in a Vivado block design alongside the Zynq UltraScale+ PS, the RF Data Converter and an AXI
# SmartConnect, with real clocking (ClockInterface BUFGs from the board LVDS clocks) and the real
# host-released reset network. So the difference between this flow's WNS and the ~ −0.156 ns the OOC
# bench reports isolates the **block-design / real-device penalty** (PS+RFDC sharing the die, BUFG
# clocking, the IP synthesised out-of-context as a child run, SmartConnect routing).
#
# Self-contained: it generates the BD (vivado=true) RTL with GenPulseTableSocJson from a per-build
# SocParams JSON (the same file the python riscq.map / co-sim flows load), then runs the BD assembly in
# flow-bd.tcl + inc/{config,create-project,package-ip,bd-build,bd-finalize,run}.tcl, with the floorplan
# from pblocks-bd.tcl. RTL, the Vivado project, the reports and vivado.log all land in one folder under
# the repo-root build/ — <repo>/build/<PROJ> — so several designs can build in parallel.
#
# Prereq: a Vivado with the Zynq PS / RFDC / SmartConnect IP (the full ZCU216 BD flow). The RTL is the
# vivado=true form (host clock = hostClk, X_INTERFACE attrs) — distinct from the OOC bench's plain ports.
# The qubit count / DAC-ADC maps / interpolation all come from the JSON config; the tcl flow discovers the
# core count from the netlist, so a different config just needs a matching floorplan (pblocks-bd.tcl).
#
# By default this runs the full flow — synth + impl + write_bitstream + XSA export — so it drops both a
# PulseTableSoc.bit and a PulseTableSoc.xsa (the fixed hardware handoff for the Vitis / PetaLinux software
# flow, bitstream embedded) in the build dir. Set RISCQ_RUN_BITSTREAM=0 to stop after implementation.
#
# Usage:
#   ./build-riscvsoc-bd.sh                    # zcu216-14q config, full floorplan, synth+impl+bitstream+xsa
#   RISCQ_RUN_BITSTREAM=0 ./build-riscvsoc-bd.sh # stop after impl (no bitstream / xsa)
#   RISCQ_CONFIG=software/configs/sim-2q.json ./build-riscvsoc-bd.sh # a different SocParams JSON
#   RISCQ_SKIP_GEN=1   ./build-riscvsoc-bd.sh # reuse the RTL already in the build dir (skip mill)
#   RISCQ_PROJ_NAME=foo ./build-riscvsoc-bd.sh # build into <repo>/build/foo (parallel designs)
#   RISCQ_QICK=1 ./build-riscvsoc-bd.sh          # QICK gen_v6 variant (zcu216-qick-1q config, no floorplan)
#
# QICK variant (RISCQ_QICK=1): the RTL is generated with `qick` (PulseTableSoc.qickGen — each core's gate /
# readout drive = WaveWordBridge -> axis_cdcsync_v1 -> sg_translator -> axis_signal_gen_v6), the QICK IP
# sources come from <clinic>/firmware (RISCQ_QICK_FW), and the gens run on the RFDC's DAC fabric clock. By
# default that is 500 MHz (DACs at the native 8 GS/s, 500 MHz dac_clk), so a gen cycle is one dsp batch and
# nsamp = dur; RISCQ_GEN_FREQ=599040000 selects QICK's 9.58464 GS/s instead (the board's dac_clk must then
# be QICK's 245.76 MHz reference). The config must give every gen its own DAC (default
# software/configs/zcu216-qick-1q.json). The 14q floorplan does not apply, so it is off unless
# RISCQ_PBLOCK_TCL is set.
#
# QICK-clock build (software/configs/zcu216-qick-1q-2loop-qickclk.json): the config's dsp_freq_hz /
# adc_batch / gen_freq_hz keys put the converters at stock QICK tProc v2 rates — DACs 9584.64 MS/s (gens
# on 599.04 MHz clk_dac0), ADCs 2457.6 MS/s as 8 lanes on a 307.2 MHz dspClk (QICK's readout fabric
# clock), every RFDC PLL on QICK's 245.76 MHz reference. The board then needs
# board-bringup/LMK04828_qickclk_307.2.txt (bringup.py --lmk), see board-bringup/gen_lmk_qickclk.py.
#
# Env: RISCQ_VIVADO_BIN, RISCQ_CONFIG (default software/configs/zcu216-14q.json), RISCQ_SKIP_GEN,
#   RISCQ_RUN_BITSTREAM (default 1 — bitstream + xsa; set 0 for impl-only),
#   RISCQ_PROJ_NAME (default riscvsoc-bd), plus the floorplan knobs read by pblocks-bd.tcl:
#   RISCQ_{ROW,PERROW,CONFINE}, RISCQ_BD_BASE, and RISCQ_PLACE_DIRECTIVE (default ExtraNetDelay_high —
#   the placer directive). RISCQ_MREG_LOCK=1 freezes the carrierGen ComplexMul product DSPs against
#   phys_opt MREG-stripping (specs/dsp-fmax.md). See README.md.
# ============================================================================================
set -e
BD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # vivado-scripts/riscvsoc-bd
REPO_DIR="$(cd "$BD_DIR/../.." && pwd)"                  # agentic-rv-dev (repo root)
VIVADO_BIN="${RISCQ_VIVADO_BIN:-$(dirname "$(command -v vivado)")}"
QICK="${RISCQ_QICK:-0}"
if [ "$QICK" = "1" ]; then
  CONFIG="${RISCQ_CONFIG:-$REPO_DIR/software/configs/zcu216-qick-1q.json}"
  PROJ="${RISCQ_PROJ_NAME:-riscvsoc-bd-qick}"
else
  CONFIG="${RISCQ_CONFIG:-$REPO_DIR/software/configs/zcu216-14q.json}"
  PROJ="${RISCQ_PROJ_NAME:-riscvsoc-bd}"
fi
# Clock plan from the config (env wins): "dsp_freq_hz" -> RISCQ_DSP_FREQ (dspClk), "adc_batch" -> RISCQ_ADC_BATCH
# (ADC lanes per dsp cycle; ADC rate = adc_batch x dsp), "gen_freq_hz" -> RISCQ_GEN_FREQ (QICK gens). Every
# config before the QICK-clock one has dsp 500 MHz / 4 lanes / no gen key, i.e. the old defaults.
_cfg() { python3 -c 'import json,sys; v=json.load(open(sys.argv[1])).get(sys.argv[2]); print("" if v is None else int(v))' "$CONFIG" "$1"; }
_v="$(_cfg dsp_freq_hz)";  export RISCQ_DSP_FREQ="${RISCQ_DSP_FREQ:-${_v:-500000000}}"
_v="$(_cfg adc_batch)";    export RISCQ_ADC_BATCH="${RISCQ_ADC_BATCH:-${_v:-4}}"
_v="$(_cfg gen_freq_hz)";  [ -z "${RISCQ_GEN_FREQ:-}" ] && [ -n "$_v" ] && export RISCQ_GEN_FREQ="$_v"
if [ "$QICK" = "1" ]; then
  GEN_ARGS="vivado qick${RISCQ_GEN_FREQ:+ genFreq=$RISCQ_GEN_FREQ}"
else
  GEN_ARGS="vivado"
fi
BUILD="$REPO_DIR/build/$PROJ"
mkdir -p "$BUILD"

# 1) RTL — the BD (vivado=true) form — emitted INTO the project build dir from the SocParams JSON.
if [ "${RISCQ_SKIP_GEN:-0}" != "1" ]; then
  echo "[riscvsoc-bd] generating BD RTL (GenPulseTableSocJson $CONFIG, $GEN_ARGS) → $BUILD"
  ( cd "$REPO_DIR" && mill runMain riscq.soc.GenPulseTableSocJson "$CONFIG" "$BUILD" $GEN_ARGS )
else
  echo "[riscvsoc-bd] RISCQ_SKIP_GEN=1 — reusing RTL in $BUILD"
  [ -f "$BUILD/PulseTableSoc.v" ] || { echo "[riscvsoc-bd] no $BUILD/PulseTableSoc.v — run once without RISCQ_SKIP_GEN" >&2; exit 1; }
fi

# 2) Build via flow-bd.tcl, selecting the floorplan + IP retiming + place directive. RISCQ_PBLOCK
#    just enables the pre-place hook (any value); RISCQ_PBLOCK_TCL is the actual floorplan file.
export RISCQ_PROJ_NAME="$PROJ"
export RISCQ_BUILD_DIR="$BUILD"
export RISCQ_QICK="$QICK"
if [ "$QICK" != "1" ]; then
  export RISCQ_PBLOCK=1
  export RISCQ_PBLOCK_TCL="$BD_DIR/pblocks-bd.tcl"
elif [ -n "${RISCQ_PBLOCK_TCL:-}" ]; then
  export RISCQ_PBLOCK=1                       # QICK variant: only an explicitly given floorplan
fi
export RISCQ_IP_RETIMING=1
export RISCQ_PLACE_DIRECTIVE="${RISCQ_PLACE_DIRECTIVE:-ExtraNetDelay_high}"   # route stays AggressiveExplore (run.tcl)
export RISCQ_RUN_IMPL=1
export RISCQ_RUN_BITSTREAM="${RISCQ_RUN_BITSTREAM:-1}"   # bitstream + XSA (hardware handoff) by default; set 0 for impl-only

echo "[riscvsoc-bd] clocks: dsp=${RISCQ_DSP_FREQ} Hz, adc_batch=${RISCQ_ADC_BATCH}${RISCQ_GEN_FREQ:+, gen=${RISCQ_GEN_FREQ} Hz}"
echo "[riscvsoc-bd] building block design in $BUILD (floorplan, IP retiming, place=$RISCQ_PLACE_DIRECTIVE / route=AggressiveExplore, bitstream+xsa=$RISCQ_RUN_BITSTREAM) …"
"$VIVADO_BIN/vivado" -nojournal -mode batch -log "$BUILD/vivado.log" -source "$BD_DIR/flow-bd.tcl"

echo "[riscvsoc-bd] ===================================================================="
echo "[riscvsoc-bd] done. reports in $BUILD"
if [ -f "$BUILD/timing_impl.rpt" ]; then
  echo "[riscvsoc-bd] impl WNS/TNS (timing_impl.rpt):"
  grep -m2 -E "WNS|TNS|Worst Negative|Total Negative" "$BUILD/timing_impl.rpt" | sed 's/^/[riscvsoc-bd]   /' || true
else
  echo "[riscvsoc-bd] (no timing_impl.rpt — see $BUILD/vivado.log)"
fi
[ -f "$BUILD/PulseTableSoc.bit" ] && echo "[riscvsoc-bd] bitstream: $BUILD/PulseTableSoc.bit"
[ -f "$BUILD/PulseTableSoc.xsa" ] && echo "[riscvsoc-bd] hardware platform: $BUILD/PulseTableSoc.xsa"
echo "[riscvsoc-bd] compare against ../riscvsoc (OOC, ~ −0.156 ns). util_impl.rpt holds the per-pblock view."
