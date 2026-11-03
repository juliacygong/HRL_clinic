#!/bin/bash
# One run, both generators: the two-generator demo with both gens cabled to their own ADC, on both designs.
#   program gen 0 (100 MHz): DAC 3_228 (JHC2 pair 2) -> ADC 2_226 (JHC7 pair 2)
#   program gen 1 (200 MHz): DAC 1_228 (JHC2 pair 1) -> ADC 0_226 (JHC7 pair 1)
# QICK plays gen 0 on its gen 3 and gen 1 on its gen 1 (both axis_signal_gen_v6). RISC-Q needs a build of
# software/configs/zcu216-qick-1q-2loop.json (gate gen on DAC 3, readout gen on DAC 1, ADC 10 captured into robs(1)).
#
#   ./run_2loop.sh              # asks for the board password once; BUILD=<dir> picks the bitstream
#
# QICK-clock build (software/configs/zcu216-qick-1q-2loop-qickclk.json: DACs 9584.64 MS/s, ADCs 2457.6 MS/s as
# 8 lanes on a 307.2 MHz dsp clock), with a program recompiled for those clocks in programs/<PROG>:
#   BUILD=../../build/riscvsoc-bd-qick-2loop-qickclk LMK=LMK04828_qickclk_307.2.txt \
#     RQ_ARGS="--adc-batch 8 --adc-fs 2.4576e9" PROG=train1_qickclk ./run_2loop.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOARD="${BOARD_HOST:-xilinx@192.168.2.99}"
REMOTE=riscq-2gen-v6
BUILD="${BUILD:-$HERE/../../build/riscvsoc-bd-qick-2loop}"
LMK="${LMK:-LMK04828_500.0.txt}"      # board-bringup/ clock file for the build (bringup.py --lmk)
RQ_ARGS="${RQ_ARGS:-}"                # extra bringup.py flags (QICK-clock build: --adc-batch 8 --adc-fs 2.4576e9)
PROG="${PROG:-train1}"                # programs/<PROG>: the compiled program for the build's clocks
DATA="$HERE/data_2loop"
PY="$HOME/.local/opt/qickrv-venv/bin/python"
mkdir -p "$DATA"

[ -f "$BUILD/PulseTableSoc.bit" ] || { echo "No bitstream at $BUILD." >&2; exit 1; }
WNS="$(awk '/^ +WNS\(ns\)/ { getline; getline; print $1; exit }' "$BUILD/timing_impl.rpt" 2>/dev/null || true)"
echo "== bitstream $BUILD: WNS ${WNS:-unknown} ns"
awk -v w="${WNS:--1}" 'BEGIN { exit !(w < 0) }' && echo "warning: this bitstream misses timing, so check any odd result against a passing build"

if [ -z "${BOARD_PW:-}" ]; then read -rsp "Board password: " BOARD_PW; echo; fi
export BOARD_PW
ASK="$(mktemp)"; trap 'rm -f "$ASK"' EXIT
printf '#!/bin/sh\nprintf "%%s\\n" "$BOARD_PW"\n' > "$ASK"; chmod 700 "$ASK"
export SSH_ASKPASS="$ASK" SSH_ASKPASS_REQUIRE=force DISPLAY="${DISPLAY:-:0}"
OPTS=(-o PreferredAuthentications=password -o PubkeyAuthentication=no -o ConnectTimeout=10)
ENVS='source /etc/profile.d/pynq_venv.sh; source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/boardname.sh'
rootrun() { printf '%s\n' "$BOARD_PW" | ssh -T "${OPTS[@]}" "$BOARD" "cd $REMOTE && sudo -S -p '' bash -c '$ENVS; $1'"; }

echo "== deploying to $BOARD:$REMOTE"
ssh "${OPTS[@]}" "$BOARD" "mkdir -p $REMOTE/results && rm -f $REMOTE/results/qick_2loop_* $REMOTE/results/riscq_2loop_*"
scp -q "${OPTS[@]}" -r "$HERE/programs" "$HERE/qick_v6_2loop.py" "$HERE/../bringup.py" "$HERE/../$LMK" "$BOARD:$REMOTE/"
scp -q "${OPTS[@]}" "$BUILD/PulseTableSoc.bit" "$BOARD:$REMOTE/PulseTableSoc.bit"
scp -q "${OPTS[@]}" "$BUILD/bd/riscq_bd/hw_handoff/riscq_bd.hwh" "$BOARD:$REMOTE/PulseTableSoc.hwh"

level() { # <csv> <minimum>: peak of a RISC-Q capture's first run
  "$PY" - "$1" "$2" <<'P'
import sys, numpy as np
x = np.loadtxt([l for l in open(sys.argv[1]) if l[:1].isdigit()], delimiter=",", usecols=3)[:4000]
v = np.abs(x - x.mean()).max(); print(f"   {sys.argv[1].rsplit('/', 1)[-1]}: signal level {v:.0f} (need at least {sys.argv[2]})")
sys.exit(0 if v >= float(sys.argv[2]) else "No signal on this cable: check its DAC pair, balun and JHC7 pair.")
P
}

echo "== QICK tProc v2: 80 runs, both gens; its one raw (MR) buffer alternates ADCs, so 40 raw captures per ADC, as RISC-Q"
rootrun "python3 qick_v6_2loop.py results/qick_2loop 40" | grep -E 'TPROC|run [0-9]+:|Error|Traceback' | sed -n '1p;2p;$p'
scp -q "${OPTS[@]}" "$BOARD:$REMOTE/results/qick_2loop_*" "$DATA/"

echo "== RISC-Q: 40 runs, both gens (program $PROG), ADC 0_226 -> robs(0), ADC 2_226 -> robs(1)"
rootrun "python3 bringup.py --lmk $LMK $RQ_ARGS --no-mts --dac-nyquist 1 --env gate=programs/$PROG/MultiPulseProgram_gen0.env --env ro=programs/$PROG/MultiPulseProgram_gen1.env --elf programs/$PROG/MultiPulseProgram.elf --repeat 40 --capture results/riscq_2loop_adc0.csv --capture2 results/riscq_2loop_adc2.csv" | tail -3
scp -q "${OPTS[@]}" "$BOARD:$REMOTE/results/riscq_2loop_adc*.csv" "$DATA/"
level "$DATA/riscq_2loop_adc0.csv" 300
level "$DATA/riscq_2loop_adc2.csv" 300
"$PY" "$HERE/plot_2loop.py" "$DATA" "$HERE/../results/twogen_board_2loop_overlay_riscq_vs_tprocv2.png" | tee "$DATA/summary.txt"
echo "== data in $DATA, figures in $(cd "$HERE/../results" && pwd)"
