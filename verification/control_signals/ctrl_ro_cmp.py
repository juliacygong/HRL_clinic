#!/usr/bin/env python3

import argparse
import csv
import re
import sys


# RISC-Q posted-RF addresses for the demod/readout channel.
RO_FIRE       = 0x20000
RO_FREQ       = 0x20004
RO_PHASE      = 0x20010
RO_AMP        = 0x20014
RO_ENV        = 0x20018
RO_DURATION   = 0x2001C
RO_START_TIME = 0x24100


RFCMD_RE = re.compile(
    r"\[RFCMD\]\s+"
    r"seq=(\d+)\s+"
    r"time=(\d+)\s+"
    r"addr=0x([0-9a-fA-F]+)\s+"
    r"data=0x([0-9a-fA-F]+)"
)


def parse_hex(value):
    return int(value.strip(), 16)


def read_qick_row(path, seq):
    """Read one accepted tProcV2 readout command from CSV."""
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    matches = [r for r in rows if int(r["seq"]) == seq]

    if not matches:
        raise RuntimeError(
            f"QICK readout seq={seq} not found in {path}"
        )

    r = matches[0]

    return {
        "seq": int(r["seq"]),
        "raw168": r["raw168"],
        "conf": parse_hex(r["conf"]),
        "nsamp": parse_hex(r["nsamp"]),
        "phrst": int(r["phrst"]),
        "mode": int(r["mode"]),
        "outsel": int(r["outsel"]),
        "phase": parse_hex(r["phase"]),
        "freq": parse_hex(r["freq"]),
    }


def read_riscq_events(path):
    """
    Reconstruct RISC-Q demod/readout events.

    Register writes update state. A write to RO_FIRE snapshots the
    current state into one readout event.
    """
    state = {
        "start_time": None,
        "freq": None,
        "phase": None,
        "amp": None,
        "env": None,
        "duration": None,
    }

    events = []

    with open(path) as f:
        for line in f:
            m = RFCMD_RE.search(line)

            if not m:
                continue

            seq = int(m.group(1))
            time = int(m.group(2))
            addr = int(m.group(3), 16)
            data = int(m.group(4), 16)

            if addr == RO_START_TIME:
                state["start_time"] = data & 0xFFFFFFFF

            elif addr == RO_FREQ:
                state["freq"] = (data >> 16) & 0xFFFF

            elif addr == RO_PHASE:
                state["phase"] = (data >> 16) & 0xFFFF

            elif addr == RO_AMP:
                state["amp"] = (data >> 16) & 0xFFFF

            elif addr == RO_ENV:
                state["env"] = (data >> 16) & 0xFFFF

            elif addr == RO_DURATION:
                state["duration"] = (data >> 16) & 0xFFFF

            elif addr == RO_FIRE:
                event = dict(state)
                event["fire_seq"] = seq
                event["fire_time"] = time
                event["fire_data"] = data
                events.append(event)

    return events


def compare(qick, riscq):
    failures = []

    print()
    print("READOUT CONTROL COMPARISON")
    print("=" * 60)
    print(f"QICK   : seq={qick['seq']}")
    print(f"RISC-Q : fire seq={riscq['fire_seq']}")
    print()

    #
    # Frequency
    #
    # QICK uses a 32-bit phase/frequency word.
    # RISC-Q uses a 16-bit field.
    #
    qick_freq_16 = (qick["freq"] >> 16) & 0xFFFF
    freq_remainder = qick["freq"] & 0xFFFF

    print("frequency")
    print(f"  QICK raw32       = 0x{qick['freq']:08x}")
    print(f"  QICK -> RISC-Q   = 0x{qick_freq_16:04x}")
    print(f"  RISC-Q           = 0x{riscq['freq']:04x}")

    if riscq["freq"] == qick_freq_16:
        if freq_remainder == 0:
            print("  PASS: exactly representable after 32->16 normalization")
        else:
            print(
                "  PASS: matches upper-16-bit quantized representation "
                f"(discarded low16=0x{freq_remainder:04x})"
            )
    else:
        print("  FAIL: normalized frequency does not match")
        failures.append("frequency")

    print()

    #
    # Phase
    #
    qick_phase_16 = (qick["phase"] >> 16) & 0xFFFF
    phase_remainder = qick["phase"] & 0xFFFF

    print("phase")
    print(f"  QICK raw32       = 0x{qick['phase']:08x}")
    print(f"  QICK -> RISC-Q   = 0x{qick_phase_16:04x}")
    print(f"  RISC-Q           = 0x{riscq['phase']:04x}")

    if riscq["phase"] == qick_phase_16:
        if phase_remainder == 0:
            print("  PASS: exactly representable after 32->16 normalization")
        else:
            print(
                "  PASS: matches upper-16-bit quantized representation "
                f"(discarded low16=0x{phase_remainder:04x})"
            )
    else:
        print("  FAIL: normalized phase does not match")
        failures.append("phase")

    print()

    #
    # Window length
    #
    print("readout window count")
    print(f"  QICK nsamp       = {qick['nsamp']}")
    print(f"  RISC-Q duration  = {riscq['duration']}")

    if qick["nsamp"] == riscq["duration"]:
        print(
            "  MATCH: numeric window count agrees "
            "(physical-time normalization still pending)"
        )
    else:
        print(
            "  MISMATCH: numeric counts differ "
            "(not treated as semantic failure until timing units are normalized)"
        )

    print()

    #
    # QICK-only control semantics
    #
    print("architecture-specific control")
    print(f"  QICK mode        = {qick['mode']}   -> no direct RISC-Q register")
    print(f"  QICK phrst       = {qick['phrst']}   -> no direct RISC-Q register")
    print(f"  QICK outsel      = {qick['outsel']}   -> no direct RISC-Q register")

    print()

    #
    # RISC-Q-specific implementation fields
    #
    print("RISC-Q demod-specific fields")
    print(f"  startTime        = {riscq['start_time']}")
    print(f"  amp              = 0x{riscq['amp']:04x}")
    print(f"  env              = 0x{riscq['env']:04x}")
    print(f"  fire data        = 0x{riscq['fire_data']:08x}")

    print()
    print("=" * 60)

    if failures:
        print("RESULT: FAIL mapped control fields: " + ", ".join(failures))
        return False

    print("RESULT: PASS mapped readout control fields")
    print(
        "NOTE: mode/phrst/outsel and physical window timing require "
        "behavioral verification."
    )
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Compare tProcV2/QICK and RISC-Q readout control commands."
    )

    parser.add_argument(
        "--qick",
        required=True,
        help="tProcV2 readout-control CSV",
    )

    parser.add_argument(
        "--riscq-log",
        required=True,
        help="RISC-Q simulation log containing [RFCMD] records",
    )

    parser.add_argument(
        "--qick-seq",
        type=int,
        default=0,
        help="QICK CSV sequence number to compare (default: 0)",
    )

    parser.add_argument(
        "--riscq-event",
        type=int,
        default=-1,
        help="RISC-Q readout fire event index (default: -1, last event)",
    )

    args = parser.parse_args()

    qick = read_qick_row(args.qick, args.qick_seq)
    events = read_riscq_events(args.riscq_log)

    if not events:
        print(
            "ERROR: no RISC-Q demod/readout FIRE events found "
            "(expected addr=0x20000)",
            file=sys.stderr,
        )
        return 2

    try:
        riscq = events[args.riscq_event]
    except IndexError:
        print(
            f"ERROR: RISC-Q event {args.riscq_event} does not exist; "
            f"found {len(events)} event(s)",
            file=sys.stderr,
        )
        return 2

    return 0 if compare(qick, riscq) else 1


if __name__ == "__main__":
    sys.exit(main())