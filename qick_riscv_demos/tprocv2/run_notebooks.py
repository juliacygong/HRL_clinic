"""Execute the notebooks against the RISC-Q backend and report per notebook.
python run_notebooks.py [--out DIR] [names...]   (default out: ./out, or $QICK_RV_OUT)"""
import argparse
import os
import re
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

HERE = Path(__file__).resolve().parent
ROOT = next((Path(c) for c in (os.environ.get("QICK_REPO"), HERE.parent.parent, HERE.parent.parent / "HRL_clinic")
             if c and (Path(c) / "qick_lib").exists()), None)
if ROOT is None:
    sys.exit("cannot find the repo: set QICK_REPO to the HRL_clinic checkout")
ap = argparse.ArgumentParser()
ap.add_argument("names", nargs="*")
ap.add_argument("--out", type=Path, default=Path(os.environ.get("QICK_RV_OUT", HERE / "out")))
ap.add_argument("-v", action="store_true", help="print every failing cell")
args = ap.parse_args()

os.environ["PYTHONPATH"] = os.pathsep.join([str(ROOT / "qick_lib"), str(ROOT / "risc-q" / "software")])
os.environ["QICK_RV_OUT"] = str(args.out)
os.environ["MPLBACKEND"] = "Agg"
files = [HERE / f"{n}.ipynb" for n in args.names] or sorted(HERE.glob("[0-9]*.ipynb"))
bad = 0
for f in files:
    nb = nbformat.read(f, as_version=4)
    os.environ["QICK_RV_OUT"] = str(args.out / f.stem)
    NotebookClient(nb, timeout=600, allow_errors=True, resources={"metadata": {"path": str(HERE)}}).execute()
    expected, real, downstream = 0, [], 0
    seen_compiled = False
    for i, c in enumerate(nb.cells):
        for o in c.get("outputs", []) if c.cell_type == "code" else []:
            if o.output_type != "error":
                continue
            tb = "\n".join(o.traceback)
            frames = re.findall(r"File\s+(\S+?\.py)|(Cell In)", re.sub(r"\x1b\[[0-9;]*m", "", tb))
            raised_in_lib = bool(frames) and bool(frames[-1][0]) and ("/qick_lib/" in frames[-1][0] or "/risc-q/" in frames[-1][0])
            if o.ename == "CompiledOnly":
                expected, seen_compiled = expected + 1, True
            elif seen_compiled and not raised_in_lib:
                downstream += 1                     # plotting/analysis of data a core would have produced
            else:
                real.append((i, o))
    compiled = sum("words ->" in "".join(o.get("text", "")) for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", []))
    print(f"{f.stem}: {compiled} program(s) compiled, {expected} stopped at acquire, "
          f"{downstream} data-dependent cell(s) skipped, {len(real)} failure(s)")
    for i, err in real:
        print(f"   cell {i}: {err.ename}: {str(err.evalue)[:160]}")
    bad += len(real)
sys.exit(bool(bad))
