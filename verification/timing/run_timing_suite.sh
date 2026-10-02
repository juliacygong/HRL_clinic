#!/usr/bin/env bash
# Run the QICK timing suite on the Verilator harness and analyze every run.
#
# Usage: run_timing_suite.sh [test[:delay,delay,...] ...]
#   default: T1..T10 at PRE_RUN_DELAY_NS=0, plus T7 (= T2 program) at 0,13,37,71
#
# Each run gets its own folder verification/timing/runs/<test>/d<delay>/ with the
# program artifacts copied in (inputs are never modified), all ev_*.csv logs,
# the cwd-relative tproc_ctrl.csv / tproc_ro_ctrl.csv, console.log, and the
# timing_report.csv / timing_summary.txt from timing_analyze.py.
#
# Requires the harness binary built with the timing monitors:
#   make -C emulator/testbench verilate VERILATOR_ROOT=~/projects/qick/emulator/submodules/verilator
set -euo pipefail

TIMING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$TIMING_DIR/../.." && pwd)"
TB_DIR="$REPO/emulator/testbench"
ART_DIR="$REPO/emulator/artifacts/timing"
RUNS_DIR="$TIMING_DIR/runs"
BIN="$TB_DIR/obj_dir/VQICKEmu_harness"

DEFAULT=(T1:0 T2:0 T3a:0 T3b:0 T3c:0 T4:0 T5:0 T6:0 T7:0,13,37,71 T8:0 T9a:0 T9b:0 T10:0)
SPECS=("${@:-${DEFAULT[@]}}")

[[ -x "$BIN" ]] || { echo "missing $BIN (build the harness first)"; exit 1; }

# T7 is the T2 program swept over start delay.
program_for() { [[ "$1" == "T7" ]] && echo "T2" || echo "$1"; }

test_run_ns_for() {
    python3 -c "import json,sys; v=json.load(open(sys.argv[1])).get('test_run_ns'); print(v or '')" \
        "$ART_DIR/$1/manifest.json"
}

run_dirs=()
for spec in "${SPECS[@]}"; do
    test="${spec%%:*}"
    delays="${spec#*:}"; [[ "$delays" == "$spec" ]] && delays=0
    prog="$(program_for "$test")"
    src="$ART_DIR/$prog"
    [[ -f "$src/pmem.mem" ]] || { echo "missing artifacts for $prog in $src"; exit 1; }
    trn="$(test_run_ns_for "$prog")"

    for d in ${delays//,/ }; do
        out="$RUNS_DIR/$test/d$d"
        rm -rf "$out"; mkdir -p "$out"
        cp "$src"/*.mem "$src"/axi_replay.* "$src"/manifest.json "$src"/prog.txt "$out"/
        args=(+EMU_DIR="$out" +PRE_RUN_DELAY_NS="$d")
        [[ -n "$trn" ]] && args+=(+TEST_RUN_NS="$trn")

        start=$(date +%s)
        # Run from the testbench dir: fir_coe.txt and tproc_*ctrl.csv are cwd-relative.
        if ! (cd "$TB_DIR" && "$BIN" "${args[@]}" > "$out/console.log" 2>&1); then
            echo "$test d$d: SIMULATION FAILED (see $out/console.log)"; exit 1
        fi
        cp "$TB_DIR/tproc_ctrl.csv" "$TB_DIR/tproc_ro_ctrl.csv" "$out"/
        # A failed integrity check is a result, not a runner error: record and continue.
        if python3 "$TIMING_DIR/timing_analyze.py" "$out" > "$out/analyze.log" 2>&1; then
            verdict="integrity PASS"
        elif grep -q "FAIL" "$out/timing_summary.txt" 2>/dev/null; then
            verdict="integrity FAIL (see timing_summary.txt)"
        else
            echo "$test d$d: ANALYSIS ERROR (see $out/analyze.log)"; exit 1
        fi
        echo "$test d$d: done in $(( $(date +%s) - start )) s, $verdict"
        run_dirs+=("$out")
    done
done

echo
echo "=== SUITE OVERVIEW ==="
(cd "$TIMING_DIR" && python3 timing_analyze.py --brief "${run_dirs[@]}")

if compgen -G "$RUNS_DIR/T7/d*" > /dev/null; then
    echo
    echo "=== T7 CLOCK-PHASE SWEEP ==="
    (cd "$TIMING_DIR" && python3 timing_analyze.py --sweep "$RUNS_DIR"/T7/d*)
fi
