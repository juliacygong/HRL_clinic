"""Compile the board demo programs for the slot-table build.

    board_progs.py <outdir>

Writes <outdir>/{old_pu,new_pu,stress}/<Class>.[s|bin|elf] + _gen<N>.env:
  old_pu  PulseUpdateProgram (00_intro notebook) at the default 1 us initial delay, with the slot-table
          defines hidden, so the compiler emits the previous per-pulse table rewrite (the "before" program)
  new_pu  the same program with slot tables: start time + fires per pulse
  stress  both gens at once, 1 us initial delay: gen 0 cycles 8 gaussians (gain ramp, 45 deg phase steps)
          every 50 ns, gen 1 hops between 4 carrier frequencies every 100 ns, for 1.5 us per shot, 3 shots
The trigger is at t = 0 so the 2 us capture window holds every pulse.
"""
import os
import sys
from pathlib import Path

import qick.riscv_toolchain as tc
tc.FLAGS[0] = "-march=rv32im"            # Vivado's GCC predates the zmmul name; none of these programs multiply
tc.FLAGS.append("-Wl,--build-id=none")  # keep .text at the reset address

from qick.asm_riscv import RvAveragerProgram as AveragerProgramV2, CompiledOnly
from qick.asm_v2 import AsmV2
from qick.riscq_config import RvConfig
from qick.riscv import _socmap, DEFAULT_SOC

out = Path(sys.argv[1])


class PulseUpdateProgram(AveragerProgramV2):
    # verbatim from 00_intro.ipynb ("pulse updates, subroutines")
    def _initialize(self, cfg):
        ro_ch = cfg['ro_ch']
        gen_ch = cfg['gen_ch']
        self.declare_gen(ch=gen_ch, nqz=1)
        self.declare_readout(ch=ro_ch, length=cfg['ro_len'])
        ramp_len = 0.1
        self.add_gauss(ch=gen_ch, name="ramp", sigma=ramp_len/10, length=ramp_len, even_length=True)
        self.add_pulse(ch=gen_ch, name="myflattop", ro_ch=ro_ch, style="flat_top", envelope="ramp",
                       freq=cfg['freq'], length=0.05, phase=0, gain=1.0)
        sub = AsmV2()
        for wname in self.list_pulse_waveforms("myflattop"):
            sub.read_wmem(name=wname)
            sub.inc_reg(dst='w_phase', src=self.deg2reg(90, gen_ch=cfg['gen_ch']))
            sub.write_wmem(name=wname)
        self.add_subroutine("virt_z", sub)
        self.add_readoutconfig(ch=ro_ch, name="myro", freq=cfg['freq'], gen_ch=gen_ch)
        self.send_readoutconfig(ch=ro_ch, name="myro", t=0)

    def _body(self, cfg):
        self.trigger(ros=[cfg['ro_ch']], t=cfg['trig_time'])
        self.pulse(ch=cfg['gen_ch'], name="myflattop", t=0)
        self.call("virt_z")
        self.pulse(ch=cfg['gen_ch'], name="myflattop", t=0.2)
        self.pulse(ch=cfg['gen_ch'], name="myflattop", t=0.4)
        self.call("virt_z")
        self.pulse(ch=cfg['gen_ch'], name="myflattop", t=0.6)


class StressProgram(AveragerProgramV2):
    def _initialize(self, cfg):
        ro_ch = cfg['ro_ch']
        for ch in (0, 1):
            self.declare_gen(ch=ch, nqz=1)
        self.declare_readout(ch=ro_ch, length=cfg['ro_len'])
        self.add_gauss(ch=0, name="g", sigma=0.008, length=0.04, even_length=True)
        for k in range(8):   # gen 0: gain ramp 1/8 .. 1 and a 45 deg phase step per pulse
            self.add_pulse(ch=0, name=f"g{k}", ro_ch=ro_ch, style="arb", envelope="g",
                           freq=cfg['f0'], phase=45 * k, gain=(k + 1) / 8)
        for k, f in enumerate(cfg['f1']):   # gen 1: carrier hops
            self.add_pulse(ch=1, name=f"h{k}", ro_ch=ro_ch, style="const", freq=f,
                           length=0.08, phase=0, gain=0.8)
        self.add_readoutconfig(ch=ro_ch, name="myro", freq=cfg['f0'], gen_ch=0)
        self.send_readoutconfig(ch=ro_ch, name="myro", t=0)

    def _body(self, cfg):
        self.trigger(ros=[cfg['ro_ch']], t=cfg['trig_time'])
        events = [(i * 0.05, 0, f"g{i % 8}") for i in range(cfg['n0'])]
        events += [(0.02 + i * 0.1, 1, f"h{i % len(cfg['f1'])}") for i in range(cfg['n1'])]
        for t, ch, name in sorted(events):   # time order, so the CPU stays ahead on both gens
            self.pulse(ch=ch, name=name, t=round(t, 6))


def compile_one(prog, sub, hide_slots=False):
    soccfg = prog.soccfg
    os.environ["QICK_RV_OUT"] = str(out / sub)
    try:
        prog.acquire(soccfg)
    except CompiledOnly as e:
        print(e)


def make_cfg(hide_slots):
    cfg = RvConfig(_socmap(DEFAULT_SOC))
    cfg.equs['RQ_GATE_PULSE_NUM'] = int(os.environ.get("SLOTS", cfg.equs['RQ_GATE_PULSE_NUM']))
    if hide_slots:
        for k in ("RQ_SLOT_CONF", "RQ_SLOT_FREQ"):
            cfg.equs.pop(k, None)
    return cfg


pu_cfg = {'gen_ch': 0, 'ro_ch': 0, 'freq': 500, 'trig_time': 0.0, 'ro_len': 0.9}
for sub, hide in (("old_pu", True), ("new_pu", False)):
    soccfg = make_cfg(hide)
    compile_one(PulseUpdateProgram(soccfg, reps=2, final_delay=0.5, cfg=pu_cfg), sub)

st_cfg = {'ro_ch': 0, 'trig_time': 0.0, 'ro_len': 2.0, 'f0': 500, 'f1': [100, 200, 300, 400],
          'n0': 30, 'n1': 15}
compile_one(StressProgram(make_cfg(False), reps=3, final_delay=0.5, cfg=st_cfg), "stress")
