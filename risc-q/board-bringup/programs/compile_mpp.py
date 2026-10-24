"""Compile MultiPulseProgram from the compiler team's 00_intro notebook (compiler branch) for RISC-Q.

Runs the notebook's own setup cells and its MultiPulseProgram cell, with optional overrides of the
notebook-level settings (`GEN_CH = ...`, `TRIG_TIME = ...`) and of the pulses' literal `gain=` value.

    compile_mpp.py <notebook> <outdir> [--set GEN_CH=0] [--set TRIG_TIME=0.40] [--gain 0.1]

Run from qick_riscv_demos/tprocv2 of a `compiler` checkout with PYTHONPATH=<it>/qick_lib:<it>/risc-q/software
and the riscv64-unknown-elf-{clang,objcopy,nm} toolchain on PATH.
"""
import argparse
import json
import os
import re

ap = argparse.ArgumentParser()
ap.add_argument("notebook")
ap.add_argument("out")
ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                help="replace the notebook's top-level `NAME = ...` assignment")
ap.add_argument("--gain", type=float, help="replace every literal gain=<x> in the MultiPulseProgram cell")
a = ap.parse_args()
os.environ["QICK_RV_OUT"] = a.out
os.environ["MPLBACKEND"] = "Agg"

sets = dict(s.split("=", 1) for s in a.set)
done = set()
cells = [''.join(c['source']) for c in json.load(open(a.notebook))['cells'] if c['cell_type'] == 'code']
code = []
for src in cells:
    src = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith(('%', '!')))
    for name, val in sets.items():
        if name not in done and re.search(rf'^{name}\s*=', src, re.M):
            src = re.sub(rf'^{name}\s*=.*$', f'{name} = {val}', src, count=1, flags=re.M)
            done.add(name)
    if 'class MultiPulseProgram' in src:
        if a.gain is not None:
            src, n = re.subn(r'gain\s*=\s*[0-9.]+', f'gain={a.gain}', src)
            print(f"gain -> {a.gain} in {n} pulses")
        code.append(src)
        break
    code.append(src)
missing = set(sets) - done
if missing:
    raise SystemExit(f"no top-level assignment for {sorted(missing)} before MultiPulseProgram")

g = {}
from qick.asm_riscv import CompiledOnly
for src in code:
    try:
        exec(compile(src, "<cell>", "exec"), g)
    except CompiledOnly as e:
        print(e)
print({k: g.get(k) for k in ("GEN_CH", "RO_CH", "TRIG_TIME", "FREQ")})
