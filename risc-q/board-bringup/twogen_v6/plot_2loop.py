#!/usr/bin/env python3
"""Figures for the one-run, two-cable board test (run_2loop.sh): RISC-Q vs QICK tProc v2, both generators in every run.

    plot_2loop.py <data_2loop dir> <overlay.png>

Wiring: gen 0 (100 MHz) on DAC 3_228 -> ADC 2_226, gen 1 (200 MHz) on DAC 1_228 -> ADC 0_226. Each design runs the
RISC-Q runs the program 40 times and records both ADCs in every run. QICK's single raw (MR) buffer records one ADC per run,
alternating (even runs ADC 0_226, odd runs ADC 2_226), so QICK runs it 80 times: 40 raw captures per ADC for both designs.

Raw signals: RISC-Q records raw ADC samples (2 GS/s). QICK's MR buffer holds its readout's full-rate output (2457.6 MS/s,
before any decimation filter): the ADC signal times the readout mixer, x e^(-j(wt + psi)). x is recovered exactly as
Re{z e^(j psi)} with z = iq e^(jwt) and psi found from z itself; x vs -x is the one ambiguity, so each QICK run takes the
sign of the first. Both designs then get the same processing: DC offset removed, normalized to the const pulse, and put
on program time by their gen-0 flat-top delay (one shift per design, used for both generators).

Overlay: one line per design per ADC, the average of all that design's runs, RISC-Q and QICK on top of each other. Each
run is first shifted onto its own const start (exact FFT fractional delay): QICK's runs move by a few ns, which at
100-200 MHz would otherwise cancel most of its carrier in the average. That run-to-run spread is in the caption. Each
design then gets one time shift (its gen-0 flat-top delay) and one amplitude scale (its const pulse).
Printed summary, from the same runs: per pulse, timing against the requested time, width, amplitude against the const
pulse and carrier phase against the generator's first pulse; plus gen 1 against gen 0 within each run (all 40 runs:
RISC-Q from its two raw captures, QICK from its two decimated readouts, which both record every run).
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

D, out = sys.argv[1:3]
NRUNS = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9   # optional: plot only the first N runs per ADC
runs = lambda n: "1 run" if n == 1 else f"average of {n} runs"
RQ, TP = "tab:blue", "tab:orange"
FS_MR = 2457.6   # MS/s, QICK readout's full rate (fs, decimation 1)
plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.color": "#b0b0b0", "grid.linewidth": .8})
# requested pulses: (name, start ns, length ns, phase deg); rq / q = RISC-Q ADC capture, QICK MR readout
GENS = [
    dict(title="Generator 0 pulses, 100 MHz, DAC 3_228 -> ADC 2_226", F=100.0, rq="adc2", q=1, const=(800, 200),
         pulses=[("flat-top", 0, 300, 0), ("Gaussian", 400, 200, 0), ("const", 800, 200, 0), ("flat-top 90°", 1200, 300, 90), ("Gaussian 2", 1600, 200, 0)],
         zooms=[("A", 40, "flat-top rise"), ("B", 770, "const start"), ("C", 970, "const end")]),
    dict(title="Generator 1 pulses, 200 MHz, DAC 1_228 -> ADC 0_226", F=200.0, rq="adc0", q=0, const=(500, 500),
         pulses=[("const", 500, 500, 0), ("Gaussian", 1500, 200, 0)],
         zooms=[("D", 470, "const start"), ("E", 970, "const end"), ("F", 1560, "Gaussian")]),
]
W = 60   # zoom width, ns


def bb(t, x, f):
    """complex baseband (amplitude, phase), low-passed over one carrier period twice"""
    n = int(round(1000 / f / (t[1] - t[0]))); box = np.convolve(np.ones(n) / n, np.ones(n) / n)
    return np.convolve(2 * x * np.exp(-2j * np.pi * f * t * 1e-3), box, mode="same")


def env(t, x, f):
    return np.abs(bb(t, x, f))


def dc_free(t, x, f):
    n = 20 * int(round(1000 / f / (t[1] - t[0])))   # 20 carrier periods: slow enough to leave pulse edges alone
    return x - np.convolve(x, np.ones(n) / n, mode="same")


def edges(t, m, lo, hi):
    """half-height rising and falling edges of the pulse between lo and hi, interpolated between samples"""
    w = (t >= lo) & (t <= hi); tt = t[w]; x = np.clip(m[w] - np.median(m[w][:12]), 0, None)
    h = .5 * x.max(); on = np.where(x > h)[0]; a, b = on[0], on[-1]
    e0 = tt[a - 1] + (h - x[a - 1]) / (x[a] - x[a - 1]) * (tt[a] - tt[a - 1])
    e1 = tt[b] + (h - x[b]) / (x[b + 1] - x[b]) * (tt[b + 1] - tt[b])
    return e0, e1, x.max()


def flat_top_delay(t, m):
    first = t[np.argmax(m > .25 * m.max())] - 76
    e0, e1, _ = edges(t, m, first - 25, first + 325)
    return (e0 + e1) / 2 - 150     # requested center of the first flat-top: 150 ns


def const_start(t, m):
    """half-height rising edge of the const pulse, the only pulse above 3/4 of the maximum"""
    k = np.argmax(m > .75 * m.max()); h = .5 * np.median(m[k + 20:k + 200]); i = k
    while m[i] > h: i -= 1
    return t[i] + (h - m[i]) / (m[i + 1] - m[i]) * (t[i + 1] - t[i])


def riscq_runs(name, f):
    _, t, _, runs = read_riscq(f"{D}/riscq_2loop_{name}.csv")
    return t, [dc_free(t, r.astype(float), f) for r in runs]


def shift(x, dt, s):
    """x delayed by s ns (fractional, via the FFT)"""
    k = np.fft.rfftfreq(len(x), dt)
    return np.fft.irfft(np.fft.rfft(x) * np.exp(-2j * np.pi * k * s), len(x))


def average(t, xs, f):
    """runs shifted onto their own const start, then averaged; returns it and the const-start spread across runs"""
    st = np.array([const_start(t, env(t, x, f)) for x in xs])
    al = [shift(x, t[1] - t[0], st.mean() - s) for x, s in zip(xs, st)]
    al = [a * np.sign(np.dot(a, al[0])) for a in al]
    return np.mean(al, axis=0), np.ptp(st)


def qick_runs(ro, f):
    xs = []
    for k in range(len(glob.glob(f"{D}/qick_2loop_mr{ro}_[0-9]*.csv"))):
        d = np.loadtxt(f"{D}/qick_2loop_mr{ro}_{k}.csv", delimiter=",", skiprows=1); t = np.arange(len(d)) / FS_MR * 1000
        z = (d[:, 0] + 1j * d[:, 1]) * np.exp(2j * np.pi * f * t * 1e-3)
        x = np.real(z * np.exp(-1j * np.angle(np.sum(z ** 2)) / 2))   # z = x e^(-j psi), x real
        xs.append(dc_free(t, x, f))
    xs = [x * np.sign(np.dot(x, xs[0])) for x in xs]                   # one sign for all runs
    return t, xs


def per_pulse(t, x, f, g, delay):
    """one run: for each requested pulse, (timing error, width error, amplitude / const, phase deg) on program time"""
    tp = t - delay; z = bb(tp, x, f); m = np.abs(z)
    s, L = g["const"]; cw = (tp > s + 50) & (tp < s + L - 40); amp_c = np.median(m[cw])
    out = []
    for nm, s0, L0, ph in g["pulses"]:
        e0, e1, pk = edges(tp, m, s0 - 30, s0 + L0 + 30)
        c = (e0 + e1) / 2; i = np.argmin(np.abs(tp - c))
        out.append((c - (s0 + L0 / 2), (e1 - e0), pk / amp_c, np.degrees(np.angle(z[i]))))
    out = np.array(out); out[:, 3] = (out[:, 3] - out[0, 3] + 180) % 360 - 180   # phase against the first pulse
    return out


# ---- data: all runs per ADC ----
R = [riscq_runs(g["rq"], g["F"]) for g in GENS]
Q = [qick_runs(g["q"], g["F"]) for g in GENS]
nR, nQ = [len(r[1]) for r in R], [len(q[1]) for q in Q]
avR = [average(t, xs, g["F"]) for (t, xs), g in zip(R, GENS)]
avQ = [average(t, xs, g["F"]) for (t, xs), g in zip(Q, GENS)]
envR = [env(R[i][0], avR[i][0], g["F"]) for i, g in enumerate(GENS)]
envQ = [env(Q[i][0], avQ[i][0], g["F"]) for i, g in enumerate(GENS)]
dr, dq = flat_top_delay(R[0][0], envR[0]), flat_top_delay(Q[0][0], envQ[0])
assert nR == nQ, f"runs per ADC differ: RISC-Q {nR}, QICK {nQ}"
NALL = nR[0]
if NRUNS < NALL:   # plot only the first NRUNS runs (unaligned when 1), still placed by the delay measured over all runs
    R = [(t, xs[:NRUNS]) for t, xs in R]; Q = [(t, xs[:NRUNS]) for t, xs in Q]
    nR, nQ = [NRUNS] * 2, [NRUNS] * 2
    avR = [average(t, xs, g["F"]) for (t, xs), g in zip(R, GENS)]
    avQ = [average(t, xs, g["F"]) for (t, xs), g in zip(Q, GENS)]
    envR = [env(R[i][0], avR[i][0], g["F"]) for i, g in enumerate(GENS)]
    envQ = [env(Q[i][0], avQ[i][0], g["F"]) for i, g in enumerate(GENS)]
lines = [f"runs averaged per ADC: {nR[0]} for both designs (QICK ran twice as many times: its raw buffer records one ADC per run)",
         f"delay from requested time to capture: RISC-Q {dr:.2f} ns, QICK {dq:.2f} ns (each design's own capture window)"]

# ---- overlay: one average per design per ADC ----
fig = plt.figure(figsize=(15, 11))
gs = GridSpec(4, 3, height_ratios=[1.4, 1, 1.4, 1], hspace=.55, wspace=.14, left=.055, right=.985, top=.87, bottom=.055)
for row, g in enumerate(GENS):
    s, L = g["const"]; t, tq = R[row][0], Q[row][0]
    tr, tp = t - dr, tq - dq
    plat = lambda tt: (tt > s + 50) & (tt < s + L - 40)
    yr = avR[row][0] / np.median(envR[row][plat(tr)])
    yq = avQ[row][0] / np.median(envQ[row][plat(tp)])
    w = plat(tp); yq = yq * np.sign(np.sum(yq[w] * np.interp(tp[w], tr, yr)))   # QICK's x vs -x, against RISC-Q
    a = fig.add_subplot(gs[2 * row, :])
    for k, lo, _ in g["zooms"]:
        a.axvspan(lo / 1000, (lo + W) / 1000, color="0.85", lw=0, zorder=0)
        a.text((lo + W / 2) / 1000, 1.17, k, ha="center", va="center", fontsize=10.5, fontweight="bold")
    a.plot(tr / 1000, yr, color=RQ, lw=.9, label=f"RISC-Q (raw ADC, 2 GS/s), {runs(nR[row])}")
    a.plot(tp / 1000, yq, color=TP, lw=.6, label=f"QICK tProc v2 (raw MR buffer, 2.46 GS/s), {runs(nQ[row])}")
    a.set_xlim(-.05, 1.9); a.set_ylim(-1.15, 1.3); a.set_xticks(np.arange(0, 1.91, .25))
    a.set_title(g["title"], loc="left", fontsize=12.5)
    a.set_ylabel("signal (normalized to const)"); a.set_xlabel("program time (us)")
    a.legend(loc="upper right" if row == 0 else "lower right", bbox_to_anchor=None if row == 0 else (1, 1), ncol=1 if row == 0 else 2, framealpha=.95, fontsize=9 if row == 0 else 8.5)
    for j, (k, lo, nm) in enumerate(g["zooms"]):
        z = fig.add_subplot(gs[2 * row + 1, j])
        z.plot(tr, yr, color=RQ, lw=2.2); z.plot(tp, yq, color=TP, lw=1.1)
        z.set_xlim(lo, lo + W); z.set_ylim(-1.15, 1.15); z.set_title(f"{k}: {nm}", loc="left", fontsize=11)
        z.set_xlabel("program time (ns)")
        if j == 0: z.set_ylabel("signal (normalized)")
        else: z.set_yticklabels([])
jr, jq = max(v[1] for v in avR), max(v[1] for v in avQ)
fig.suptitle("Two-generator MultiPulseProgram on the ZCU216 board: RISC-Q vs QICK tProc v2, both generators in every run",
             x=.055, y=.985, ha="left", fontsize=14, fontweight="bold")
fig.text(.055, .955, va="top", fontsize=10, color="0.3", s=
         "Blue: RISC-Q's first run (both ADCs recorded in it). Orange: QICK's first raw capture of each ADC (its raw buffer records "
         "one ADC per run, so these are\nQICK's runs 0 and 1). One run each, no averaging, no phase fitted. Each design shifted by "
         f"the delay measured on the average of all {NALL} runs (RISC-Q {dr:.1f} ns, QICK {dq:.1f} ns),\nDC offset removed, and normalized to its const pulse."
         if nR[0] == 1 else
         f"Blue: average of {nR[0]} RISC-Q runs per ADC (both ADCs recorded every run). Orange: average of {nQ[0]} QICK runs per ADC "
         f"(its raw buffer records one ADC per run,\nso QICK ran {2 * nQ[0]} times, alternating ADCs). No phase fitted. "
         f"Each run is shifted onto its own const start before averaging; the run-to-run spread of the const start was\nRISC-Q {jr:.2f} ns, "
         f"QICK {jq:.1f} ns. Each design shifted by its own measured delay (RISC-Q {dr:.1f} ns, QICK {dq:.1f} ns), DC offset removed, "
         f"and normalized to its const pulse.")
fig.savefig(out, dpi=170); plt.close(fig)

# ---- printed summary, per pulse, per run ----
for row, g in enumerate(GENS):
    pr = np.array([per_pulse(R[row][0], x, g["F"], g, dr) for x in R[row][1]])
    pq = np.array([per_pulse(Q[row][0], x, g["F"], g, dq) for x in Q[row][1]])
    for i, (nm, s0, L0, ph) in enumerate(g["pulses"]):
        f = lambda p, c: f"{p[:, i, c].mean():+7.2f} ± {p[:, i, c].std():4.2f}"
        lines.append(f"gen{row} {nm:13s} timing RISC-Q {f(pr, 0)}  QICK {f(pq, 0)} ns | width RISC-Q {pr[:, i, 1].mean():6.1f}  QICK {pq[:, i, 1].mean():6.1f} ns "
                     f"(requested length {L0}) | amplitude RISC-Q {pr[:, i, 2].mean():.3f}  QICK {pq[:, i, 2].mean():.3f} | phase RISC-Q {f(pr, 3)}  QICK {f(pq, 3)} deg (requested {ph})")


def const_center(t, m, s, L):
    e0, e1, _ = edges(t, m, s - 30, s + L + 30)
    return (e0 + e1) / 2


# gen 1 against gen 0 within the same run (const centers; requested gap 750 - 900 = -150 ns), all 40 runs
_, t, _, r0 = read_riscq(f"{D}/riscq_2loop_adc2.csv"); _, _, _, r1 = read_riscq(f"{D}/riscq_2loop_adc0.csv")
rel_r = np.array([const_center(t, env(t, dc_free(t, a.astype(float), 200.), 200.), 500 + dr, 500)
                  - const_center(t, env(t, dc_free(t, b.astype(float), 100.), 100.), 800 + dr, 200) + 150 for a, b in zip(r1, r0)])
rel_q = []
for k in range(len(glob.glob(f"{D}/qick_2loop_ro0_[0-9]*.csv"))):
    c = []
    for ro, L in ((0, 500), (1, 200)):
        d = np.loadtxt(f"{D}/qick_2loop_ro{ro}_{k}.csv", delimiter=",", skiprows=1); tt = d[:, 0] * 1000; m = np.abs(d[:, 1] + 1j * d[:, 2])
        c.append(const_center(tt, m, tt[np.argmax(m > .75 * m.max())] - 10, L))   # the const is each readout's strongest pulse
    rel_q.append(c[0] - c[1] + 150)
rel_q = np.array(rel_q)
lines.append(f"gen1 against gen0 in the same run (const centers, against the requested 150 ns gap): RISC-Q {rel_r.mean():+.2f} ± {rel_r.std():.2f} ns "
             f"over {len(rel_r)} runs, QICK {rel_q.mean():+.2f} ± {rel_q.std():.2f} ns over {len(rel_q)} runs (QICK from its decimated readouts)")
print("\n".join(lines)); print(f"-> {out}")
