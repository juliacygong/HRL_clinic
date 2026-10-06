"""Assemble and link a .s with the riscv toolchain against the riscq runtime (fw/start.S + generated link.ld).
Read-only use of the risc-q checkout; nothing is written there."""
import hashlib
import functools
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

FW = Path(__file__).resolve().parents[2] / "risc-q" / "software" / "fw"
CC = shutil.which("riscv64-unknown-elf-clang") or shutil.which("riscv64-unknown-elf-gcc")
OBJCOPY = shutil.which("riscv64-unknown-elf-objcopy")
NM = shutil.which("riscv64-unknown-elf-nm")
FLAGS = ["-march=rv32i_zmmul", "-mabi=ilp32", "-O2", "-fwrapv", "-nostdlib", "-ffreestanding", "-mno-relax", "-I."]
CACHE = Path(tempfile.gettempdir()) / "qick_riscv_build"


@dataclass
class Image:
    data: bytes
    symbols: dict            # name -> (address, size)


def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{cmd[0]} failed:\n{r.stderr}")
    return r.stdout


@functools.lru_cache(maxsize=None)
def tool_version(cc):
    return run([cc, "--version"], None)


def build_image(text, soc_map):
    missing = [n for n, tool in (("riscv64-unknown-elf-clang/gcc", CC), ("riscv64-unknown-elf-objcopy", OBJCOPY),
                                 ("riscv64-unknown-elf-nm", NM)) if tool is None]
    if missing:
        raise RuntimeError(f"{', '.join(missing)} not found on PATH")
    files = {"main.s": text, "riscq_map.h": soc_map.gen_header(), "link.ld": soc_map.gen_linker(),
             **{n: (FW / n).read_text() for n in ("start.S", "muldiv.c", "riscq.h")}}
    version = tool_version(CC)
    d = CACHE / hashlib.sha256(json.dumps([CC, version, FLAGS, files], sort_keys=True).encode()).hexdigest()[:16]
    if not (d / "symbols.json").exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=CACHE, prefix="build-"))
        try:
            for name, content in files.items():
                (tmp / name).write_text(content)
            run([CC, *FLAGS, "-T", "link.ld", "-o", "main.elf", "start.S", "main.s", "muldiv.c"], tmp)
            run([OBJCOPY, "-O", "binary", "main.elf", "main.bin"], tmp)
            (tmp / "symbols.json").write_text(json.dumps(
                {p[-1]: (int(p[0], 16), int(p[1], 16) if len(p) == 4 else 0)
                 for p in (l.split() for l in run([NM, "-S", "main.elf"], tmp).splitlines()) if len(p) in (3, 4)}))
            try:
                os.replace(tmp, d)
            except OSError:
                if not (d / "symbols.json").exists():
                    raise
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    data = (d / "main.bin").read_bytes()
    if len(data) > soc_map.mem_bytes:
        raise RuntimeError(f"image {len(data)} B exceeds RAM {soc_map.mem_bytes} B")
    return Image(data, {k: tuple(v) for k, v in json.loads((d / "symbols.json").read_text()).items()})
