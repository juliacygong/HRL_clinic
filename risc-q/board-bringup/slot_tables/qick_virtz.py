"""tProc v2 counterpart of the RISC-Q VirtZ benchmark: a 100-step loop, each iteration a short flat-top (3
waveforms) then virt_z (read_wmem / +90 deg / write_wmem on each waveform), started late; gen 3 (DAC 3_228) ->
ADC 2_226 = readout 1, MR buffer. The iteration spacing is the tProc's cost.
    qick_virtz.py <out prefix> [runs]"""
import json, os, sys
os.environ.setdefault("BOARD", "ZCU216")
import numpy as np
from qick.qick import QickSoc
from qick.asm_v2 import AveragerProgramV2, AsmV2
OUT = sys.argv[1]; RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 5
GEN, RO, N, F = 3, 1, 40, 100.0
soc = QickSoc(); soccfg = soc
class VirtZ(AveragerProgramV2):
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
        self.trigger(ros=[RO], mr=True, t=0)
        self.open_loop(N, "l")
        self.pulse(ch=GEN, name="ft", t=0); self.call("virt_z"); self.delay_auto(0, ros=False)
        self.close_loop()
for k in range(RUNS):
    prog = VirtZ(soccfg, reps=1, final_delay=0.0, initial_delay=0.01, cfg={"ro_len": 1.6})
    if k == 0: open(f"{OUT}_virtz.asm", "w").write(str(prog.asm()))
    soc.arm_mr(RO); prog.acquire_decimated(soc, rounds=1, progress=False); mr = soc.get_mr()
    np.savetxt(f"{OUT}_virtz_mr_{k}.csv", mr, delimiter=",", header="I,Q", comments="", fmt="%d")
    print(f"run {k}: {len(mr)} samples, max {np.abs(mr[:, 0] + 1j * mr[:, 1]).max():.0f}", flush=True)
