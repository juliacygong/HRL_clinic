#!/usr/bin/env python3
"""Generate the QICK timing-characterization programs T1..T10 as QICKEmu artifacts.

Run with the QICKEmu venv (needs numpy + qick):
    ~/projects/HRL_clinic/.venv/bin/python gen_timing_programs.py [T1 T2 ...]

For each test this writes emulator/artifacts/timing/<test>/:
    pmem.mem, wmem.mem, dmem.mem, sgmem_ch*.mem   program + tables
    axi_replay.jsonl, axi_replay.txt              recorded AXI writes (ends with PROC_START)
    prog.txt                                      assembled program listing
    manifest.json                                 intended pulses (t, length, gain, channel)

Export only: this does NOT run Verilator. It records the same AXI sequence as
the HRL fork's QickEmu acquire path (~/projects/qick qick_lib/qick/qick_asm.py,
_run_emu_acquire): _reset_soc_state -> config_all(load_mem=False) -> config_bufs
-> start_src -> start_tproc -> prepare -> export_vivado_files. Programs are
compiled with the local HRL_clinic qick_lib (0.2.422).

Every pulse gets a unique gain so it can be fingerprinted at every event layer.
All pulses are style='const' so the output is non-zero from the first sample.
"""

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "qick_lib"), str(REPO / "emulator" / "software")]

from qick_emu import QickEmu                      # noqa: E402
from qick.asm_v2 import AveragerProgramV2         # noqa: E402

CFG_PATH = REPO / "emulator" / "config" / "qick_emu_config.json"
OUT_ROOT = REPO / "emulator" / "artifacts" / "timing"
FREQ_MHZ = 100.0


def P(t, length=0.1, ch=0, gain=None):
    """One const pulse: start t [us] relative to the reference time, length [us]."""
    return {"t": t, "length": length, "ch": ch, "gain": gain}


def two(delta):
    return [P(0.5), P(0.5 + delta)]


# Each test: pulses in issue order, plus optional ops ('wait' before a pulse).
TESTS = {
    "T1": {"desc": "one pulse", "pulses": [P(0.5)]},
    "T2": {"desc": "two pulses, idle gap 0.5 us", "pulses": two(0.5)},
    "T3a": {"desc": "two pulses, gap 0.3 us", "pulses": two(0.3)},
    "T3b": {"desc": "two pulses, gap 0.5 us (same as T2)", "pulses": two(0.5)},
    "T3c": {"desc": "two pulses, gap 0.7 us", "pulses": two(0.7)},
    "T4": {"desc": "back-to-back: pulse 2 due at pulse 1's end",
           "pulses": [P(0.5), P(0.6)]},
    "T5": {"desc": "overlap: pulse 2 due before pulse 1 ends",
           "pulses": [P(0.5), P(0.55)]},
    "T6": {"desc": "later-time pulse written first",
           "pulses": [P(1.0), P(0.5)]},
    "T8": {"desc": "late command: core waits until 1.0 us, then issues a pulse due at 0.8 us",
           "pulses": [P(0.5), P(0.8)], "wait_before": {1: 1.0}},
    "T9a": {"desc": "acceptance stall: 300 pulses due 10 us + k*0.05 us (fills 256-entry dispatcher FIFO, no SG backpressure)",
            "pulses": [P(10.0 + 0.05 * k, length=0.02) for k in range(300)], "test_run_ns": 30000},
    "T9b": {"desc": "downstream backpressure: 300 pulses all due at 0.5 us, 0.02 us long",
            "pulses": [P(0.5, length=0.02) for _ in range(300)], "test_run_ns": 12000},
    "T10": {"desc": "same due on SG0 and SG1",
            "pulses": [P(0.5, ch=0), P(0.5, ch=1)]},
    "T11": {"desc": "shared-CDC coupling: SG0 backed up (40 overlapping pulses), SG1 gets 2 distinct pulses",
            "pulses": [P(0.5, length=0.1, ch=0) for _ in range(40)] + [P(0.6, ch=1), P(1.0, ch=1)],
            "test_run_ns": 12000},
}
# T7 = T2 run at several +PRE_RUN_DELAY_NS values by the suite runner (no new program).


class TimingProgram(AveragerProgramV2):
    def _initialize(self, cfg):
        for ch in sorted({p["ch"] for p in cfg["pulses"]}):
            self.declare_gen(ch=ch, nqz=1)
        for i, p in enumerate(cfg["pulses"]):
            self.add_pulse(ch=p["ch"], name=f"p{i}", style="const", freq=FREQ_MHZ,
                           phase=0, gain=p["gain"], length=p["length"])

    def _body(self, cfg):
        waits = cfg.get("wait_before", {})
        for i, p in enumerate(cfg["pulses"]):
            if i in waits:
                self.wait(waits[i])
            self.pulse(ch=p["ch"], name=f"p{i}", t=p["t"])


def assign_gains(pulses):
    """Unique gain per pulse: 0.1, 0.2, ... (or k/1000 for long lists)."""
    step = 0.1 if len(pulses) <= 9 else 0.001
    for k, p in enumerate(pulses):
        p["gain"] = round((k + 1) * step, 6)
    return pulses


def generate(name, spec, soc):
    out = OUT_ROOT / name
    pulses = assign_gains([dict(p) for p in spec["pulses"]])
    cfg = {"pulses": pulses, "wait_before": spec.get("wait_before", {})}
    prog = TimingProgram(soc.soccfg, reps=1, final_delay=1.0, cfg=cfg)

    # Same recording sequence as the emulator acquire path, without the simulation.
    soc._reset_soc_state(memdir=out)
    prog.config_all(soc, load_envelopes=True, load_mem=False)
    prog.config_bufs(soc, enable_avg=True, enable_buf=True)
    soc.start_src("internal")
    soc.start_tproc()
    soc.prepare(prog, soc=soc, memdir=out)
    soc.export_vivado_files(memdir=out)

    (out / "prog.txt").write_text(str(prog))
    f_time = soc.soccfg["tprocs"][0]["f_time"]
    manifest = {
        "test": name, "desc": spec["desc"], "freq_mhz": FREQ_MHZ,
        "f_time_mhz": f_time, "test_run_ns": spec.get("test_run_ns"),
        "wait_before": {str(k): v for k, v in cfg["wait_before"].items()},
        "pulses": [dict(p, t_ticks=round(p["t"] * f_time)) for p in pulses],
        "qick_lib": str(REPO / "qick_lib"),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return out


def main(argv):
    names = argv or list(TESTS)
    unknown = [n for n in names if n not in TESTS]
    if unknown:
        raise SystemExit(f"unknown test(s): {unknown}; choose from {list(TESTS)}")
    stray = pathlib.Path.cwd() / "tb_mem"          # QickEmu() creates ./tb_mem by default
    existed = stray.exists()
    soc = QickEmu(str(CFG_PATH))
    if not existed and stray.is_dir() and not any(stray.iterdir()):
        stray.rmdir()
    for name in names:
        out = generate(name, TESTS[name], soc)
        replay = (out / "axi_replay.txt").read_text().strip().splitlines()
        print(f"{name:<4} -> {out.relative_to(REPO)}  ({len(replay)} replay lines, last: {replay[-1]})")


if __name__ == "__main__":
    main(sys.argv[1:])
