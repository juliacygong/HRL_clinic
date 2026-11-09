"""Simulated DAC output of the 32-slot design (QickCpuSim, 8 GS/s gen samples) + tProc v2 board captures.
    plot_sim.py <scratch pu dir> <out dir>"""
import csv
import glob
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

S, OUT = Path(sys.argv[1]), Path(sys.argv[2])
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE = "#2a78d6", "#eb6834"
plt.rcParams.update({"figure.facecolor": SURF, "axes.facecolor": SURF, "axes.edgecolor": INK2,
                     "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
                     "font.size": 9.5, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6})
FS_DAC = 8e9


def dac(path, c0=None):
    """Gen samples on a continuous 8 GS/s timeline (idle cycles are zero). Returns t_ns, samples. With `c0` (a gen
    cycle), time 0 is that cycle instead of this file's first pulse (to line two gens up)."""
    rows = [[int(x) for x in r] for r in list(csv.reader(open(path)))[1:]]
    if not rows:
        return np.zeros(0), np.zeros(0)
    a = np.array(rows)
    lo, c1 = a[:, 0].min(), a[:, 0].max()
    x = np.zeros((c1 - lo + 1) * 16)
    for r in a:
        k = (r[0] - lo) * 16
        x[k:k + 16] = r[1:]
    t = np.arange(len(x)) / FS_DAC * 1e9 + lo * 2.0          # absolute ns (2 ns per gen cycle)
    zero = (c0 * 2.0) if c0 is not None else t[np.flatnonzero(x)[0]]
    keep = t >= zero - 20
    return t[keep] - zero, x[keep]


def first_cycle(path):
    rows = [[int(x) for x in r] for r in list(csv.reader(open(path)))[1:]]
    return min(r[0] for r in rows if any(r[1:]))


def envelope(x, f_hz, smooth_ns=5.0):
    """What a QICK readout sees: mix down at the carrier, then a ~smooth_ns boxcar (the MR path's bandwidth)."""
    n = np.arange(len(x))
    bb = x * np.exp(-2j * np.pi * f_hz / FS_DAC * n)
    k = max(1, int(smooth_ns * 1e-9 * FS_DAC))
    return np.abs(np.convolve(bb, np.ones(k) / k, "same")) * 2


# ── figure 1: the demos at the default 1 us initial delay ──
fig, axes = plt.subplots(4, 1, figsize=(11, 9.2))
for ax, name, color, title in (
        (axes[0], "old_pu", ORANGE, "PulseUpdateProgram, previous code generation: shot 2 cannot keep up, pulses land late and cut short"),
        (axes[1], "new_pu", BLUE, "PulseUpdateProgram, new code generation: 4 pulses every 200 ns in both shots, on time")):
    t, x = dac(S / "data" / "riscq_sim" / name / "dac_out_ch0.csv")
    ax.plot(t, x / 1000, color=color, lw=0.35)
    ax.set_title(title, loc="left", fontsize=10)
    ax.set_ylabel("DAC (k counts)")
    ax.set_xlim(-20, 2300)
for ax, ch, color, title in (
        (axes[2], 0, BLUE, "Stress program, gen 0: 30 Gaussians every 50 ns, gain ramp in 8 steps, +45° phase per pulse"),
        (axes[3], 1, ORANGE, "Stress program, gen 1 at the same time: 15 pulses every 100 ns, carrier 100/200/300/400 MHz")):
    t, x = dac(S / "data" / "riscq_sim" / "stress" / f"dac_out_ch{ch}.csv", c0=first_cycle(S / "data" / "riscq_sim" / "stress" / "dac_out_ch0.csv"))
    keep = t < 1600
    ax.plot(t[keep], x[keep] / 1000, color=color, lw=0.35)
    ax.set_title(title, loc="left", fontsize=10)
    ax.set_ylabel("DAC (k counts)")
    ax.set_xlim(-20, 1600)
axes[1].set_xlabel("time from the first pulse (ns)")
axes[3].set_xlabel("time from gen 0's first pulse (ns), first shot of 3")
fig.suptitle("Simulated DAC output of the new design (CPU running the compiled program, 32-slot RTL), 1 µs initial delay",
             x=0.01, ha="left", fontsize=12)
fig.text(0.01, 0.004, "QickCpuSim: RISC-V core, pulse tables, WaveWordBridge, axis_cdcsync, sg_translator, axis_signal_gen_v6 "
         "(QICK emulator models), 8 GS/s. Late flag set only for the previous code generation.", fontsize=8, color=INK2)
fig.tight_layout(rect=(0, 0.02, 1, 0.97))
fig.savefig(OUT / "sim_waveforms_demos.png", dpi=160)
print("wrote", OUT / "sim_waveforms_demos.png")

# ── figure 2: issue-rate tests, RISC-Q (sim) vs tProc v2 (board, same programs) ──
FS_MR = 2457.6e6
def mr_env(f):
    a = np.loadtxt(f, delimiter=",", skiprows=1)
    e = np.abs(np.convolve(a[:, 0] + 1j * a[:, 1], np.ones(3) / 3, "same"))
    idx = np.flatnonzero(e > 0.15 * e.max())
    e = e[max(idx[0] - 50, 0):]
    return np.arange(len(e)) / FS_MR * 1e9 - (min(idx[0], 50) / FS_MR * 1e9), e / e.max()

rows = (("rate", "q_same_mr_0.csv", "40 back-to-back pulses (gain alternating 1.0 / 0.4)", 40, "pulse"),
        ("sweep", "q_sweep_mr_0.csv", "40-step gain sweep loop", 40, "iteration"),
        ("virtz", "v_virtz_mr_0.csv", "40 × (short flat-top + virt_z)", 40, "iteration"))
fig, axes = plt.subplots(3, 1, figsize=(11, 8.4))
for ax, (name, qf, title, n, unit) in zip(axes, rows):
    t, x = dac(S / "data" / "riscq_sim" / name / "dac_out_ch0.csv")
    e = envelope(x, 100e6); e /= e.max()
    tq, eq = mr_env(S / "data" / "tproc_board" / qf)
    on_r = t[np.flatnonzero(e > 0.15)]; on_q = tq[np.flatnonzero(eq > 0.15)]
    span_r, span_q = on_r[-1] - on_r[0], on_q[-1] - on_q[0]
    ax.plot(t, e + 1.25, color=BLUE, lw=0.9)
    ax.plot(tq, eq, color=ORANGE, lw=0.9)
    ax.set_yticks([0.5, 1.75]); ax.set_yticklabels(["tProc v2\n(board)", "RISC-Q\n(sim)"])
    ax.set_ylim(-0.1, 2.45)
    ax.set_xlim(-20, max(span_q, span_r) * 1.05 + 20)
    ax.set_title(title, loc="left", fontsize=10)
    ax.text(span_r + 8, 1.75, f"{span_r:.0f} ns: {span_r / n:.1f} ns per {unit}", color=INK, fontsize=9, va="center")
    ax.text(span_q + 8, 0.5, f"{span_q:.0f} ns: {span_q / n:.1f} ns per {unit}", color=INK, fontsize=9, va="center")
axes[-1].set_xlabel("time from the first pulse (ns)")
fig.suptitle("Same programs, all started late, so the train length is each processor's issue rate (normalized envelopes)",
             x=0.01, ha="left", fontsize=12)
fig.text(0.01, 0.004, "RISC-Q: QickCpuSim of the 32-slot design (8 GS/s, mixed down at 100 MHz, 5 ns smoothing). "
         "tProc v2: stock QICK firmware on the ZCU216, DAC 3_228 -> ADC 2_226, MR buffer at 2.4576 GS/s.",
         fontsize=8, color=INK2)
fig.tight_layout(rect=(0, 0.02, 1, 0.97))
fig.savefig(OUT / "sim_vs_tproc_issue_rate.png", dpi=160)
print("wrote", OUT / "sim_vs_tproc_issue_rate.png")
