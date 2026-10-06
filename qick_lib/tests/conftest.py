import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "qick_lib"), str(ROOT / "risc-q" / "software")]

CONFIG = ROOT / "risc-q" / "software" / "configs" / "sim-2q.json"
