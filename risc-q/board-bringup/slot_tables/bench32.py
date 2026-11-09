"""Benchmarks for the 32-slot build (RQ_GATE_PULSE_NUM = 32): every pulse starts late (initial_delay 0.01 us,
final_delay 0), so output spacing = issue cost.
    bench32.py <outdir>"""
import os, sys
from pathlib import Path
import qick.riscv_toolchain as tc
tc.FLAGS[0] = "-march=rv32im"; tc.FLAGS.append("-Wl,--build-id=none")
from qick.asm_riscv import RvAveragerProgram as AveragerProgramV2, CompiledOnly
from qick.asm_v2 import AsmV2, QickSweep1D
from qick.riscq_config import RvConfig
from qick.riscv import _socmap, DEFAULT_SOC
out = Path(sys.argv[1]); N, L = 100, 0.006

def cfg32():
    c = RvConfig(_socmap(DEFAULT_SOC)); c.equs['RQ_GATE_PULSE_NUM'] = 32; return c

class Same(AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_gen(ch=0, nqz=1); self.add_pulse(ch=0, name="p", style="const", freq=500, length=L, phase=0, gain=1.0)
    def _body(self, cfg):
        for i in range(N): self.pulse(ch=0, name="p", t=round(i * L, 6))

class Many40(AveragerProgramV2):
    """40 different waveforms on one gen (more than its 32 slots), cycled"""
    def _initialize(self, cfg):
        self.declare_gen(ch=0, nqz=1)
        for k in range(40):
            self.add_pulse(ch=0, name=f"p{k}", style="const", freq=100 + 5 * k, length=L, phase=0, gain=0.5 + k / 100)
    def _body(self, cfg):
        for i in range(N): self.pulse(ch=0, name=f"p{i % 40}", t=round(i * L, 6))

class Sweep(AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_gen(ch=0, nqz=1); self.add_loop("l", N)
        self.add_pulse(ch=0, name="p", style="const", freq=500, length=L, phase=0, gain=QickSweep1D("l", 0.1, 1.0))
    def _body(self, cfg):
        self.pulse(ch=0, name="p", t=0)

class VirtZ(AveragerProgramV2):
    """every iteration: a short flat-top (3 waveforms, 36 ns), then virt_z (+90 deg on each of its waveforms)"""
    def _initialize(self, cfg):
        self.declare_gen(ch=0, nqz=1); self.add_loop("l", N)
        self.add_gauss(ch=0, name="ramp", sigma=0.002, length=0.012, even_length=True)
        self.add_pulse(ch=0, name="ft", style="flat_top", envelope="ramp", freq=500, length=0.012, phase=0, gain=1.0)
        sub = AsmV2()
        for wname in self.list_pulse_waveforms("ft"):
            sub.read_wmem(name=wname); sub.inc_reg(dst='w_phase', src=self.deg2reg(90, gen_ch=0)); sub.write_wmem(name=wname)
        self.add_subroutine("virt_z", sub)
    def _body(self, cfg):
        self.pulse(ch=0, name="ft", t=0); self.call("virt_z")

for cls in (Same, Many40, Sweep, VirtZ):
    os.environ["QICK_RV_OUT"] = str(out / cls.__name__)
    try: cls(cfg32(), reps=1, final_delay=0.0, initial_delay=0.01, cfg={}).acquire(None)
    except CompiledOnly as e: print(e)
