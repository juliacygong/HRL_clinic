"""python qick_lib/riscq_cli.py prog.py [--out DIR] [--soc CONFIG.json] [--reps N] [--final-delay US] 

Compiles every RvProgram/RvAveragerProgram subclass defined in prog.py (any file, anywhere) to <out>/<Class>.s and .bin."""

import argparse
import importlib.util
import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "qick_lib"), str(ROOT / "risc-q" / "software")]

from qick.asm_riscv import RvAveragerProgram, RvMixin  # noqa: E402
from qick.riscq_config import RvConfig  # noqa: E402
from riscq.map import SocMap, SocParams  # noqa: E402

DEFAULT_OUT = ROOT / "qick_lib" / "tests" / "out"
DEFAULT_SOC = ROOT / "risc-q" / "software" / "configs" / "sim-2q.json"


def load_programs(path: Path) -> list:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(mod)
    return [c for _, c in inspect.getmembers(mod, inspect.isclass)
            if issubclass(c, RvMixin) and c.__module__ == mod.__name__]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("program", type=Path)
    ap.add_argument("--out", type=Path, default=Path(os.environ.get("QICK_RV_OUT", DEFAULT_OUT)))
    ap.add_argument("--soc", type=Path, default=DEFAULT_SOC)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--final-delay", type=float, default=1.0)
    args = ap.parse_args(argv)

    soc_map = SocMap(SocParams.load(args.soc))
    cfg = RvConfig(soc_map)
    progs = load_programs(args.program.resolve())
    if not progs:
        sys.exit(f"no RvProgram/RvAveragerProgram subclass found in {args.program}")
    args.out.mkdir(parents=True, exist_ok=True)
    for cls in progs:
        kwargs = dict(reps=args.reps, final_delay=args.final_delay) if issubclass(cls, RvAveragerProgram) else {}
        prog = cls(cfg, **kwargs)
        prog.compile()
        prog.write_asm(args.out / f"{cls.__name__}.s")
        prog.write_bin(args.out / f"{cls.__name__}.bin")
        print(f"{cls.__name__}: {len(prog.binprog['pmem'])} words -> {args.out}/{cls.__name__}.[s|bin]")


if __name__ == "__main__":
    main()
