#!/usr/bin/env python3

import argparse
import csv
import re
import sys


RFCMD_RE = re.compile(
    r"\[RFCMD\]\s+seq=(\d+)\s+"
    r"time=(\d+)\s+"
    r"addr=0x([0-9a-fA-F]+)\s+"
    r"data=0x([0-9a-fA-F]+)"
)


def read_qick_pulse(path, seq):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    matches = [r for r in rows if int(r["seq"]) == seq]

    if not matches:
        raise ValueError(f"QICK seq {seq} not found")

    row = matches[0]

    qick_freq = int(row["freq"], 16)
    qick_phase = int(row["phase"], 16)

    # Current RISC-Q uses 16-bit normalized frequency/phase.
    # For this first checker, require exact 32 -> 16 representation.
    if qick_freq & 0xFFFF:
        raise ValueError(
            f"QICK freq 0x{qick_freq:08x} is not exactly representable "
            "in current 16-bit RISC-Q format"
        )

    if qick_phase & 0xFFFF:
        raise ValueError(
            f"QICK phase 0x{qick_phase:08x} is not exactly representable "
            "in current 16-bit RISC-Q format"
        )

    return {
        "freq": qick_freq >> 16,
        "phase": qick_phase >> 16,
        "amp": int(row["gain"], 16) & 0xFFFF,
        "env": int(row["env"], 16) & 0xFFFF,
        "duration": int(row["len"], 16) & 0xFFFF,
    }


def read_riscq_pulses(path):
    state = {
        "start_time": None,
        "freq": None,
        "phase": None,
        "amp": None,
        "env": None,
        "duration": None,
    }

    pulses = []

    with open(path) as f:
        for line in f:
            m = RFCMD_RE.search(line)
            if not m:
                continue

            seq = int(m.group(1))
            sim_time = int(m.group(2))
            addr = int(m.group(3), 16)
            data = int(m.group(4), 16)

            if addr == 0x4100:
                state["start_time"] = data & 0xFFFFFFFF

            elif addr == 0x0004:
                state["freq"] = (data >> 16) & 0xFFFF

            elif addr == 0x0010:
                state["phase"] = (data >> 16) & 0xFFFF

            elif addr == 0x0014:
                state["amp"] = (data >> 16) & 0xFFFF

            elif addr == 0x0018:
                state["env"] = (data >> 16) & 0xFFFF

            elif addr == 0x001C:
                state["duration"] = (data >> 16) & 0xFFFF

            elif addr == 0x0000:
                pulse = dict(state)
                pulse["fire_seq"] = seq
                pulse["fire_sim_time"] = sim_time
                pulse["table_id"] = data & 0xFFFF
                pulses.append(pulse)

    return pulses


def compare(qick, riscq):
    fields = ["freq", "phase", "amp", "env", "duration"]

    print()
    print("Controller command comparison")
    print("-" * 68)
    print(f"{'field':<12} {'QICK':>14} {'RISC-Q':>14} {'result':>12}")
    print("-" * 68)

    all_pass = True

    for field in fields:
        q = qick[field]
        r = riscq[field]

        passed = q == r
        all_pass &= passed

        q_text = f"0x{q:04x}" if q is not None else "None"
        r_text = f"0x{r:04x}" if r is not None else "None"

        print(
            f"{field:<12} "
            f"{q_text:>14} "
            f"{r_text:>14} "
            f"{'PASS' if passed else 'FAIL':>12}"
        )

    print("-" * 68)

    if riscq.get("start_time") is not None:
        print(f"RISC-Q startTime : {riscq['start_time']}")

    print(f"RISC-Q table ID  : {riscq.get('table_id')}")
    print()

    if all_pass:
        print("PASS: controller pulse parameters are equivalent.")
        return 0
    else:
        print("FAIL: controller pulse parameters differ.")
        return 1


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--qick",
        required=True,
        help="QICK tproc_ctrl.csv",
    )

    parser.add_argument(
        "--riscq-log",
        required=True,
        help="RISC-Q simulation console log",
    )

    parser.add_argument(
        "--qick-seq",
        type=int,
        default=0,
        help="QICK command sequence number, default 0",
    )

    parser.add_argument(
        "--riscq-event",
        type=int,
        default=0,
        help="RISC-Q fired pulse index, default 0",
    )

    args = parser.parse_args()

    qick = read_qick_pulse(args.qick, args.qick_seq)
    pulses = read_riscq_pulses(args.riscq_log)

    if not pulses:
        raise ValueError("No RISC-Q FIRE events found")

    if args.riscq_event >= len(pulses):
        raise ValueError(
            f"Requested RISC-Q event {args.riscq_event}, "
            f"but only {len(pulses)} pulse(s) were found"
        )

    riscq = pulses[args.riscq_event]

    sys.exit(compare(qick, riscq))


if __name__ == "__main__":
    main()