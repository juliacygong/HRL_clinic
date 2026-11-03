"""Compile MultiPulseProgram of emulator/notebooks/00_intro_emu_2sg.ipynb for RISC-Q, same class and config as the
tProc v2 run. Only differences: base class, and the trigger's pins/ddr4 (RISC-Q has readout triggers only).
Run with PYTHONPATH=<compiler checkout>/qick_lib:<compiler checkout>/risc-q/software and the riscv toolchain on PATH.

train1 (two-generator board program) = this, then ../../programs/patch_readout_len.py <out>/MultiPulseProgram.s 2.0 <dir>
(the backend drops declare_readout's length) plus the two .env files. Rebuilt 2026-11-02 at compiler 8da261d7: .s, .bin
and .env identical to train1; the .elf differs only in its temporary object-file names."""
import json, os, pathlib, sys
os.environ["QICK_RV_OUT"] = sys.argv[1]
nb = json.load(open("/home/galencar/HRL_clinic/emulator/notebooks/00_intro_emu_2sg.ipynb"))
cell = next(''.join(c['source']) for c in nb['cells'] if c['cell_type'] == 'code' and 'class MultiPulseProgram' in ''.join(c['source']))
cell = cell.replace(", pins=[0], t=cfg['trig_time'], ddr4=True", ", t=cfg['trig_time']")
import qick.riscv_toolchain as _tc; _tc.CACHE = pathlib.Path(sys.argv[1]) / "cache"; _tc.CACHE.mkdir(parents=True, exist_ok=True)
from qick.asm_riscv import RvAveragerProgram as AveragerProgramV2, CompiledOnly
from qick.riscq_config import RvConfig
from qick.riscv import _socmap, DEFAULT_SOC
soc = soccfg = RvConfig(_socmap(DEFAULT_SOC))
g = dict(AveragerProgramV2=AveragerProgramV2, soccfg=soccfg, GEN_CH0=0, GEN_CH1=1, RO_CH=0, TRIG_TIME=0.0, FREQ=100)
cell = cell.replace('final_delay=0.5,', 'final_delay=0.5, initial_delay=5.0,'); assert 'initial_delay=5.0' in cell
cell = cell.replace("name='myflattop', ro_ch", "name='myflattop', phrst=True, ro_ch").replace("name='myconst_ch1', ro_ch", "name='myconst_ch1', phrst=True, ro_ch"); assert cell.count('phrst=True') == 2
import re; cell, n = re.subn(r'gain=1\.0', 'gain=0.1', cell); assert n == 6; cell = cell.replace("'ro_len':    1.9", "'ro_len':    2.0"); assert "'ro_len':    2.0" in cell
exec(compile(cell, "<cell>", "exec"), g)
try: g['prog'].acquire_decimated(soc)
except CompiledOnly as e: print(e)
