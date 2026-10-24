# Derive a 500 MHz LMK04828 config for the CLK104 (ZCU216) from the board's own 245.76 MHz TICS file.
# Pure computation: nothing is written to the clock chips.
import sys
sys.path.insert(0, "/home/xilinx/jupyter_notebooks/qick/qick_lib/qick/ipq_pynq_utils")
from ipq_pynq_utils.clock_models import LMK04828B

NAMES = ["RF_PLL_ADC_REF", "AMS_SYSREF", "RF_PLL_DAC_REF", "DAC_REFCLK", "PL_CLK", "EXT_REF_OUT", "ADC_REFCLK"]

def show(lmk, tag):
    print(f"--- {tag}: VCO/PLL2 = {lmk.pll2_output_freq:.3f} MHz, SYSREF = {lmk.sysref_freq:.5f} MHz")
    for n, b in zip(NAMES, lmk.clock_branches):
        print(f"  {n:15s} dclk {b.dclk_freq:9.3f} MHz active={b.dclk_active!s:5}  sdclk {b.sdclk_freq:9.5f} active={b.sdclk_active}")

src = sys.argv[1]
lmk = LMK04828B(10, 10, 10, 160)            # CLK104: 10 MHz ref inputs, 160 MHz VCXO
with open(src) as f:
    lmk.init_from_file(f)
lmk.update()
show(lmk, "board file " + src)

print(lmk.set_refclk(3000))                 # VCO1 @ 3000 MHz = 6 x 500
for i in (3, 4, 6):                         # DAC_REFCLK, PL_CLK, ADC_REFCLK -> 500 MHz
    lmk.clock_branches[i].request_freq(500)
lmk.set_sysref(3000 / 384)                  # 7.8125 MHz: divides 500 (PL/DAC fabric/refclk) and 250 (ADC fabric)
show(lmk, "500 MHz plan")
lmk.write_register_dump(sys.argv[2])
