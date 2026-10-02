#!/usr/bin/env python3
"""Generate native RISC-Q probe programs (P1..P9) from the QICK timing test manifests.

QICK is the reference: every program is a literal translation of a QICK test in
emulator/artifacts/timing/<test>/manifest.json (same pulses, same issue order, same
relative times), converted into RISC-Q units. It is deliberately a naive, tProc-style
translation (each pulse carries its own startTime + freq + table entry + fire, like a
tProc wave-port command) so conversion weak spots show up instead of being designed away.

Usage:  gen_riscq_programs.py [probe ...]      (stdlib only; needs riscv64-unknown-elf-gcc)
Output: verification/timing/riscq_programs/<probe>/{prog.S, prog.elf, manifest.json}

Unit mapping (QICK -> RISC-Q):
  1 RISC-Q batch == 1 QICK sg_clk cycle (both 16 DAC samples); QICK us -> batches at 599.04 MHz.
  QICK program reference (TIME #430 inc_ref = 1.0 us)  -> base = time_read + 599 batches.
  QICK pulse t [us]  -> startTime = base + round(t * 599.04).
  QICK nsamp          -> dur (batches).  QICK gain -> amp = round(gain * 32767) (unique fingerprint).
RISC-Q register map (risc-q/src/riscq/soc/rf/PulseParamBuffer.scala, sw/pulse_sched.S):
  time @0xbff8; gate channel (ch0) CPU window 0x10000, readout-drive channel (ch1) 0x20000;
  fire @+0x0 (data = table index), freq @+0x4, table[i] @+(i+1)*0x10 {phase, amp, env, dur},
  startTime @+0x4100; 16-bit fields in data[31:16].
"""

import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
QICK_ART = REPO / "emulator" / "artifacts" / "timing"
OUT_ROOT = pathlib.Path(__file__).resolve().parent / "riscq_programs"

BATCH_MHZ = 599.04
REF_US = 1.0                      # QICK programs start with TIME #430 inc_ref (1.0 us)
CH_BASE = {0: 0x10000, 1: 0x20000}
TABLE_SLOTS = {0: 8, 1: 1}        # gatePulseNum = 8; readout-drive table depth 1
FREQ16 = 0x0708                   # carrier freq field (timing-neutral); P4b varies it per pulse
ENV_BASE = 10

# probe -> QICK test it translates + options
PROBES = {
    "P1_T1":  {"qick": "T1",  "why": "time reference: single pulse"},
    "P1_T2":  {"qick": "T2",  "why": "time reference: two pulses, 0.5 us gap"},
    "P1_T3a": {"qick": "T3a", "why": "time reference: 0.3 us gap"},
    "P1_T3c": {"qick": "T3c", "why": "time reference: 0.7 us gap"},
    "P2_T5":  {"qick": "T5",  "why": "overlap: QICK chains, RISC-Q dur counter reloads"},
    "P3_T4":  {"qick": "T4",  "why": "back-to-back with explicit startTime per pulse (literal tProc translation)"},
    "P3_auto": {"qick": "T4", "why": "back-to-back relying on startTime auto-advance (one startTime write)",
                "auto_advance": True},
    "P4_T6":  {"qick": "T6",  "why": "issue order != due order"},
    "P4_freq": {"qick": "T6", "why": "issue order != due order, distinct freq per pulse (freq/pulse pairing)",
                "distinct_freq": True},
    "P5_T8":  {"qick": "T8",  "why": "late command: wait until 1.0 us, then pulse due 0.8 us"},
    "P6_n4":  {"qick": "T9a", "why": "capacity: 4 pending pulses (= queue depth)", "first_n": 4},
    "P6_n5":  {"qick": "T9a", "why": "capacity: 5 pending pulses (> queue depth)", "first_n": 5},
    "P6_n8":  {"qick": "T9a", "why": "capacity: 8 pending pulses", "first_n": 8},
    "P6_same5": {"qick": "T9b", "why": "capacity: 5 pulses, same due", "first_n": 5},
    "P7_T10": {"qick": "T10", "why": "cross-channel: equal due on ch0 (gate) and ch1 (readout drive)"},
    "P8_T2":  {"qick": "T2",  "why": "rerun after abort: pulses scheduled far ahead, reset re-asserted before they play",
               "extra_lead_us": 3.0},
    "P9_T1":  {"qick": "T1",  "why": "power-up window (run in powerup mode)"},
}


def batches(us):
    return round(us * BATCH_MHZ)


class Asm:
    def __init__(self):
        self.lines = ["  .section .text.init, \"ax\"", "  .globl _start", "_start:"]
        self.label_n = 0

    def emit(self, text, comment=""):
        self.lines.append(f"  {text:<28}" + (f"# {comment}" if comment else ""))

    def store(self, addr, value, comment):
        self.emit(f"li   t0, {addr:#x}")
        self.emit(f"li   t2, {value:#x}")
        self.emit("sw   t2, 0(t0)", comment)

    def store_time(self, addr, offset, comment):
        """mem[addr] = s0 + offset (s0 = program base time)."""
        self.emit(f"li   t0, {addr:#x}")
        self.emit(f"li   t2, {offset}")
        self.emit("add  t2, s0, t2")
        self.emit("sw   t2, 0(t0)", comment)

    def wait_until(self, offset):
        """spin until batch time >= s0 + offset (signed difference, wrap-safe)."""
        lbl = f"wait{self.label_n}"; self.label_n += 1
        self.emit(f"li   t3, {offset}")
        self.emit("add  t3, s0, t3")
        self.emit("li   t0, 0xbff8")
        self.lines.append(f"{lbl}:")
        self.emit("lw   a1, 0(t0)")
        self.emit("sub  t4, a1, t3")
        self.emit(f"bltz t4, {lbl}", f"wait until time >= base+{offset}")

    def text(self):
        return "\n".join(self.lines + ["1:", "  j    1b                    # park"]) + "\n"


def build(probe, spec):
    m = json.loads((QICK_ART / spec["qick"] / "manifest.json").read_text())
    pulses = m["pulses"][: spec.get("first_n", len(m["pulses"]))]
    waits = {int(k): v for k, v in m.get("wait_before", {}).items()}
    base_off = batches(REF_US + spec.get("extra_lead_us", 0.0))

    a = Asm()
    a.emit("li   t0, 0xbff8", "TimeMemMap batch time")
    a.emit("lw   a0, 0(t0)")
    a.emit(f"li   t1, {base_off}")
    a.emit("add  s0, a0, t1", f"s0 = base = now + {base_off} batches (QICK ref 1.0 us)")
    plan = []
    for k, p in enumerate(pulses):
        ch = p["ch"]
        cb = CH_BASE[ch]
        slot = k % TABLE_SLOTS[ch]
        t_off = batches(p["t"])
        dur = round(p["length"] * BATCH_MHZ)            # = QICK nsamp for these const pulses
        amp = round(p["gain"] * 32767)
        freq = (FREQ16 + 0x100 * k) & 0xFFFF if spec.get("distinct_freq") else FREQ16
        if k in waits:
            a.emit(f"# QICK wait({waits[k]} us)")
            a.wait_until(batches(waits[k]))
        a.lines.append(f"  # pulse {k}: QICK t={p['t']} us ch={ch} -> startTime base+{t_off}, dur {dur}, amp {amp}")
        if not spec.get("auto_advance") or k == 0:
            a.store_time(cb + 0x4100, t_off, "startTime")
        a.store(cb + 0x4, freq << 16, "freq")
        e = cb + (slot + 1) * 0x10
        a.store(e + 0x0, 0, "phase")
        a.store(e + 0x4, amp << 16, "amp (fingerprint)")
        a.store(e + 0x8, ENV_BASE << 16, "env base")
        a.store(e + 0xC, dur << 16, "dur")
        a.store(cb + 0x0, slot, f"fire table[{slot}]")
        plan.append({"k": k, "ch": ch, "slot": slot, "qick_t_us": p["t"], "start_offset": t_off,
                     "dur": dur, "amp": amp, "freq16": freq,
                     "explicit_start": not spec.get("auto_advance") or k == 0})

    out = OUT_ROOT / probe
    out.mkdir(parents=True, exist_ok=True)
    (out / "prog.S").write_text(f"# {probe}: {spec['why']}\n# generated from QICK {spec['qick']} "
                                f"({m['desc']}) by gen_riscq_programs.py\n" + a.text())
    subprocess.run(["riscv64-unknown-elf-gcc", "-march=rv32i", "-mabi=ilp32", "-nostdlib", "-static",
                    "-Wl,-Ttext=0x80000000", "-Wl,-e,_start", str(out / "prog.S"), "-o", str(out / "prog.elf")],
                   check=True)
    size = int(subprocess.run(["riscv64-unknown-elf-size", "-A", str(out / "prog.elf")], check=True,
                              capture_output=True, text=True).stdout.split(".text")[1].split()[0])
    manifest = {"probe": probe, "why": spec["why"], "qick_test": spec["qick"], "qick_desc": m["desc"],
                "base_offset_batches": base_off, "batch_mhz": BATCH_MHZ,
                "waits_batches": {str(k): batches(v) for k, v in waits.items()},
                "text_bytes": size, "pulses": plan}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return out, size, len(plan)


def main(argv):
    names = argv or list(PROBES)
    for n in names:
        out, size, npulse = build(n, PROBES[n])
        print(f"{n:<9} {npulse:>2} pulses  {size:>5} B .text  -> {out.relative_to(REPO)}")


if __name__ == "__main__":
    main(sys.argv[1:])
