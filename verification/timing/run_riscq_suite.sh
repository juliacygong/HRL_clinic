#!/usr/bin/env bash
# Run the native RISC-Q probe suite (programs from gen_riscq_programs.py) and analyze every run.
#
# Usage: run_riscq_suite.sh [probe ...]        default: every probe in riscq_programs/
#
# Mode per probe: P9_* = powerup (cores not held during load), P8_* = driver flow with an abort
# 300 cycles after release and a rerun without reloading, everything else = driver flow (run.py).
# Log window = latest planned pulse end + 1500 cycles (at least 3000).
# Output: verification/timing/riscq_runs/<probe>/ with ev_*.csv, manifest.json, console.log,
# riscq_timing_summary_ch0.txt, riscq_probe_report.csv.
set -euo pipefail

TIMING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$TIMING_DIR/../.." && pwd)"
PROG_DIR="$TIMING_DIR/riscq_programs"
RUNS_DIR="$TIMING_DIR/riscq_runs"
MILL="$HOME/projects/RISC-Q/mill"

PROBES=("$@")
[[ ${#PROBES[@]} -gt 0 ]] || mapfile -t PROBES < <(ls "$PROG_DIR")

window_for() {
    python3 -c "
import json,sys
m=json.load(open(sys.argv[1]))
end=max(m['base_offset_batches']+p['start_offset']+p['dur'] for p in m['pulses'])
end=max(end, max([int(v) for v in m['waits_batches'].values()] or [0])+m['base_offset_batches'])
print(max(3000, end+1500))" "$PROG_DIR/$1/manifest.json"
}

"$MILL" shutdown > /dev/null 2>&1 || true
for probe in "${PROBES[@]}"; do
    out="$RUNS_DIR/$probe"
    rm -rf "$out"; mkdir -p "$out"
    cp "$PROG_DIR/$probe/manifest.json" "$PROG_DIR/$probe/prog.S" "$out"/
    mode=driver; abort=""
    [[ "$probe" == P9_* ]] && mode=powerup
    [[ "$probe" == P8_* ]] && abort="300,100"
    cycles="$(window_for "$probe")"
    [[ -n "$abort" ]] && cycles=$((cycles + 600))

    start=$(date +%s)
    if ! (cd "$REPO/risc-q" && env RISCQ_ELF="$PROG_DIR/$probe/prog.elf" RISCQ_OUT="$out" RISCQ_MODE="$mode" \
            RISCQ_CYCLES="$cycles" ${abort:+RISCQ_ABORT=$abort} \
            "$MILL" runMain riscq.soc.sim.TimingSocCpuSim > "$out/console.log" 2>&1); then
        echo "$probe: SIMULATION FAILED (see $out/console.log)"; exit 1
    fi
    python3 "$TIMING_DIR/riscq_timing_analyze.py" "$out" > "$out/analyze.log" 2>&1 \
        || { echo "$probe: ANALYSIS ERROR (see $out/analyze.log)"; exit 1; }
    n_att=$(sed -n '/^ATTENTION/,$p' "$out/riscq_timing_summary_ch0.txt" | grep -c '^  - ' || true)
    echo "$probe ($mode${abort:+, abort $abort}, $cycles cyc): done in $(( $(date +%s) - start )) s, attention items: $n_att"
done
