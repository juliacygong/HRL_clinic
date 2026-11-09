"""tProc v2 pulse issue rate on the stock QICK firmware (ZCU216, run on the board as root).

    qick_rate.py <out prefix> [runs, default 10]

Gen 3 (axis_signal_gen_v6, DAC 3_228) -> ADC 2_226 = readout 1, captured at the full rate with the MR buffer.
  same:  N back-to-back 3-cycle const pulses, gain alternating 1.0 / 0.4 so each boundary shows
  sweep: an N-step loop, one 3-cycle pulse per iteration, its gain rewritten every iteration
         (read_wmem / inc_reg w_gain / write_wmem, the code QICK's sweeps generate)
Both start late (initial_delay 0.01 us), so if the tProc cannot keep up, gaps appear between pulses.
"""
import json
import os
import sys
os.environ.setdefault("BOARD", "ZCU216")
import numpy as np
from qick.qick import QickSoc
from qick.asm_v2 import AveragerProgramV2

OUT = sys.argv[1]
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 10
GEN, RO, N, F = 3, 1, 40, 100.0
soc = QickSoc(); soccfg = soc
L = soccfg.cycles2us(3, gen_ch=GEN)
print("TPROC", soc.TPROC_VERSION, "gen", soccfg["gens"][GEN]["type"], "f_fabric", soccfg["gens"][GEN]["f_fabric"],
      "pulse", L, "us", flush=True)


class Base(AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_gen(ch=GEN, nqz=1)
        self.declare_readout(ch=RO, length=cfg['ro_len'])
        self.add_pulse(ch=GEN, name="a", ro_ch=RO, style="const", freq=F, length=L, phase=0, gain=1.0)
        self.add_pulse(ch=GEN, name="b", ro_ch=RO, style="const", freq=F, length=L, phase=0, gain=0.4)
        self.add_readoutconfig(ch=RO, name="ro", freq=F, gen_ch=GEN)
        self.send_readoutconfig(ch=RO, name="ro", t=0)


class Same(Base):
    def _body(self, cfg):
        self.trigger(ros=[RO], mr=True, t=0)
        for i in range(N):
            self.pulse(ch=GEN, name="a" if i % 2 == 0 else "b", t=round(i * L, 9))


class Sweep(Base):
    def _body(self, cfg):
        self.trigger(ros=[RO], mr=True, t=0)
        wname = self.list_pulse_waveforms("a")[0]
        self.open_loop(N, "l")
        self.pulse(ch=GEN, name="a", t=0)
        self.read_wmem(name=wname)
        self.inc_reg(dst='w_gain', src=-500)
        self.write_wmem(name=wname)
        self.delay(L)
        self.close_loop()


meta = {}
for name, cls in (("same", Same), ("sweep", Sweep)):
    for k in range(RUNS):
        prog = cls(soccfg, reps=1, final_delay=0.0, initial_delay=0.01, cfg={"ro_len": 1.5})
        if k == 0:
            open(f"{OUT}_{name}.asm", "w").write(str(prog.asm()))
        soc.arm_mr(RO)
        prog.acquire_decimated(soc, rounds=1, progress=False)
        mr = soc.get_mr()
        np.savetxt(f"{OUT}_{name}_mr_{k}.csv", mr, delimiter=",", header="I,Q", comments="", fmt="%d")
        print(f"{name} run {k}: {len(mr)} samples, max {np.abs(mr[:, 0] + 1j * mr[:, 1]).max():.0f}", flush=True)
ro = soccfg["readouts"][RO]
json.dump(dict(N=N, L_us=L, freq=F, gen=GEN, ro=RO, runs=RUNS, gen_f_fabric=soccfg["gens"][GEN]["f_fabric"],
               readout={k: ro.get(k) for k in ("fs", "decimation", "f_fabric")},
               tproc_f=soccfg["tprocs"][0].get("f_time") if "tprocs" in soccfg._cfg else None),
          open(OUT + "_meta.json", "w"), default=str)
