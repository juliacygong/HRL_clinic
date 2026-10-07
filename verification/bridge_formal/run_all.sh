#!/usr/bin/env bash
# Run WaveWordBridge formal tasks in ONE sby run, so sby keeps a shared status database.
# Results: bridge_<task>/ per task; sby's overall summary: sby bridge.sby --taskstatus
#
#   ./run_all.sh              all tasks in bridge.sby
#   ./run_all.sh p1 cov       only these tasks
#   JOBS=4 ./run_all.sh       parallel jobs (default: number of CPUs)
#   ./run_all.sh --summary    only print sby's summary of the last runs
#
# Needs OSS CAD Suite: source ~/tools/oss-cad-suite/environment
set -u
cd "$(dirname "$0")"
command -v sby >/dev/null || { echo "sby not found: source ~/tools/oss-cad-suite/environment"; exit 1; }

if [ "${1:-}" != "--summary" ]; then
   sby -f -j "${JOBS:-$(nproc)}" bridge.sby "$@" > run_all.log 2>&1
   tail -n 1 run_all.log
fi
echo "--- sby --taskstatus (from sby's status database) ---"
sby bridge.sby --taskstatus
