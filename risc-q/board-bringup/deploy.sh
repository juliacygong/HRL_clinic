#!/bin/bash
# Copy the QICK riscvsoc-bd build + the standalone bring-up to the ZCU216 and (optionally) run it.
#
#   ./deploy.sh                       # copy PulseTableSoc.{bit,hwh}, bringup.py, LMK04828_500.0.txt
#   ./deploy.sh run [bringup args]    # ... and run bringup.py on the board (sudo asks for the password)
#
# Env: BOARD_HOST (default xilinx@192.168.2.99 — the board's PYNQ static address on the direct link),
#      BUILD (default <repo>/build/riscvsoc-bd-qick), BIT (default $BUILD/PulseTableSoc.bit), REMOTE_DIR (default riscq-bringup, under ~xilinx).
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
BOARD_HOST="${BOARD_HOST:-xilinx@192.168.2.99}"
BUILD="${BUILD:-$REPO/build/riscvsoc-bd-qick}"
REMOTE_DIR="${REMOTE_DIR:-riscq-bringup}"

BIT="${BIT:-$BUILD/PulseTableSoc.bit}"
HWH="$BUILD/bd/riscq_bd/hw_handoff/riscq_bd.hwh"
for f in "$BIT" "$HWH"; do
  [ -f "$f" ] || { echo "[deploy] missing $f — run the bitstream build first" >&2; exit 1; }
done
[ "$HWH" -nt "$BIT" ] && echo "[deploy] warning: $HWH is newer than $BIT (stale bitstream?)" >&2

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp "$BIT" "$STAGE/PulseTableSoc.bit"
cp "$HWH" "$STAGE/PulseTableSoc.hwh"            # PYNQ 2.7 wants <name>.hwh next to <name>.bit
cp "$HERE/bringup.py" "$HERE/qick_baseline.py" "$HERE/LMK04828_500.0.txt" "$STAGE/"
cp -r "$HERE/programs" "$STAGE/"

echo "[deploy] copying to $BOARD_HOST:$REMOTE_DIR/"
ssh "$BOARD_HOST" "mkdir -p $REMOTE_DIR"
scp -qr "$STAGE"/* "$BOARD_HOST:$REMOTE_DIR/"

if [ "${1:-}" = "run" ]; then
  shift
  echo "[deploy] running bringup.py $* on the board"
  ssh -t "$BOARD_HOST" "cd $REMOTE_DIR && sudo bash -c 'source /etc/profile.d/pynq_venv.sh; source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/boardname.sh; python3 bringup.py $*'"
fi
