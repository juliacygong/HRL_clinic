#!/usr/bin/env python3
"""Overlay of the v6-vs-v6 board run as signals (carrier included), with lettered zooms on gray bands.

    plot_v6_overlay.py <riscq_train0.csv> <riscq_train1.csv> <qick_train0_prefix> <qick_train1_prefix> <out.png>

RISC-Q is one run of raw ADC samples (2 GS/s), DC offset removed. QICK only returns its readout's I/Q, so its trace is
one round rebuilt as Re{(I + jQ) e^(j2 pi f t)}. QICK rounds have a random carrier phase, so each QICK trace gets one
constant phase rotation that matches RISC-Q over the const pulse; nothing else is fitted. Each trace is normalized to
its const amplitude and put on program time by its design's gen-0 flat-top delay (one shift per design).
"""
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
plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.color": "#b0b0b0", "grid.linewidth": .8})
GENS = [
    dict(title="Generator 0 pulses, 100 MHz", F=100.0, rq=rq0, q=q0, const=(800, 200),
         zooms=[("A", 40, "flat-top rise"), ("B", 770, "const start"), ("C", 970, "const end")]),
    dict(title="Generator 1 pulses, 200 MHz", F=200.0, rq=rq1, q=q1, const=(500, 500),
         zooms=[("D", 470, "const start"), ("E", 970, "const end"), ("F", 1560, "Gaussian")]),
]
W = 60   # zoom width, ns


def env(t, x, f):
    n = int(round(2000 / f)); box = np.convolve(np.ones(n) / n, np.ones(n) / n)
    return np.convolve(2 * x * np.exp(-2j * np.pi * f * t * 1e-3), box, mode="same")


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


def riscq(path, f):
    _, t, _, runs = read_riscq(path)
    x = runs[0].astype(float); n = 20 * int(round(2000 / f))   # 20 carrier periods: slow enough to leave pulse edges alone
    x = x - np.convolve(x, np.ones(n) / n, mode="same")
    return t, x, env(t, x, f)


def qick(prefix, f):
    rounds = [np.loadtxt(f"{prefix}_{k}.csv", delimiter=",", skiprows=1) for k in range(12)]
    d = rounds[0]; tq = d[:, 0] * 1000; t = np.arange(tq[0], tq[-1], .5)
    iq = np.interp(t, tq, d[:, 1]) + 1j * np.interp(t, tq, d[:, 2])
    return t, iq, tq, np.mean([np.abs(e[:, 1] + 1j * e[:, 2]) for e in rounds], axis=0)


data = [(riscq(g["rq"], g["F"]), qick(g["q"], g["F"])) for g in GENS]
(t, _, zr), (_, _, tq, mq) = data[0]
dr, dq = flat_top_delay(t, np.abs(zr)), flat_top_delay(tq, mq)

fig = plt.figure(figsize=(15, 11))
gs = GridSpec(4, 3, height_ratios=[1.4, 1, 1.4, 1], hspace=.55, wspace=.14, left=.055, right=.985, top=.9, bottom=.055)
for row, (g, ((t, x, zr), (tqf, iq, _, _))) in enumerate(zip(GENS, data)):
    F = g["F"]; s, L = g["const"]
    tr, tp = t - dr, tqf - dq
    pr, pq = (lambda tt: (tt > s + 50) & (tt < s + L - 40))(tr), (lambda tt: (tt > s + 50) & (tt < s + L - 40))(tp)
    ar, aq = np.median(np.abs(zr[pr])), np.median(np.abs(iq[pq]))
    # QICK's I/Q carries its own carrier phase: one rotation so its const pulse matches RISC-Q's
    # (baseband on program time: x = Re{zr e^(jw dr) e^(jw tr)}, and the same for QICK with dq)
    rot = np.mean(zr[pr]) * np.exp(2j * np.pi * F * dr * 1e-3) / (np.mean(iq[pq]) * np.exp(2j * np.pi * F * dq * 1e-3))
    yq = np.real(iq * rot / abs(rot) * np.exp(2j * np.pi * F * tqf * 1e-3)) / aq
    yr = x / ar
    a = fig.add_subplot(gs[2 * row, :])
    for k, lo, _ in g["zooms"]:
        a.axvspan(lo / 1000, (lo + W) / 1000, color="0.85", lw=0, zorder=0)
        a.text((lo + W / 2) / 1000, 1.17, k, ha="center", va="center", fontsize=10.5, fontweight="bold")
    a.plot(tr / 1000, yr, color=RQ, lw=.9, label="RISC-Q (raw ADC, 1 run)")
    a.plot(tp / 1000, yq, color=TP, lw=.6, label="QICK tProc v2 (from readout I/Q, 1 round)")
    a.set_xlim(-.05, 1.9); a.set_ylim(-1.15, 1.3); a.set_xticks(np.arange(0, 1.91, .25))
    a.set_title(f"{g['title']}, on DAC 1_228", loc="left", fontsize=12.5)
    a.set_ylabel("signal (normalized to const)"); a.set_xlabel("program time (us)")
    a.legend(loc="upper right" if row == 0 else "lower center", bbox_to_anchor=None if row == 0 else (.665, 0), framealpha=.95, fontsize=9.5)
    for j, (k, lo, nm) in enumerate(g["zooms"]):
        z = fig.add_subplot(gs[2 * row + 1, j])
        z.plot(tr, yr, color=RQ, lw=2.2); z.plot(tp, yq, color=TP, lw=1.1)
        z.set_xlim(lo, lo + W); z.set_ylim(-1.15, 1.15); z.set_title(f"{k}: {nm}", loc="left", fontsize=11)
        z.set_xlabel("program time (ns)")
        if j == 0: z.set_ylabel("signal (normalized)")
        else: z.set_yticklabels([])
fig.suptitle("Two-generator MultiPulseProgram on the ZCU216 board: RISC-Q vs QICK tProc v2 overlaid, both on signal gen v6",
             x=.055, y=.985, ha="left", fontsize=14, fontweight="bold")
fig.text(.055, .935, f"Each capture shifted by its design's measured delay (RISC-Q {dr:.1f} ns, QICK {dq:.1f} ns). QICK does not return "
         f"raw samples: its trace is rebuilt from readout I/Q,\nwith one phase rotation per generator to match RISC-Q on the const pulse "
         f"(QICK's carrier phase is random per round). Gen 0 and gen 1 are separate runs.", fontsize=10, color="0.3")
fig.savefig(out, dpi=170)
print(f"delay RISC-Q {dr:.2f} ns, QICK {dq:.2f} ns -> {out}")
