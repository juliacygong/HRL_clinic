#!/bin/bash
# Reruns the two-generator demo with both designs on axis_signal_gen_v6, then writes the full figure and timing table.
# Before running: cable from DAC 1_228 (tile 0, block 1) to ADC 0_226 on JHC7.
# The default bitstream is riscvsoc-bd-qick-2gen-explore, which meets timing (WNS +0.061 ns). BUILD=<dir> picks another.
#
#   ./run_v6.sh                 # everything; asks for the board password once
#   ./run_v6.sh --old-bit       # no new bitstream: reuses the board's lb bitstream, whose second gen plays flat-tops wrong
#   ./run_v6.sh --plumbing-test # keeps going without a signal and writes to data/test, to test the script without the cable
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOARD="${BOARD_HOST:-xilinx@192.168.2.99}"
REMOTE=riscq-2gen-v6
BUILD="${BUILD:-$HERE/../../build/riscvsoc-bd-qick-2gen-explore}"
OLD_BIT=0; TEST=0
for a in "$@"; do
  case "$a" in
    --old-bit) OLD_BIT=1 ;;
    --plumbing-test) TEST=1 ;;
    *) echo "unknown option $a" >&2; exit 2 ;;
  esac
done
DATA="$HERE/data"; [ "$TEST" = 1 ] && DATA="$HERE/data/test"
PY="$HOME/.local/opt/qickrv-venv/bin/python"
mkdir -p "$DATA"

if [ "$OLD_BIT" = 0 ]; then
  [ -f "$BUILD/PulseTableSoc.bit" ] || { echo "No bitstream at $BUILD. Check the build, or use --old-bit." >&2; exit 1; }
  WNS="$(awk '/^ +WNS\(ns\)/ { getline; getline; print $1; exit }' "$BUILD/timing_impl.rpt" 2>/dev/null || true)"
  echo "== bitstream $BUILD: WNS ${WNS:-unknown} ns"
  awk -v w="${WNS:--1}" 'BEGIN { exit !(w < 0) }' && echo "warning: this bitstream misses timing, so check any odd result against a passing build"
fi

if [ -z "${BOARD_PW:-}" ]; then read -rsp "Board password: " BOARD_PW; echo; fi
export BOARD_PW
ASK="$(mktemp)"; trap 'rm -f "$ASK"' EXIT
printf '#!/bin/sh\nprintf "%%s\\n" "$BOARD_PW"\n' > "$ASK"; chmod 700 "$ASK"
export SSH_ASKPASS="$ASK" SSH_ASKPASS_REQUIRE=force DISPLAY="${DISPLAY:-:0}"
OPTS=(-o PreferredAuthentications=password -o PubkeyAuthentication=no -o ConnectTimeout=10)
ENVS='source /etc/profile.d/pynq_venv.sh; source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/boardname.sh'
rootrun() { printf '%s\n' "$BOARD_PW" | ssh -T "${OPTS[@]}" "$BOARD" "cd $REMOTE && sudo -S -p '' bash -c '$ENVS; $1'"; }

echo "== deploying to $BOARD:$REMOTE"
ssh "${OPTS[@]}" "$BOARD" "mkdir -p $REMOTE/results"
scp -q "${OPTS[@]}" -r "$HERE/programs" "$HERE/qick_v6.py" "$HERE/../bringup.py" "$HERE/../LMK04828_500.0.txt" "$BOARD:$REMOTE/"
if [ "$OLD_BIT" = 1 ]; then
  ssh "${OPTS[@]}" "$BOARD" "cp riscq-bringup-lb/PulseTableSoc.bit riscq-bringup-lb/PulseTableSoc.hwh $REMOTE/"
else
  scp -q "${OPTS[@]}" "$BUILD/PulseTableSoc.bit" "$BOARD:$REMOTE/PulseTableSoc.bit"
  scp -q "${OPTS[@]}" "$BUILD/bd/riscq_bd/hw_handoff/riscq_bd.hwh" "$BOARD:$REMOTE/PulseTableSoc.hwh"
fi

check() { # <prefix-or-csv> <minimum level>: stop if the capture is only noise, which means the cable is on the wrong DAC
  "$PY" - "$1" "$2" "$TEST" <<'P'
import glob, sys
import numpy as np
p, least, test = sys.argv[1], float(sys.argv[2]), sys.argv[3] == "1"
if p.endswith(".csv"):
    x = np.loadtxt([l for l in open(p) if l[:1].isdigit()], delimiter=",", usecols=3)[:4000]
    level = np.abs(x - x.mean()).max()
else:
    m = [np.abs(d[:, 1] + 1j * d[:, 2]) for d in (np.loadtxt(f, delimiter=",", skiprows=1) for f in glob.glob(p + "_[0-9]*.csv"))]
    level = np.mean(m, axis=0).max()
print(f"   signal level {level:.1f} (need at least {least:.0f})")
if level < least and not test:
    sys.exit("No signal: check the cable is on DAC 1_228 and JHC7.")
P
}

qick() { # <run name> <gen for train 0> <gen for train 1> <readout MHz>
  echo "== QICK tProc v2: $1"
  rootrun "python3 qick_v6.py results/$1 $2 $3 $4 1" | grep -E 'TPROC|Error|Traceback' || true
  scp -q "${OPTS[@]}" "$BOARD:$REMOTE/results/$1_*" "$DATA/"
  check "$DATA/$1" 40
}
riscq() { # <run name> <program>
  echo "== RISC-Q: $1"
  rootrun "python3 bringup.py --no-mts --dac-nyquist 1 --env gate=programs/$2/MultiPulseProgram_gen0.env --env ro=programs/$2/MultiPulseProgram_gen1.env --elf programs/$2/MultiPulseProgram.elf --repeat 10 --capture results/$1.csv" | tail -2
  scp -q "${OPTS[@]}" "$BOARD:$REMOTE/results/$1.csv" "$DATA/"
  check "$DATA/$1.csv" 300
}

qick qick_train0 1 0 100
qick qick_train1 0 1 200
riscq riscq_train0 train0
riscq riscq_train1 train1
[ "$TEST" = 1 ] && { echo "plumbing test done: no figure, because the cable is not on DAC 1_228"; exit 0; }

"$PY" "$HERE/plot_v6.py" "$DATA/riscq_train0.csv" "$DATA/riscq_train1.csv" "$DATA/qick_train0" "$DATA/qick_train1" \
  "$HERE/../results/twogen_board_v6_riscq_vs_tprocv2.png" "$DATA/summary.txt"
echo "== figure: $(cd "$HERE/../results" && pwd)/twogen_board_v6_riscq_vs_tprocv2.png"
