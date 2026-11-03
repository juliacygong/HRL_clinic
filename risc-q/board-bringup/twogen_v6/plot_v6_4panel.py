#!/usr/bin/env python3
"""Four panels of the v6-vs-v6 board run, laid out like the simulation's twogen_4panel figure: each generator's
signal on the loopback cable, QICK tProc v2 vs RISC-Q, against the program's requested pulse times.

    plot_v6_4panel.py <riscq_train0.csv> <riscq_train1.csv> <qick_train0_prefix> <qick_train1_prefix> <out.png>

RISC-Q is one run of raw ADC samples (2 GS/s). QICK only returns its readout's I/Q (one round, 3.26 ns), so its trace
is rebuilt as Re{(I + jQ) e^(j2 pi f t)} on the RISC-Q time grid. Each trace is normalized to its const pulse's
amplitude. The time axis is program time: each design's capture is shifted by its gen-0 flat-top delay (the same
shift for both generators, so the gen-1 panels keep their measured timing against gen 0).
"""
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plot_compare import read_riscq

rq0, rq1, q0, q1, out = sys.argv[1:6]
RQ, TP = "tab:blue", "tab:orange"
plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.color": "#b0b0b0", "grid.linewidth": .8})
PROG = [[(0, 300, "flat-top"), (400, 200, "Gaussian"), (800, 200, "const"), (1200, 300, "flat-top 90°"), (1600, 200, "Gaussian")],
        [(500, 500, "const"), (1500, 200, "Gaussian")]]     # requested start ns, length ns, name
CONST = [(800, 200), (500, 500)]
F = [100.0, 200.0]


def env(t, x, f):
    n = int(round(2000 / f)); box = np.convolve(np.ones(n) / n, np.ones(n) / n)
    return np.abs(np.convolve(2 * x * np.exp(-2j * np.pi * f * t * 1e-3), box, mode="same"))


def center(t, m, lo, hi):
    """half-height midpoint of the pulse between lo and hi"""
    w = (t >= lo) & (t <= hi); tt = t[w]; x = m[w] - np.median(m[w][:12])
    on = np.where(x > .5 * x.max())[0]
    return (tt[on[0]] + tt[on[-1]]) / 2


def riscq(path, f):
    """one run; a moving average over two carrier periods (which cancels the carrier) removes the ADC's DC offset
    and slow drift, which QICK's demodulator removes too"""
    _, t, _, runs = read_riscq(path)
    x = runs[0].astype(float); n = int(round(2000 / f))
    x = x - np.convolve(x, np.ones(n) / n, mode="same")
    return t, x, env(t, x, f)


def qick(prefix, f):
    """round 0 rebuilt on a 0.5 ns grid; the mean |IQ| of all rounds sets the delay"""
    d = np.loadtxt(f"{prefix}_0.csv", delimiter=",", skiprows=1)
    tq = d[:, 0] * 1000; t = np.arange(tq[0], tq[-1], .5)
    iq = np.interp(t, tq, d[:, 1]) + 1j * np.interp(t, tq, d[:, 2])
    m = np.mean([np.abs(e[:, 1] + 1j * e[:, 2]) for e in
                 (np.loadtxt(f"{prefix}_{k}.csv", delimiter=",", skiprows=1) for k in range(12))], axis=0)
    return t, np.real(iq * np.exp(2j * np.pi * f * t * 1e-3)), np.abs(iq), tq, m


traces = {}
for g, (rp, qp) in enumerate(((rq0, q0), (rq1, q1))):
    traces[g] = (riscq(rp, F[g]), qick(qp, F[g]))
# program time = capture time - delay, with one delay per design from its gen-0 flat-top (requested center 150 ns)
(t, xr, mr), (_, _, _, tq, mq) = traces[0]
first = t[np.argmax(mr > .25 * mr.max())] - 76
dr = center(t, mr, first - 25, first + 325) - 150
first = tq[np.argmax(mq > .25 * mq.max())] - 76
dq = center(tq, mq, first - 25, first + 325) - 150

fig, ax = plt.subplots(2, 2, figsize=(15, 7.2), sharex=True, sharey=True)
for j, (name, col, delay, k) in enumerate((("QICK tProc v2", TP, dq, 1), ("RISC-Q", RQ, dr, 0))):
    for g in (0, 1):
        a = ax[g, j]; tt, x, m = traces[g][k][:3]; tp = tt - delay
        s, L = CONST[g]
        amp = np.median(m[(tp > s + 50) & (tp < s + L - 40)])
        for p0, pl, nm in PROG[g]:
            a.axvline(p0 / 1000, color="0.25", lw=.9, ls=(0, (3, 3)), zorder=3)
            a.text(p0 / 1000 + .012, 1.17, nm, fontsize=9.5, color="0.25", va="center")
        a.plot(tp / 1000, x / amp, color=col, lw=.5, zorder=2)
        a.set_title(f"{name}, generator {g} ({F[g]:.0f} MHz)", loc="left", fontsize=12.5, fontweight="bold")
        a.set_xlim(-.03, 1.9); a.set_ylim(-1.15, 1.3); a.set_yticks([-1, 0, 1])
    ax[1, j].set_xlabel("program time (µs), from generator 0's first requested pulse")
for g in (0, 1): ax[g, 0].set_ylabel("signal (normalized to const)")
fig.suptitle("Two-generator MultiPulseProgram on the ZCU216 board, both designs on signal gen v6 (DAC 1_228 → ADC 0_226)",
             x=.012, y=.985, ha="left", fontsize=14, fontweight="bold")
fig.text(.012, .905, f"Dashed lines are the program's requested pulse times. Each capture is shifted by its design's measured delay "
         f"(RISC-Q {dr:.1f} ns, QICK {dq:.1f} ns).\nRISC-Q: one run of raw ADC samples, DC offset removed. QICK: one round, rebuilt from its "
         f"readout I/Q (QICK does not return raw samples). Gen 0 and gen 1 are separate runs.", fontsize=10.5, color="0.3")
fig.tight_layout(rect=(0, 0, 1, .88)); fig.savefig(out, dpi=170)
print(f"delay RISC-Q {dr:.2f} ns, QICK {dq:.2f} ns -> {out}")
