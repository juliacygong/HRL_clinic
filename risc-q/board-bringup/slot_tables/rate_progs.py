"""Issue-rate test programs: pulses scheduled faster than the CPU can issue them, so each one is pushed late and
plays as soon as it is written; the spacing of the output pulses is then the CPU's issue interval.

    rate_progs.py <outdir>

  same    100 x one 6 ns const pulse (same slot every time), scheduled back to back
  cycle   100 x 6 ns const pulses cycling through 8 slots (different freq / gain each)
  sweep   a 100-step loop: one 6 ns pulse per iteration with a gain sweep (QickSweep1D), so every iteration
          rewrites the pulse (read_wmem, step, write through to the slot) as sweeps do
  *_old   the same programs with the previous code generation (slot tables hidden)
"""
import os
import sys
from pathlib import Path

import qick.riscv_toolchain as tc
tc.FLAGS[0] = "-march=rv32im"
tc.FLAGS.append("-Wl,--build-id=none")

from qick.asm_riscv import RvAveragerProgram as AveragerProgramV2, CompiledOnly
from qick.asm_v2 import QickSweep1D
from qick.riscq_config import RvConfig
from qick.riscv import _socmap, DEFAULT_SOC

out = Path(sys.argv[1])
N, LEN = 100, 0.006          # 100 pulses of 6 ns (3 dsp cycles, the compiler minimum)


class Same(AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_gen(ch=0, nqz=1)
        self.add_pulse(ch=0, name="p", style="const", freq=500, length=LEN, phase=0, gain=1.0)

    def _body(self, cfg):
        for i in range(N):
            self.pulse(ch=0, name="p", t=round(i * LEN, 6))


class Cycle(AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_gen(ch=0, nqz=1)
        for k in range(8):
            self.add_pulse(ch=0, name=f"p{k}", style="const", freq=100 + 50 * k, length=LEN, phase=0,
                           gain=(k + 1) / 8)

    def _body(self, cfg):
        for i in range(N):
            self.pulse(ch=0, name=f"p{i % 8}", t=round(i * LEN, 6))


class Sweep(AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_gen(ch=0, nqz=1)
        self.add_loop("l", N)
        self.add_pulse(ch=0, name="p", style="const", freq=500, length=LEN, phase=0,
                       gain=QickSweep1D("l", 0.1, 1.0))

    def _body(self, cfg):
        self.pulse(ch=0, name="p", t=0)


def make_cfg(hide_slots):
    cfg = RvConfig(_socmap(DEFAULT_SOC))
    if hide_slots:
        for k in ("RQ_SLOT_CONF", "RQ_SLOT_FREQ"):
            cfg.equs.pop(k, None)
    return cfg


for cls, name, kw in ((Same, "same", {}), (Cycle, "cycle", {}), (Sweep, "sweep", {})):
    for hide, suffix in ((False, ""), (True, "_old")):
        # final_delay 0: the sweep's iterations follow each other with no gap, so every pulse is late too
        prog = cls(make_cfg(hide), reps=1, final_delay=0.0, initial_delay=0.01, cfg={}, **kw)
        os.environ["QICK_RV_OUT"] = str(out / (name + suffix))
        try:
            prog.acquire(prog.soccfg)
        except CompiledOnly as e:
            print(e)
