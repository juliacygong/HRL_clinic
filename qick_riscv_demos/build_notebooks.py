"""Copy ../qick_demos/*.ipynb to this folder with the minimum changes needed to target a RISC-Q core.
Every difference from the originals is listed in EDITS (old text -> new text, per notebook), so the diff is explicit.
Outputs are cleared."""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = next((Path(c) for c in (os.environ.get("QICK_REPO"), HERE.parent, HERE.parent / "HRL_clinic")
             if c and (Path(c) / "qick_lib").exists()), None)
if ROOT is None:
    sys.exit("cannot find the repo: set QICK_REPO to the HRL_clinic checkout")
SRC = ROOT / "qick_demos"
DST = HERE

import re

# (regex, replacement) applied to code cells. Everything here is a hardware number or import, never program logic.
ALL = [(r"from qick import \*", "from qick.riscv import *")]           # RISC-V backend, same names
CH = [(r'"res_ch":\s*6', '"res_ch":1')]                                  # readout drive = RISC-Q channel 1
ONE_READOUT = [(r"for ch in \[0,1\]:", "for ch in [0]:"), (r"adcs=\[0,1\]", "adcs=[0]")]   # RISC-Q has one readout
EDITS = {
    "00_Send_receive_pulse": [(r"GEN_CH = 6", "GEN_CH = 1")],
    "01_Phase_coherent_readout": [(r"out_chs = \[0,5,6\]", "out_chs = [0,1]"), (r"gen_ch=6", "gen_ch=1"),
                                  (r"for ch in range\(2\)", "for ch in range(1)"), (r"adcs=\[0,1\]", "adcs=[0]")],
    "02_Sweeping_variables": CH,
    "03_Conditional_logic": CH,
    "05_PhaseCoherence_QickProgram": CH,
    "06_qubit_demos": ONE_READOUT + [(r'"res_ch":5', '"res_ch":1'), (r'"qubit_ch":2', '"qubit_ch":0'),
                                     (r"gen_ch=5", "gen_ch=1"), (r"gen_ch=2", "gen_ch=0")],
    "07_Sweep_ND_variables": [(r'"res_ch":\s*6', '"res_ch": 1')],
    "08_Special_buffers": [(r"GEN_CH = 6", "GEN_CH = 1")],
}


def convert(name):
    nb = json.loads((SRC / f"{name}.ipynb").read_text())
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        text = "".join(cell["source"])
        for old, new in ALL + EDITS.get(name, []):
            text = re.sub(old, new, text)
        cell["source"] = text.splitlines(keepends=True)
        cell["outputs"], cell["execution_count"] = [], None
    (DST / f"{name}.ipynb").write_text(json.dumps(nb, indent=1) + "\n")


if __name__ == "__main__":
    for f in sorted(SRC.glob("*.ipynb")):
        if f.stem != "000_Install_qick_package":
            convert(f.stem)
            print("wrote", f.stem)
