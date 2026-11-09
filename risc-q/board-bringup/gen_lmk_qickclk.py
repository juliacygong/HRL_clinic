# Derive the LMK04828 config (CLK104, ZCU216) for the QICK-clock RISC-Q build
# (software/configs/zcu216-qick-1q-2loop-qickclk*.json) from the 500 MHz one. Pure computation: nothing is
# written to the clock chips. Runs on the board (PYNQ venv) or on a host with the qick repo's ipq_pynq_utils:
#
#   python3 gen_lmk_qickclk.py LMK04828_500.0.txt LMK04828_qickclk_307.2.txt 307.2
#   python3 gen_lmk_qickclk.py LMK04828_500.0.txt LMK04828_qickclk_491.52.txt 491.52
#
# Plan: VCO0 at 2457.6 MHz (= 10 x 245.76), PLL2 R=25 / N=192 / P=2 off the 160 MHz VCXO;
#   DAC_REFCLK, ADC_REFCLK = 245.76 MHz (/10): QICK's RF reference — the RFDC tile-2 PLLs make 9584.64 MS/s
#                            (x 39) for the DACs and 2457.6 MS/s (x 10) or 1966.08 MS/s (x 8) for the ADCs
#   PL_CLK                 = the dsp clock (dspClk): 307.2 MHz (/8, QICK's readout fabric clock) or 491.52 (/5)
#   SYSREF                 = 7.68 MHz (/320): divides 245.76, 307.2, 491.52 and the 599.04 MHz gen fabric clock
# As with LMK04828_500.0.txt the LMX2594s are not used. The stock QICK firmware uses the board's own 245.76 MHz
# TICS file instead; both give the RFDC the same 245.76 MHz reference.
import os
import sys

sys.path.insert(0, os.environ.get("IPQ_PYNQ_UTILS", "/home/xilinx/jupyter_notebooks/qick/qick_lib/qick/ipq_pynq_utils"))
from ipq_pynq_utils.clock_models import LMK04828B

NAMES = ["RF_PLL_ADC_REF", "AMS_SYSREF", "RF_PLL_DAC_REF", "DAC_REFCLK", "PL_CLK", "EXT_REF_OUT", "ADC_REFCLK"]
VCO_MHZ, REF_MHZ, SYSREF_MHZ = 2457.6, 245.76, 7.68


def show(lmk, tag):
    print(f"--- {tag}: VCO/PLL2 = {lmk.pll2_output_freq:.3f} MHz, SYSREF = {lmk.sysref_freq:.5f} MHz")
    for n, b in zip(NAMES, lmk.clock_branches):
        print(f"  {n:15s} dclk {b.dclk_freq:9.3f} MHz active={b.dclk_active!s:5}  sdclk {b.sdclk_freq:9.5f} active={b.sdclk_active}")


src, dst, pl_mhz = sys.argv[1], sys.argv[2], float(sys.argv[3])
lmk = LMK04828B(10, 10, 10, 160)            # CLK104: 10 MHz ref inputs, 160 MHz VCXO
with open(src) as f:
    lmk.init_from_file(f)
lmk.update()
show(lmk, "source " + src)

print("PLL2 R, N, P:", lmk.set_refclk(VCO_MHZ))
for i, mhz in ((3, REF_MHZ), (6, REF_MHZ), (4, pl_mhz)):   # DAC_REFCLK, ADC_REFCLK, PL_CLK
    lmk.clock_branches[i].request_freq(mhz)
lmk.set_sysref(SYSREF_MHZ)
show(lmk, f"QICK-clock plan (PL_CLK {pl_mhz} MHz)")
got = {n: b.dclk_freq for n, b in zip(NAMES, lmk.clock_branches)}
assert abs(got["DAC_REFCLK"] - REF_MHZ) < 1e-6 and abs(got["ADC_REFCLK"] - REF_MHZ) < 1e-6, got
assert abs(got["PL_CLK"] - pl_mhz) < 1e-6, got
# Keep the source file's register set and write order (TICS order: PLL2_N, R360, near the end so the VCO
# calibrates after everything else is set); only patch the values the plan changed.
new = dict(lmk.get_register_dump(with_addr=True))
lines, changed = [], []
with open(src) as f:
    for line in f:
        name, val = line.rstrip("\n").split("\t")
        if name.startswith("R") and " " not in name:
            addr = int(name[1:])
            if addr in new and new[addr] != int(val, 16):
                changed.append(f"{name} {val} -> 0x{new[addr]:06X}")
                val = f"0x{new[addr]:06X}"
        lines.append(f"{name}\t{val}\n")
with open(dst, "w") as f:
    f.writelines(lines)
print(f"wrote {dst}: {len(changed)} registers changed from {src}:", *changed, sep="\n  ")
