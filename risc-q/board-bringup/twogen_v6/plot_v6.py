#!/usr/bin/env python3
"""Full two-train board figure and timing table for the v6-vs-v6 run on DAC 1_228.

    plot_v6.py <riscq_train0.csv> <riscq_train1.csv> <qick_train0_prefix> <qick_train1_prefix> <out.png> <summary.txt>

Delays are pulse centers (half-height midpoints) against the requested times, which do not depend on filter sharpness.
QICK rounds have random carrier phase, so they are averaged as |IQ|, never as I and Q.
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

rq0, rq1, q0, q1, out, summ = sys.argv[1:7]
RQ, TP = "tab:blue", "tab:orange"
plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.color": "#b0b0b0", "grid.linewidth": .8})
TRAINS = [
    dict(title="Generator 0 pulses, 100 MHz", F=100.0, rq=rq0, q=q0, const=(800, 200),
         pulses=[("flat-top", 150, 300), ("Gaussian", 500, 200), ("const", 900, 200), ("flat-top 90", 1350, 300), ("Gaussian 2", 1700, 200)],
         zooms=[("A", 33, "flat-top rise"), ("B", 763, "const start"), ("C", 963, "const end")], legend="upper right"),
    dict(title="Generator 1 pulses, 200 MHz", F=200.0, rq=rq1, q=q1, const=(500, 500),
         pulses=[("const", 750, 500), ("Gaussian", 1600, 200)],
         zooms=[("D", 463, "const start"), ("E", 963, "const end"), ("F", 1563, "Gaussian")], legend="upper right"),
]


def read_rq(path, F):
    _, t, _, runs = read_riscq(path)
    t, runs = t[:4000], runs[:, :4000].astype(float)
    n = int(round(2000 / F)); box = np.convolve(np.ones(n) / n, np.ones(n) / n)
    env = [np.abs(np.convolve(2 * (x - x[:60].mean()) * np.exp(-2j * np.pi * F * t * 1e-3), box, mode="same")) for x in runs]
    return t, np.mean(env, axis=0)


def read_q(prefix):
    env = []
    for f in sorted(glob.glob(f"{prefix}_[0-9]*.csv")):
        d = np.loadtxt(f, delimiter=",", skiprows=1)
        env.append(np.abs(d[:, 1] + 1j * d[:, 2]))
    return d[:, 0] * 1000, np.mean(env, axis=0)


def plateau(t, m, start, length, delay):
    return np.median(m[(t > start + delay + 50) & (t < start + delay + length - 40)])


def first_rise(t, m):
    """coarse delay: the first pulse's rising edge at a quarter of the strongest level"""
    return t[np.argmax(m > .25 * np.percentile(m, 99.5))]


def center(t, m, lo, hi):
    w = (t >= lo) & (t <= hi); tt = t[w]; x = np.clip(m[w] - np.median(m[w][:12]), 0, None)
    h = .5 * x.max(); on = np.where(x > h)[0]; a, b = on[0], on[-1]
    e0 = tt[a - 1] + (h - x[a - 1]) / (x[a] - x[a - 1]) * (tt[a] - tt[a - 1])
    e1 = tt[b] + (h - x[b]) / (x[b + 1] - x[b]) * (tt[b + 1] - tt[b])
    return (e0 + e1) / 2, e1 - e0


lines = []
fig = plt.figure(figsize=(15, 11))
gs = GridSpec(4, 3, height_ratios=[1.4, 1, 1.4, 1], hspace=.52, wspace=.14, left=.055, right=.985, top=.945, bottom=.055)
for row, tr in enumerate(TRAINS):
    F = tr["F"]; t, mr = read_rq(tr["rq"], F); tq, mq = read_q(tr["q"])
    first_req = tr["pulses"][0][1] - tr["pulses"][0][2] / 2
    rough = 76 if row == 0 else 0     # the flat-top's ramp reaches that level 76 ns after it starts
    dr0, dq0 = first_rise(t, mr) - first_req - rough, first_rise(tq, mq) - first_req - rough
    pr, pq = plateau(t, mr, *tr["const"], dr0), plateau(tq, mq, *tr["const"], dq0)
    lines.append(f"{tr['title']}: const level RISC-Q {pr:.1f}, QICK {pq:.1f}, ratio {pr / pq:.2f}")
    rows = []
    for nm, c, L in tr["pulses"]:
        a, af = center(t, mr, c + dr0 - L / 2 - 25, c + dr0 + L / 2 + 25)
        b, bf = center(tq, mq, c + dq0 - L / 2 - 25, c + dq0 + L / 2 + 25)
        rows.append((nm, a - c, b - c, af, bf))
        lines.append(f"  {nm:12s} delay RISC-Q {a - c:7.2f} ns  QICK {b - c:7.2f} ns  difference {b - a:7.2f} ns  width {af:6.1f} / {bf:6.1f} ns")
    con = [r for r in rows if r[0] == "const"]; sha = [r for r in rows if r[0] != "const"]
    gap = lambda i: np.mean([r[i] for r in sha]) - np.mean([r[i] for r in con])
    lines.append(f"  shaped minus const delay: RISC-Q {gap(1):+.2f} ns, QICK {gap(2):+.2f} ns")
    d = np.mean([r[2] - r[1] for r in con])  # aligned on the const pulses
    a = fig.add_subplot(gs[2 * row, :])
    for k, lo, _ in tr["zooms"]:
        x0 = lo + dr0
        a.axvspan(x0 / 1000, (x0 + 80) / 1000, color="0.85", lw=0, zorder=0)
        a.text((x0 + 40) / 1000, 1.15, k, ha="center", va="center", fontsize=10.5, fontweight="bold")
    a.plot(t / 1000, mr / pr, color=RQ, lw=3, label="RISC-Q on axis_signal_gen_v6 (10 runs)")
    a.plot((tq - d) / 1000, mq / pq, color=TP, lw=1.1, label="QICK tProc v2 on axis_signal_gen_v6 (12 rounds)")
    a.set_xlim(0, 2); a.set_ylim(-.05, 1.25); a.set_xticks(np.arange(0, 2.01, .25))
    a.set_title(f"{tr['title']}, on DAC 1_228 (QICK shifted {-d / 1000:+.3f} us)", loc="left", fontsize=12.5)
    a.set_ylabel("|IQ| (normalized to const)"); a.set_xlabel("time in RISC-Q readout window (us)")
    a.legend(loc=tr["legend"], bbox_to_anchor=(.995, .9 if row else .78), framealpha=.9, fontsize=10)
    for j, (k, lo, nm) in enumerate(tr["zooms"]):
        z = fig.add_subplot(gs[2 * row + 1, j]); x0 = lo + dr0
        z.plot(t, mr / pr, color=RQ, lw=3); z.plot(tq - d, mq / pq, color=TP, lw=1.1, marker="o", ms=3)
        z.set_xlim(x0, x0 + 80); z.set_ylim(-.05, 1.15); z.set_title(f"{k}: {nm}", loc="left", fontsize=11); z.set_xlabel("time (ns)")
        if j == 0: z.set_ylabel("|IQ| (normalized)")
        else: z.set_yticklabels([])
fig.suptitle("Two-generator MultiPulseProgram on the ZCU216 board: RISC-Q vs QICK tProc v2, both on signal gen v6", x=.055, y=.99, ha="left", fontsize=14, fontweight="bold")
fig.savefig(out, dpi=170)
text = "\n".join(lines) + "\n"
print(text); Path(summ).write_text(text)
