"""qick_v6.py with the multi-rate (MR) buffer also triggered: records the readout's full-speed, undecimated I/Q.
Writes <out>_<k>.csv (t_us,I,Q, decimated, as qick_v6.py) and <out>_mr_<k>.csv (I,Q at full rate) + <out>_meta.json."""
import json, os, sys
os.environ.setdefault("BOARD", "ZCU216")
import numpy as np
from qick.qick import QickSoc
from qick.asm_v2 import AveragerProgramV2
OUT = sys.argv[1]; GEN0 = int(sys.argv[2]); GEN1 = int(sys.argv[3]); RO = 0
soc = QickSoc(); soccfg = soc
print("TPROC", soc.TPROC_VERSION, "gen0", soccfg["gens"][GEN0]["type"], soccfg["gens"][GEN0]["dac"], "gen1", soccfg["gens"][GEN1]["type"], soccfg["gens"][GEN1]["dac"], "ro", soccfg["readouts"][RO]["ro_type"], soccfg["readouts"][RO]["adc"], flush=True)
class MultiPulseProgram(AveragerProgramV2):
    def _initialize(self, cfg):
        g0, g1, ro = cfg['gen_ch0'], cfg['gen_ch1'], cfg['ro_ch']
        self.declare_gen(ch=g0, nqz=1, **({'mixer_freq':0.0} if 'int4' in soccfg['gens'][g0]['type'] else {}))
        self.declare_gen(ch=g1, nqz=1, **({'mixer_freq':0.0} if 'int4' in soccfg['gens'][g1]['type'] else {}))
        self.declare_readout(ch=ro, length=cfg['ro_len'])
        L = 0.2; f, G = cfg['freq'], cfg['gain']
        self.add_gauss(ch=g0, name='ramp', sigma=L/10, length=L, even_length=True)
        self.add_pulse(ch=g0, name='myflattop', phrst=True, ro_ch=ro, style='flat_top', envelope='ramp', freq=f, length=0.1, phase=0, gain=G)
        self.add_pulse(ch=g0, name='mygaus', ro_ch=ro, style='arb', envelope='ramp', freq=f, phase=0, gain=G)
        self.add_pulse(ch=g0, name='myconst', ro_ch=ro, style='const', length=0.2, freq=f, phase=0, gain=G)
        self.add_pulse(ch=g0, name='myflattop2', ro_ch=ro, style='flat_top', envelope='ramp', freq=f, length=0.1, phase=90, gain=G)
        self.add_gauss(ch=g1, name='ramp_ch1', sigma=L/10, length=L, even_length=True)
        self.add_pulse(ch=g1, name='myconst_ch1', phrst=True, ro_ch=ro, style='const', length=0.5, freq=f*2, phase=0, gain=G)
        self.add_pulse(ch=g1, name='mygauss_ch1', ro_ch=ro, style='arb', envelope='ramp_ch1', freq=f*2, phase=0, gain=G)
        self.add_readoutconfig(ch=ro, name='myro', freq=cfg['ro_freq'], gen_ch=cfg['ro_gen'])
        self.send_readoutconfig(ch=ro, name='myro', t=0)
    def _body(self, cfg):
        self.trigger(ros=[cfg['ro_ch']], mr=True, t=cfg['trig_time'])
        g0, g1 = cfg['gen_ch0'], cfg['gen_ch1']
        for n, t in (('myflattop', 0), ('mygaus', .4), ('myconst', .8), ('myflattop2', 1.2), ('mygaus', 1.6)):
            self.pulse(ch=g0, name=n, t=t)
        self.pulse(ch=g1, name='myconst_ch1', t=0.5)
        self.pulse(ch=g1, name='mygauss_ch1', t=1.5)
cfg = dict(gen_ch0=GEN0, gen_ch1=GEN1, ro_ch=RO, freq=100.0, gain=0.1, trig_time=0.0, ro_len=2.4, ro_freq=float(sys.argv[4]), ro_gen=int(sys.argv[5]))
ro = soccfg["readouts"][RO]
print("readout", {k: ro.get(k) for k in ("fs", "decimation", "f_dds", "f_output", "f_fabric")}, "mr", soccfg["mr_buf"], flush=True)
for k in range(int(os.environ.get("NROUNDS", "10"))):
    prog = MultiPulseProgram(soccfg, reps=1, final_delay=0.5, initial_delay=5.0, cfg=cfg)
    soc.arm_mr(RO)
    iq = prog.acquire_decimated(soc, rounds=1)[0]
    mr = soc.get_mr()
    np.savetxt(f"{OUT}_mr_{k}.csv", mr, delimiter=",", header="I,Q", comments="", fmt="%d")
    print("mr", k, mr.shape, "max", np.abs(mr[:, 0] + 1j * mr[:, 1]).max(), flush=True)
    t = prog.get_time_axis(ro_index=0)
    p = f"{OUT}_{k}.csv"
    np.savetxt(p, np.column_stack([t, iq[:, 0], iq[:, 1]]), delimiter=",", header="t_us,I,Q", comments="")
    print(p, len(t), "max mag", np.abs(iq[:, 0] + 1j*iq[:, 1]).max(), flush=True)
json.dump(dict(cfg, readout={k: ro.get(k) for k in ("fs", "decimation", "f_dds", "f_output", "f_fabric")}), open(OUT + "_meta.json", "w"))
