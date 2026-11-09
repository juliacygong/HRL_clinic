"""RISC-Q counterpart of qick_rate.py: 40 back-to-back 3-cycle const pulses, gain alternating 1.0 / 0.4, started
late (initial_delay 0.01 us), gen 0 -> DAC 3_228 -> ADC 2_226 (robs(1)); the train length gives the issue rate.
    board_rate.py <outdir>"""
import os, sys
from pathlib import Path
import qick.riscv_toolchain as tc
tc.FLAGS[0] = "-march=rv32im"; tc.FLAGS.append("-Wl,--build-id=none")
from qick.asm_riscv import RvAveragerProgram as AveragerProgramV2, CompiledOnly
from qick.riscq_config import RvConfig
from qick.riscv import _socmap, DEFAULT_SOC
N, L, F = 40, 0.006, 100.0
class RateProgram(AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_gen(ch=0, nqz=1)
        self.declare_readout(ch=0, length=cfg['ro_len'])
        self.add_pulse(ch=0, name="a", ro_ch=0, style="const", freq=F, length=L, phase=0, gain=1.0)
        self.add_pulse(ch=0, name="b", ro_ch=0, style="const", freq=F, length=L, phase=0, gain=0.4)
        self.add_readoutconfig(ch=0, name="ro", freq=F, gen_ch=0)
        self.send_readoutconfig(ch=0, name="ro", t=0)
    def _body(self, cfg):
        self.trigger(ros=[0], t=0)
        for i in range(N):
            self.pulse(ch=0, name="a" if i % 2 == 0 else "b", t=round(i * L, 6))
os.environ["QICK_RV_OUT"] = sys.argv[1]
try: RateProgram(RvConfig(_socmap(DEFAULT_SOC)), reps=1, final_delay=0.0, initial_delay=0.01, cfg={"ro_len": 2.0}).acquire(None)
except CompiledOnly as e: print(e)
