"""Copy qick_demos_sho/tprocv2/*.ipynb to this folder with the minimum changes needed to target a RISC-Q core.
Every difference from the originals is listed in EDITS (old text -> new text, per notebook), so the diff is explicit.
Outputs are cleared. The source folder is found from QICK_DEMOS_SHO (default: a sibling of the repo)."""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = next((Path(c) for c in (os.environ.get("QICK_DEMOS_SHO"), HERE.parents[2] / "qick_demos_sho" / "tprocv2",
                              HERE.parents[1] / "qick_demos_sho" / "tprocv2")
            if c and Path(c).exists()), None)
if SRC is None:
    sys.exit("cannot find qick_demos_sho/tprocv2: set QICK_DEMOS_SHO")
DST = HERE

# (regex, replacement) applied to code cells. Everything here is a hardware number or import, never program logic.
ALL = [(r"^from qick\.asm_v2 import AveragerProgramV2", "from qick.asm_riscv import RvAveragerProgram as AveragerProgramV2"),   # RISC-V backend
       (r"^from qick\.asm_v2 import (AcquireProgramV2|QickProgramV2)", r"from qick.asm_riscv import RvProgram as \1"),
       (r"^from qick\.pyro import make_proxy\n", "from qick.riscq_config import RvConfig\nfrom qick.riscv import _socmap, DEFAULT_SOC\n"),
       (r"^soc, soccfg = make_proxy\(.*\)$", "soc = soccfg = RvConfig(_socmap(DEFAULT_SOC))"),    # local RISC-Q description, no pyro
       (r"(?s)^(# )?# use pyro's traceback code.*?^(# )?ip\.set_custom_exc[^\n]*\n?", ""),    # no custom handler: failures must fail
       (r"pins=\[0\], ", ""), (r"ddr4=True, mr=True, ", ""), (r", ddr4=True", "")]            # no output pins, no DDR4/MR buffers
EDITS = {
    "00_intro": [(r"^GEN_CH = 7", "GEN_CH = 1")],                       # readout drive = RISC-Q channel 1 (one readout, 0)
    "01_gens-and-readouts": [(r"^FSGEN_CH = 0", "FSGEN_CH = 1"),       # the only generator type RISC-Q has
                             (r"^config\['steps'\]=100001", "config['steps']=2797")],   # gen/readout frequency-match step is ~358 Hz: 1 MHz fits 2797 steps
}
# cells removed: restoring a dumped tProc program, tProc instruction dicts/raw waveforms, and mux/mixer gens and std/mux readouts, which RISC-Q does not have
DROP = {
    "00_intro": {17, 55, 56, 57, 59, 60, 79},
    "01_gens-and-readouts": {*range(12, 23), *range(41, 64)},
}


def convert(name):
    nb = json.loads((SRC / f"{name}.ipynb").read_text())
    nb["cells"] = [c for i, c in enumerate(nb["cells"]) if i not in DROP.get(name, ())]
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        text = "".join(cell["source"])
        for old, new in ALL + EDITS.get(name, []):
            text = re.sub(old, new, text, flags=re.M)
        cell["source"] = text.splitlines(keepends=True)
        cell["outputs"], cell["execution_count"] = [], None
    (DST / f"{name}.ipynb").write_text(json.dumps(nb, indent=1) + "\n")


if __name__ == "__main__":
    for f in sorted(SRC.glob("*.ipynb")):
        convert(f.stem)
        print("wrote", f.stem)
