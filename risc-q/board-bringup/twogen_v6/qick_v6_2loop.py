"""Two-generator MultiPulseProgram on QICK tProc v2 with both generators cabled, so one round plays both.

    qick_v6_2loop.py <out prefix> [runs per MR channel, default 20: 2x that many runs in all]

Program gen 0 (100 MHz) is QICK gen 3 on DAC 3_228 -> ADC 2_226 (readout 1); program gen 1 (200 MHz) is QICK gen 1
on DAC 1_228 -> ADC 0_226 (readout 0). Both readouts capture every run (decimated). The MR buffer records one
readout per run, so runs alternate: even runs readout 0, odd runs readout 1. Writes <out>_ro{0,1}_<k>.csv (t_us,I,Q decimated),
<out>_mr{0,1}_<k>.csv (I,Q at the full 2457.6 MS/s) and <out>_meta.json.
"""
import json, os, sys
os.environ.setdefault("BOARD", "ZCU216")
import numpy as np
from qick.qick import QickSoc
from qick.asm_v2 import AveragerProgramV2
OUT = sys.argv[1]; N = int(sys.argv[2]) if len(sys.argv) > 2 else 20
GEN0, GEN1 = 3, 1
soc = QickSoc(); soccfg = soc
print("TPROC", soc.TPROC_VERSION, "gen0", soccfg["gens"][GEN0]["type"], soccfg["gens"][GEN0]["dac"],
      "gen1", soccfg["gens"][GEN1]["type"], soccfg["gens"][GEN1]["dac"],
      "ro0 adc", soccfg["readouts"][0]["adc"], "ro1 adc", soccfg["readouts"][1]["adc"], flush=True)


class MultiPulseProgram(AveragerProgramV2):
    def _initialize(self, cfg):
        g0, g1 = cfg['gen_ch0'], cfg['gen_ch1']
        self.declare_gen(ch=g0, nqz=1)
        self.declare_gen(ch=g1, nqz=1)
        for ro in (0, 1):
            self.declare_readout(ch=ro, length=cfg['ro_len'])
        L = 0.2; f, G = cfg['freq'], cfg['gain']
        self.add_gauss(ch=g0, name='ramp', sigma=L/10, length=L, even_length=True)
        self.add_pulse(ch=g0, name='myflattop', phrst=True, ro_ch=1, style='flat_top', envelope='ramp', freq=f, length=0.1, phase=0, gain=G)
        self.add_pulse(ch=g0, name='mygaus', ro_ch=1, style='arb', envelope='ramp', freq=f, phase=0, gain=G)
        self.add_pulse(ch=g0, name='myconst', ro_ch=1, style='const', length=0.2, freq=f, phase=0, gain=G)
        self.add_pulse(ch=g0, name='myflattop2', ro_ch=1, style='flat_top', envelope='ramp', freq=f, length=0.1, phase=90, gain=G)
        self.add_gauss(ch=g1, name='ramp_ch1', sigma=L/10, length=L, even_length=True)
        self.add_pulse(ch=g1, name='myconst_ch1', phrst=True, ro_ch=0, style='const', length=0.5, freq=f*2, phase=0, gain=G)
        self.add_pulse(ch=g1, name='mygauss_ch1', ro_ch=0, style='arb', envelope='ramp_ch1', freq=f*2, phase=0, gain=G)
        # each readout demodulates its own cable's generator
        self.add_readoutconfig(ch=0, name='ro0', freq=f*2, gen_ch=g1)
        self.add_readoutconfig(ch=1, name='ro1', freq=f, gen_ch=g0)
        self.send_readoutconfig(ch=0, name='ro0', t=0)
        self.send_readoutconfig(ch=1, name='ro1', t=0)

    def _body(self, cfg):
        self.trigger(ros=[0, 1], mr=True, t=cfg['trig_time'])
        g0, g1 = cfg['gen_ch0'], cfg['gen_ch1']
        for n, t in (('myflattop', 0), ('mygaus', .4), ('myconst', .8), ('myflattop2', 1.2), ('mygaus', 1.6)):
            self.pulse(ch=g0, name=n, t=t)
        self.pulse(ch=g1, name='myconst_ch1', t=0.5)
        self.pulse(ch=g1, name='mygauss_ch1', t=1.5)


cfg = dict(gen_ch0=GEN0, gen_ch1=GEN1, freq=100.0, gain=0.1, trig_time=0.0, ro_len=2.4)
count = {0: 0, 1: 0}
for k in range(2 * N):
    mr_ch = int(os.environ.get("MR_CH", k % 2))    # the MR buffer records one readout per run (MR_CH pins it)
    prog = MultiPulseProgram(soccfg, reps=1, final_delay=0.5, initial_delay=5.0, cfg=cfg)
    soc.arm_mr(mr_ch)
    iqs = prog.acquire_decimated(soc, rounds=1, progress=False)
    mr = soc.get_mr()
    j = count[mr_ch]; count[mr_ch] += 1
    np.savetxt(f"{OUT}_mr{mr_ch}_{j}.csv", mr, delimiter=",", header="I,Q", comments="", fmt="%d")
    for ro in (0, 1):
        t = prog.get_time_axis(ro_index=ro); iq = iqs[ro]
        np.savetxt(f"{OUT}_ro{ro}_{k}.csv", np.column_stack([t, iq[:, 0], iq[:, 1]]), delimiter=",", header="t_us,I,Q", comments="")
    print(f"run {k}: mr ro{mr_ch} max {np.abs(mr[:, 0] + 1j * mr[:, 1]).max():.0f}, decimated max "
          f"ro0 {np.abs(iqs[0][:, 0] + 1j * iqs[0][:, 1]).max():.0f} ro1 {np.abs(iqs[1][:, 0] + 1j * iqs[1][:, 1]).max():.0f}", flush=True)
ro = soccfg["readouts"][0]
json.dump(dict(cfg, runs_per_mr=N, readout={k: ro.get(k) for k in ("fs", "decimation", "f_dds", "f_output", "f_fabric")}),
          open(OUT + "_meta.json", "w"))
