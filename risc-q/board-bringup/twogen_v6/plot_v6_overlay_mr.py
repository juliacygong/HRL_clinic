#!/usr/bin/env python3
"""Overlay of the v6-vs-v6 board run as raw signals from both designs, with lettered zooms on gray bands.

    plot_v6_overlay_mr.py <riscq_train0.csv> <riscq_train1.csv> <qick_mr_train0_prefix> <qick_mr_train1_prefix> <out.png>

RISC-Q: one run of raw ADC samples (2 GS/s). QICK: one round from its multi-rate (MR) buffer (qick_v6_mr.py), the
readout's full-speed output at the ADC rate (2457.6 MS/s), before any decimation filter. That output is the ADC signal
times the readout's mixer, x e^(-j(wt + psi)), so x is recovered exactly as Re{z e^(j psi)} with z = iq e^(jwt) and psi
the readout mixer's (random) phase, found from z itself. x and -x give the same z, so the sign is taken from RISC-Q.
Both traces then get the same processing: DC offset removed, normalized to the const amplitude, and put on program
time by each design's gen-0 flat-top delay. Nothing else is fitted: carrier phases are as measured.
"""
import glob
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plot_compare import read_riscq

rq0, rq1, q0, q1, out = sys.argv[1:6]
RQ, TP = "tab:blue", "tab:orange"
FS_MR = 2457.6   # MS/s, the readout's full-speed rate (fs, decimation 1)
plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.color": "#b0b0b0", "grid.linewidth": .8})
GENS = [
    dict(title="Generator 0 pulses, 100 MHz", F=100.0, rq=rq0, q=q0, const=(800, 200),
         zooms=[("A", 40, "flat-top rise"), ("B", 770, "const start"), ("C", 970, "const end")]),
    dict(title="Generator 1 pulses, 200 MHz", F=200.0, rq=rq1, q=q1, const=(500, 500),
         zooms=[("D", 470, "const start"), ("E", 970, "const end"), ("F", 1560, "Gaussian")]),
]
W = 60   # zoom width, ns


def env(t, x, f):
    dt = t[1] - t[0]; n = int(round(1000 / f / dt)); box = np.convolve(np.ones(n) / n, np.ones(n) / n)
    return np.abs(np.convolve(2 * x * np.exp(-2j * np.pi * f * t * 1e-3), box, mode="same"))


def dc_free(t, x, f):
    n = 20 * int(round(1000 / f / (t[1] - t[0])))   # 20 carrier periods: slow enough to leave pulse edges alone
    return x - np.convolve(x, np.ones(n) / n, mode="same")


def center(t, m, lo, hi):
    """half-height midpoint, edges interpolated between samples (as plot_v6.py)"""
    w = (t >= lo) & (t <= hi); tt = t[w]; x = np.clip(m[w] - np.median(m[w][:12]), 0, None)
    h = .5 * x.max(); on = np.where(x > h)[0]; a, b = on[0], on[-1]
    e0 = tt[a - 1] + (h - x[a - 1]) / (x[a] - x[a - 1]) * (tt[a] - tt[a - 1])
    e1 = tt[b] + (h - x[b]) / (x[b + 1] - x[b]) * (tt[b + 1] - tt[b])
    return (e0 + e1) / 2


def flat_top_delay(t, m):
    first = t[np.argmax(m > .25 * m.max())] - 76
    return center(t, m, first - 25, first + 325) - 150     # requested center of the first flat-top: 150 ns


def const_start(t, m):
    """half-height rising edge of the const pulse, the only pulse above 3/4 of the maximum"""
    k = np.argmax(m > .75 * m.max()); h = .5 * np.median(m[k + 20:k + 200]); i = k
    while m[i] > h: i -= 1
    return t[i] + (h - m[i]) / (m[i + 1] - m[i]) * (t[i + 1] - t[i])


def spread(v):
    return max(v) - min(v)


def riscq(path, f):
    _, t, _, runs = read_riscq(path)
    xs = [dc_free(t, r.astype(float), f) for r in runs]
    ms = [env(t, x, f) for x in xs]
    return t, xs[0], np.mean(ms, axis=0), spread([const_start(t, m) for m in ms])


def qick_mr(prefix, f):
    """the plotted round is the one whose const start is the median: QICK rounds jitter by a few ns"""
    xs = []
    for p in sorted(glob.glob(f"{prefix}_mr_[0-9]*.csv")):
        d = np.loadtxt(p, delimiter=",", skiprows=1); t = np.arange(len(d)) / FS_MR * 1000
        z = (d[:, 0] + 1j * d[:, 1]) * np.exp(2j * np.pi * f * t * 1e-3)
        psi = -np.angle(np.sum(z ** 2)) / 2               # z = x e^(-j psi) with x real
        x = np.real(z * np.exp(1j * psi))
        resid = np.linalg.norm(np.imag(z * np.exp(1j * psi))) / np.linalg.norm(x)
        xs.append(dc_free(t, x, f))
    print(f"{prefix}: {len(xs)} rounds, last round's leftover imaginary part {resid:.3f} of the signal (0 = exact)")
    ms = [env(t, x, f) for x in xs]; st = [const_start(t, m) for m in ms]
    k = int(np.argmin(np.abs(np.array(st) - np.median(st))))
    print(f"  const start per round (ns): {' '.join(f'{v:.2f}' for v in st)}; plotting round {k}")
    return t, xs[k], np.mean(ms, axis=0), spread(st)


data = [(riscq(g["rq"], g["F"]), qick_mr(g["q"], g["F"])) for g in GENS]
dr, dq = flat_top_delay(data[0][0][0], data[0][0][2]), flat_top_delay(data[0][1][0], data[0][1][2])
jit_r = max(d[0][3] for d in data); jit_q = max(d[1][3] for d in data)

fig = plt.figure(figsize=(15, 11))
gs = GridSpec(4, 3, height_ratios=[1.4, 1, 1.4, 1], hspace=.55, wspace=.14, left=.055, right=.985, top=.87, bottom=.055)
for row, (g, ((t, x, mr, _), (tq, xq, mq, _))) in enumerate(zip(GENS, data)):
    s, L = g["const"]; tr, tp = t - dr, tq - dq
    plat = lambda tt: (tt > s + 50) & (tt < s + L - 40)
    yr, yq = x / np.median(mr[plat(tr)]), xq / np.median(mq[plat(tp)])
    w = plat(tp); sign = np.sign(np.sum(yq[w] * np.interp(tp[w], tr, yr)))   # x vs -x: the one ambiguity in z
    yq = sign * yq
    a = fig.add_subplot(gs[2 * row, :])
    for k, lo, _ in g["zooms"]:
        a.axvspan(lo / 1000, (lo + W) / 1000, color="0.85", lw=0, zorder=0)
        a.text((lo + W / 2) / 1000, 1.17, k, ha="center", va="center", fontsize=10.5, fontweight="bold")
    a.plot(tr / 1000, yr, color=RQ, lw=.9, label="RISC-Q (raw ADC, 2 GS/s, 1 run)")
    a.plot(tp / 1000, yq, color=TP, lw=.6, label="QICK tProc v2 (MR buffer, 2.46 GS/s, median round)")
    a.set_xlim(-.05, 1.9); a.set_ylim(-1.15, 1.3); a.set_xticks(np.arange(0, 1.91, .25))
    a.set_title(f"{g['title']}, on DAC 1_228", loc="left", fontsize=12.5)
    a.set_ylabel("signal (normalized to const)"); a.set_xlabel("program time (us)")
    a.legend(loc="upper right" if row == 0 else "lower center", bbox_to_anchor=None if row == 0 else (.665, 0), framealpha=.95, fontsize=9.5)
    for j, (k, lo, nm) in enumerate(g["zooms"]):
        z = fig.add_subplot(gs[2 * row + 1, j])
        z.plot(tr, yr, color=RQ, lw=2.2, marker="o", ms=2.5); z.plot(tp, yq, color=TP, lw=1.1, marker="o", ms=2)
        z.set_xlim(lo, lo + W); z.set_ylim(-1.15, 1.15); z.set_title(f"{k}: {nm}", loc="left", fontsize=11)
        z.set_xlabel("program time (ns)")
        if j == 0: z.set_ylabel("signal (normalized)")
        else: z.set_yticklabels([])
fig.suptitle("Two-generator MultiPulseProgram on the ZCU216 board: RISC-Q vs QICK tProc v2, raw samples from both, overlaid",
             x=.055, y=.985, ha="left", fontsize=14, fontweight="bold")
fig.text(.055, .955, va="top", s= f"Each capture shifted by its design's measured delay (RISC-Q {dr:.1f} ns, QICK {dq:.1f} ns); no phase fitted. "
         f"QICK: its MR buffer (readout output before decimation), with the readout mixer\nundone. Both DC-offset removed and "
         f"normalized to the const pulse. Gen 0 and gen 1 are separate runs.\n"
         f"Run-to-run jitter of the const start: RISC-Q {jit_r:.2f} ns over 10 runs, QICK {jit_q:.1f} ns over 6 rounds; the QICK round shown is the median one.", fontsize=10, color="0.3")
fig.savefig(out, dpi=170)
print(f"delay RISC-Q {dr:.2f} ns, QICK {dq:.2f} ns -> {out}")
