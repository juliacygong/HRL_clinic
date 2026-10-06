"""Drop-in for `from qick import *` when targeting a RISC-Q core: same program classes and names, RISC-V underneath.
QickSoc() is the RISC-Q SoC description; programs compiled for it are written to the output directory."""
import logging
import os
from pathlib import Path

from .asm_riscv_v1 import (AveragerProgram, RAveragerProgram, NDAveragerProgram, RiscvQickProgram as QickProgram,  # noqa: F401
                           QickRegister, QickRegisterManagerMixin)
from .averager_program import QickSweep  # noqa: F401
from .riscq_config import RvConfig

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOC = ROOT / "risc-q" / "software" / "configs" / "sim-2q.json"


def _socmap(path):
    import sys
    sys.path[:0] = [str(ROOT / "risc-q" / "software")]
    from riscq.map import SocMap, SocParams
    return SocMap(SocParams.load(path))


class NoCoreAttached(RuntimeError):
    pass


class QickSoc(RvConfig):
    """RISC-Q stand-in for QickSoc: it is also the QickConfig. Programs loaded onto it are exported as .s/.bin."""

    def __init__(self, soc=DEFAULT_SOC, out=None, **kwargs):
        super().__init__(_socmap(soc), v1=True)
        self.out = Path(out or os.environ.get("QICK_RV_OUT", "out"))
        self.programs = []

    def load_program(self, prog):
        self.out.mkdir(parents=True, exist_ok=True)
        name = type(prog).__name__
        n = sum(1 for p in self.programs if type(p).__name__ == name) + 1
        stem = name if n == 1 else f"{name}_{n}"
        prog.write_asm(self.out / f"{stem}.s")
        prog.write_bin(self.out / f"{stem}.bin")
        self.programs.append(prog)
        print(f"{name}: {len(prog.binprog)} words -> {self.out / stem}.[s|bin]")

    def no_core(self, prog):
        raise NoCoreAttached(f"{type(prog).__name__} was compiled to {self.out}, but no RISC-Q core is attached to run it")

    def __getattr__(self, name):
        # hardware pokes (soc.tproc..., soc.arm_ddr4(), soc.get_mr(), ...) have nothing to talk to
        if name.startswith('_'):
            raise AttributeError(name)
        raise NoCoreAttached(f"soc.{name} needs a RISC-Q core, none is attached")

    def reset_gens(self):
        pass

    def start_tproc(self):
        pass

    def stop_tproc(self, lazy=False):
        pass
