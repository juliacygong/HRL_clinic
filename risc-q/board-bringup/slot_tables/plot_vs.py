"""Board vs board: RISC-Q (32-slot staged-shim bitstream) vs tProc v2, same programs, all started late.
    plot_vs.py <out dir> [run index]"""
import sys, glob
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
from analyze import load
OUT = Path(sys.argv[1]); RUN = int(sys.argv[2]) if len(sys.argv) > 2 else 0
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE = "#2a78d6", "#eb6834"
plt.rcParams.update({"figure.facecolor": SURF, "axes.facecolor": SURF, "axes.edgecolor": INK2,
                     "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
                     "font.size": 9.5, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6})
FS_R, FS_Q = 2e9, 2457.6e6
def riscq(name):
    t, R = load(f"data/riscq_board/{name}_adc2.csv"); x = R[:, RUN]; x = x - np.median(x[x != 0])
    n = np.arange(len(x)); e = np.abs(np.convolve(x * np.exp(-2j*np.pi*100e6/FS_R*n), np.ones(10)/10, "same"))
    return t, e / e.max()
def tproc(f):
    a = np.loadtxt(f, delimiter=",", skiprows=1); e = np.abs(np.convolve(a[:, 0] + 1j*a[:, 1], np.ones(3)/3, "same"))
    return np.arange(len(e)) / FS_Q * 1e9, e / e.max()
def first(t, e): return t[np.flatnonzero(e > 0.15)[0]]
def onsets(t, e):
    on = e > 0.3; return t[1:][np.diff(on.astype(int)) == 1]
rows = (("rate", "q_same_mr", "40 back-to-back 6 ns pulses (gain alternating 1.0 / 0.4)", "pulse"),
        ("sweep", "q_sweep_mr", "40-step gain sweep loop, one pulse per iteration", "iteration"),
        ("virtz", "v_virtz_mr", "40 × (short flat-top + virt_z subroutine)", "iteration"))
fig, axes = plt.subplots(3, 1, figsize=(11, 8.4))
for ax, (name, qf, title, unit) in zip(axes, rows):
    t, e = riscq(name); t0 = first(t, e); t = t - t0
    tq, eq = tproc(f"data/tproc_board/{qf}_{min(RUN, 4)}.csv"); tq = tq - first(tq, eq)
    on_r = t[e > 0.15]; on_q = tq[eq > 0.15]
    span_q = on_q[-1]
    truncated = t[-1] - on_r[-1] < 60
    ax.plot(t, e + 1.25, color=BLUE, lw=0.9); ax.plot(tq, eq, color=ORANGE, lw=0.9)
    ax.set_yticks([0.5, 1.75]); ax.set_yticklabels(["tProc v2", "RISC-Q"]); ax.set_ylim(-0.1, 2.45)
    ax.set_xlim(-20, span_q * 1.25 + 20); ax.set_title(title, loc="left", fontsize=10)
    if truncated:
        o = onsets(t, e); per = (o[-1] - o[0]) / (len(o) - 1)
        lab = f"{per:.1f} ns per {unit}\n(train runs past the 2 µs capture;\nspacing of the {len(o)} pulses seen)"
        ax.text(t[-1] + 15, 1.75, lab, color=INK, fontsize=9, va="center")
    else:
        ax.text(on_r[-1] + 8, 1.75, f"{on_r[-1]:.0f} ns: {on_r[-1]/40:.1f} ns per {unit}", fontsize=9, va="center")
    ax.text(span_q + 8, 0.5, f"{span_q:.0f} ns: {span_q/40:.1f} ns per {unit}", fontsize=9, va="center")
axes[-1].set_xlabel("time from the first pulse (ns)")
fig.suptitle(f"Both on the ZCU216: same programs, started late, so the train length is the issue rate (run {RUN+1}, no averaging)",
             x=0.01, ha="left", fontsize=12)
fig.text(0.01, 0.004, "RISC-Q: 32-slot bitstream (WNS +0.015 ns), DAC 3_228 -> ADC 2_226 at 2 GS/s, mixed down at 100 MHz. "
         "tProc v2: stock QICK firmware, same cable, MR buffer at 2.4576 GS/s. Normalized envelopes.", fontsize=8, color=INK2)
fig.tight_layout(rect=(0, 0.02, 1, 0.97))
fig.savefig(OUT / "board_vs_tproc_issue_rate.png", dpi=160); print("wrote", OUT / "board_vs_tproc_issue_rate.png")
