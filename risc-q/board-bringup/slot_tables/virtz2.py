"""RISC-Q build of exactly the qick_virtz.py program (trigger outside, open_loop in the body, delay_auto)."""
import os, sys
import qick.riscv_toolchain as tc
tc.FLAGS[0] = "-march=rv32im"; tc.FLAGS.append("-Wl,--build-id=none")
from qick.asm_riscv import RvAveragerProgram as AveragerProgramV2, CompiledOnly
from qick.asm_v2 import AsmV2
from qick.riscq_config import RvConfig
from qick.riscv import _socmap, DEFAULT_SOC
GEN, RO, N, F = 0, 0, 40, 100.0
class VirtZ2(AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_gen(ch=GEN, nqz=1); self.declare_readout(ch=RO, length=cfg['ro_len'])
        self.add_gauss(ch=GEN, name="ramp", sigma=0.002, length=0.012, even_length=True)
        self.add_pulse(ch=GEN, name="ft", ro_ch=RO, style="flat_top", envelope="ramp", freq=F, length=0.012, phase=0, gain=1.0)
        sub = AsmV2()
        for wname in self.list_pulse_waveforms("ft"):
            sub.read_wmem(name=wname); sub.inc_reg(dst='w_phase', src=self.deg2reg(90, gen_ch=GEN)); sub.write_wmem(name=wname)
        self.add_subroutine("virt_z", sub)
        self.add_readoutconfig(ch=RO, name="ro", freq=F, gen_ch=GEN); self.send_readoutconfig(ch=RO, name="ro", t=0)
    def _body(self, cfg):
        self.trigger(ros=[RO], t=0)
        self.open_loop(N, "l")
        self.pulse(ch=GEN, name="ft", t=0); self.call("virt_z"); self.delay_auto(0, ros=False)
        self.close_loop()
c = RvConfig(_socmap(DEFAULT_SOC)); c.equs['RQ_GATE_PULSE_NUM'] = 32
os.environ["QICK_RV_OUT"] = sys.argv[1]
try: VirtZ2(c, reps=1, final_delay=0.0, initial_delay=0.01, cfg={"ro_len": 1.6}).acquire(None)
except CompiledOnly as e: print(e)
