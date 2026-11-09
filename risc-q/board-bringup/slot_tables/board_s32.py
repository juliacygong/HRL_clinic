"""Board programs for the 32-slot build (all with a readout trigger at t = 0 so the capture window holds them).
    board_s32.py <outdir>
  rate   40 back-to-back 3-cycle pulses, gain alternating, started late (as qick_rate.py "same")
  sweep  a 40-step gain sweep loop, one 3-cycle pulse per iteration, started late (as qick_rate.py "sweep")
  virtz  40 x (short flat-top + virt_z), started late (as qick_virtz.py)"""
import os, sys
from pathlib import Path
import qick.riscv_toolchain as tc
tc.FLAGS[0] = "-march=rv32im"; tc.FLAGS.append("-Wl,--build-id=none")
from qick.asm_riscv import RvAveragerProgram as AveragerProgramV2, CompiledOnly
from qick.asm_v2 import AsmV2
from qick.riscq_config import RvConfig
from qick.riscv import _socmap, DEFAULT_SOC
out = Path(sys.argv[1]); GEN, RO, N, F, L = 0, 0, 40, 100.0, 0.006
class Base(AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_gen(ch=GEN, nqz=1); self.declare_readout(ch=RO, length=cfg['ro_len'])
        self.add_pulse(ch=GEN, name="a", ro_ch=RO, style="const", freq=F, length=L, phase=0, gain=1.0)
        self.add_pulse(ch=GEN, name="b", ro_ch=RO, style="const", freq=F, length=L, phase=0, gain=0.4)
        self.add_gauss(ch=GEN, name="ramp", sigma=0.002, length=0.012, even_length=True)
        self.add_pulse(ch=GEN, name="ft", ro_ch=RO, style="flat_top", envelope="ramp", freq=F, length=0.012, phase=0, gain=1.0)
        sub = AsmV2()
        for wname in self.list_pulse_waveforms("ft"):
            sub.read_wmem(name=wname); sub.inc_reg(dst='w_phase', src=self.deg2reg(90, gen_ch=GEN)); sub.write_wmem(name=wname)
        self.add_subroutine("virt_z", sub)
        self.add_readoutconfig(ch=RO, name="ro", freq=F, gen_ch=GEN); self.send_readoutconfig(ch=RO, name="ro", t=0)
class Rate(Base):
    def _body(self, cfg):
        self.trigger(ros=[RO], t=0)
        for i in range(N): self.pulse(ch=GEN, name="a" if i % 2 == 0 else "b", t=round(i * L, 6))
class Sweep(Base):
    def _body(self, cfg):
        self.trigger(ros=[RO], t=0)
        wname = self.list_pulse_waveforms("a")[0]
        self.open_loop(N, "l"); self.pulse(ch=GEN, name="a", t=0)
        self.read_wmem(name=wname); self.inc_reg(dst='w_gain', src=-500); self.write_wmem(name=wname)
        self.delay(L); self.close_loop()
class VirtZ(Base):
    def _body(self, cfg):
        self.trigger(ros=[RO], t=0)
        self.open_loop(N, "l"); self.pulse(ch=GEN, name="ft", t=0); self.call("virt_z"); self.delay_auto(0, ros=False)
        self.close_loop()
c = RvConfig(_socmap(DEFAULT_SOC)); c.equs['RQ_GATE_PULSE_NUM'] = 32
for cls, ro_len in ((Rate, 2.0), (Sweep, 2.0), (VirtZ, 2.0)):
    os.environ["QICK_RV_OUT"] = str(out / cls.__name__.lower())
    try: cls(c, reps=1, final_delay=0.0, initial_delay=0.01, cfg={"ro_len": ro_len}).acquire(None)
    except CompiledOnly as e: print(e)
