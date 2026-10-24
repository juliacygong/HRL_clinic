"""Give a compiled program's readout (demod channel, RF_CH2) a window length, and reassemble it.

The RISC-V backend translates QICK's trigger(ros=...) into a demod-channel fire (startTime, then fire slot 0)
but drops declare_readout's length: slot 0's dur is never written, so the demod carrier's scheduled window
[startTime, startTime + dur) is empty and nothing is captured. This inserts, after the program's existing
RF_CH2 setup, one store of slot 0's dur (RF_CH2 + 0x10 + 0xC, value seated in data[31:16] like every
compiled slot field), then rebuilds the ELF with the compiler's own toolchain (qick.riscv_toolchain).

    patch_readout_len.py <prog.s> <ro_len_us> <outdir>     (env as for compile_mpp.py)
"""
import re
import sys
from pathlib import Path

from qick.riscv import _socmap, DEFAULT_SOC
from qick.riscv_toolchain import build_image

src, ro_len_us, out = Path(sys.argv[1]), float(sys.argv[2]), Path(sys.argv[3])
DSP_MHZ = 500.0
dur = int(round(ro_len_us * DSP_MHZ))
if not 0 < dur < 1 << 16:
    raise SystemExit(f"dur {dur} cycles does not fit the 16-bit slot field")

text = src.read_text()
anchor = re.compile(r"^(\s*)li t1, RF_CH2\n(?:\s*sw \w+, \d+\(t1\)\n)+", re.M)
m = anchor.search(text)
if not m:
    raise SystemExit("no RF_CH2 setup block found to patch after")
ind = m.group(1)
patch = (f"{ind}li t2, {dur << 16}    # PATCH readout window: RF_CH2 slot 0 dur = {dur} cycles ({ro_len_us} us)\n"
         f"{ind}sw t2, 28(t1)\n")
text = text[:m.end()] + patch + text[m.end():]

out.mkdir(parents=True, exist_ok=True)
img = build_image(text, _socmap(DEFAULT_SOC))
(out / src.name).write_text(text)
(out / src.with_suffix(".elf").name).write_bytes(img.elf)
(out / src.with_suffix(".bin").name).write_bytes(img.data)
print(f"patched {src.name}: RF_CH2 slot 0 dur = {dur} cycles -> {out} ({len(img.data)} B image)")
