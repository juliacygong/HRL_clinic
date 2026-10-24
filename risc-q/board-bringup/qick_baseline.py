#!/usr/bin/env python3
"""Run the QICK tProc v2 loopback MultiPulseProgram from a board notebook headlessly and save its trace.

Executes the notebook's code cells up to and including the one that defines MultiPulseProgram and calls
acquire_decimated (by default ~/jupyter_notebooks/Untitled.ipynb on the ZCU216: QickSoc() with the default
firmware, GEN 14 -> DAC 2_231 / JHC3, RO 0 -> ADC 0_226 / JHC7), unchanged except: IPython magics dropped,
plt.show() -> savefig. Then writes t_us,I,Q to CSV — the plot_compare.py baseline format.

QickSoc() reprograms the PL with QICK's firmware and the clock chips to 245.76 MHz: rerun bringup.py
(without --skip-clocks / --no-download) before running RISC-Q again.

    sudo -E /usr/local/share/pynq-venv/bin/python3 qick_baseline.py [--nb NOTEBOOK] [--out qick_baseline]
"""
import argparse
import json
import os
import re
import sys

os.environ.setdefault("BOARD", "ZCU216")
import matplotlib
matplotlib.use("Agg")

ap = argparse.ArgumentParser()
ap.add_argument("--nb", default="/home/xilinx/jupyter_notebooks/Untitled.ipynb")
ap.add_argument("--out", default="qick_baseline")
a = ap.parse_args()

cells = [''.join(c['source']) for c in json.load(open(a.nb))['cells'] if c['cell_type'] == 'code']
run = []
for src in cells:
    run.append(src)
    if 'class MultiPulseProgram' in src and 'acquire_decimated' in src:
        break
else:
    sys.exit(f"{a.nb}: no cell defines MultiPulseProgram and calls acquire_decimated")
# setup cells (imports, QickSoc) + the program cell; skip the channel-scan cells in between
run = [s for s in run if not re.search(r'test_pair\(|GEN_CANDIDATES', s)]

import matplotlib.pyplot as plt
g = {}
for i, src in enumerate(run):
    src = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith(('%', '!')))
    src = src.replace("plt.show()", f"plt.savefig('{a.out}.png', dpi=130)")
    print(f"[qick_baseline] running cell {i} ({src.strip().splitlines()[0][:60]!r})", flush=True)
    exec(compile(src, f"<cell {i}>", "exec"), g)

import numpy as np
t, iq = g["t"], g["iq_list"][0]
np.savetxt(f"{a.out}.csv", np.column_stack([t, iq[:, 0], iq[:, 1]]), delimiter=",",
           header="t_us,I,Q", comments="")
cfg = g.get("config", {})
with open(f"{a.out}_meta.json", "w") as f:
    json.dump({"notebook": a.nb, "config": cfg, "samples": len(t)}, f, indent=2, default=str)
print(f"[qick_baseline] wrote {a.out}.csv ({len(t)} samples), {a.out}.png, {a.out}_meta.json; config {cfg}")
