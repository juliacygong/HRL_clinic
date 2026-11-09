#!/bin/bash
# Board run of the slot-table build: PulseUpdateProgram before/after (1 us initial delay) and the two-gen stress
# program. Cabling as the two-loop run: DAC 3_228 (gate gen) -> ADC 2_226 = robs(1); DAC 1_228 (readout gen) ->
# ADC 0_226 = robs(0).   BUILD=<build dir> BOARD_PW=... ./run_s32.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BB=/home/galencar/HRL_clinic/risc-q/board-bringup
BOARD="${BOARD_HOST:-xilinx@192.168.2.99}"
REMOTE=riscq-fast
BUILD="${BUILD:?set BUILD to the build dir}"
REPEAT="${REPEAT:-20}"
DATA="$HERE/data/riscq_board"
mkdir -p "$DATA"

WNS="$(awk '/^ +WNS\(ns\)/ { getline; getline; print $1; exit }' "$BUILD/timing_impl.rpt")"
echo "== bitstream $BUILD: WNS $WNS ns"

: "${BOARD_PW:?set BOARD_PW}"
ASK="$(mktemp)"; trap 'rm -f "$ASK"' EXIT
printf '#!/bin/sh\nprintf "%%s\\n" "$BOARD_PW"\n' > "$ASK"; chmod 700 "$ASK"
export SSH_ASKPASS="$ASK" SSH_ASKPASS_REQUIRE=force DISPLAY="${DISPLAY:-:0}"
OPTS=(-o PreferredAuthentications=password -o PubkeyAuthentication=no -o ConnectTimeout=10)
ENVS='source /etc/profile.d/pynq_venv.sh; source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/boardname.sh'
rootrun() { printf '%s\n' "$BOARD_PW" | ssh -T "${OPTS[@]}" "$BOARD" "cd $REMOTE && sudo -S -p '' bash -c '$ENVS; $1'"; }

echo "== deploying to $BOARD:$REMOTE"
ssh "${OPTS[@]}" "$BOARD" "mkdir -p $REMOTE/results && rm -f $REMOTE/results/*"
scp -q "${OPTS[@]}" -r "$HERE/programs" "$BB/bringup.py" "$BB/LMK04828_500.0.txt" "$BOARD:$REMOTE/"
scp -q "${OPTS[@]}" "$BUILD/PulseTableSoc.bit" "$BOARD:$REMOTE/PulseTableSoc.bit"
scp -q "${OPTS[@]}" "$BUILD/bd/riscq_bd/hw_handoff/riscq_bd.hwh" "$BOARD:$REMOTE/PulseTableSoc.hwh"

COMMON="--lmk LMK04828_500.0.txt --no-mts --dac-nyquist 1 --qick-status --repeat $REPEAT"
first=1
run() { # <name> <dir> <class> [extra bringup args]
  local name=$1 dir=$2 cls=$3; shift 3
  local clk=""; [ $first = 1 ] || clk="--skip-clocks --no-download"; first=0
  echo "== $name"
  rootrun "python3 bringup.py $COMMON $clk --elf programs/$dir/$cls.elf $* \
    --capture results/${name}_adc0.csv --capture2 results/${name}_adc2.csv" | grep -E "status|DONE \(|wrote|Error|Traceback" | grep -v "^.*run [0-9]*: pulse" | tail -4 || true
}
run old_pu old_pu PulseUpdateProgram --env gate=programs/old_pu/PulseUpdateProgram_gen0.env
run new_pu new_pu PulseUpdateProgram --env gate=programs/new_pu/PulseUpdateProgram_gen0.env
run stress stress StressProgram --env gate=programs/stress/StressProgram_gen0.env
run rate rate Rate
run sweep sweep Sweep
run virtz virtz VirtZ --env gate=programs/virtz/VirtZ_gen0.env
scp -q "${OPTS[@]}" "$BOARD:$REMOTE/results/*.csv" "$DATA/"
echo "== data in $DATA"
