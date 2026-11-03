"""Run-to-run timing spread of QICK tProc v2 against RISC-Q, as histograms, with the clock-crossing model.

    plot_jitter.py <qick jitter dir> <2loop data dir> <out.png>

QICK data: qick_v6_2loop.py with MR_CH=1, so every run records ADC 2_226 (gen 0, 100 MHz) raw. RISC-Q data: the 2loop
run's riscq_2loop_adc2.csv (same ADC, same pulses). Per run: the const pulse's start against the capture, and the
const start minus the flat-top start in the same run (same generator, so the capture trigger's crossing cancels).

Model (uniform, independent): QICK's pulse command crosses tProc 430.08 MHz -> gen 599.04 MHz (up to 1.67 ns) and its
capture trigger crosses into the ADC buffer's 307.2 MHz (up to 3.26 ns): the const start spreads as the two uniforms
convolved (a trapezoid 4.93 ns wide). The clocks are locked to one reference, so where the program starts in their
common 65 ns pattern fixes every later crossing of that run: two pulses of one generator move together (no model line).

"""
import glob
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

QD, RD, OUT = sys.argv[1:4]
sys.argv = ["plot_2loop.py", RD, "/dev/null"]
exec(open(__file__.replace("plot_jitter.py", "plot_2loop.py")).read().split("# ---- data: all runs per ADC ----")[0])
F = 100.
T_GEN, T_RO = 1e3 / 599.04, 1e3 / 307.2


def starts(t, xs):
    ms = [env(t, x, F) for x in xs]
    return np.array([const_start(t, m) for m in ms]), np.array([flat_top_delay(t, m) for m in ms])


xs = []
for k in range(len(glob.glob(f"{QD}/qick_jit_mr1_[0-9]*.csv"))):
    d = np.loadtxt(f"{QD}/qick_jit_mr1_{k}.csv", delimiter=",", skiprows=1); t = np.arange(len(d)) / FS_MR * 1000
    z = (d[:, 0] + 1j * d[:, 1]) * np.exp(2j * np.pi * F * t * 1e-3)
    xs.append(dc_free(t, np.real(z * np.exp(-1j * np.angle(np.sum(z ** 2)) / 2)), F))
qc, qf = starts(t, xs)
tr, rx = riscq_runs("adc2", F)
rc, rf = starts(tr, rx)
nq, nr = len(qc), len(rc)


def model(x, a, b):
    """density of U(0,a) + U(0,b), centered"""
    x = x + (a + b) / 2; lo, hi = min(a, b), max(a, b)
    return np.clip(np.minimum(np.minimum(x, a + b - x), lo), 0, None) / (a * b)


fig, ax = plt.subplots(1, 2, figsize=(14, 5.2), gridspec_kw=dict(wspace=.18, left=.06, right=.985, top=.78, bottom=.12))
bins = np.arange(-4, 4.01, .25); xx = np.linspace(-4, 4, 801)
for i, (a, (q, r, m, title)) in enumerate(zip(ax, [
        (qc - qc.mean(), rc - rc.mean(), model(xx, T_GEN, T_RO),
         "Const pulse start against the capture, each run minus the average"),
        ((qc - qf) - (qc - qf).mean(), (rc - rf) - (rc - rf).mean(), model(xx, T_GEN, T_GEN),
         "Const start minus flat-top start in the same run (capture trigger cancels)")])):
    a.hist(r, bins=np.arange(-4, 4.01, .05), color="tab:blue", alpha=.9, label=f"RISC-Q, {nr} runs: spread {r.std():.2f} ns, range {np.ptp(r):.2f} ns", density=True)
    a.hist(q, bins=bins, color="tab:orange", alpha=.75, label=f"QICK tProc v2, {nq} runs: spread {q.std():.2f} ns, range {np.ptp(q):.2f} ns", density=True)
    if i == 0: a.plot(xx, m, color="k", lw=1.6, ls="--", label="clock-crossing model (no fitted parameters)")
    a.set_xlim(-4, 4); a.set_ylim(0, 1.0 if i == 0 else 2.6); a.set_title(title, loc="left", fontsize=11.5)
    a.set_xlabel("ns"); a.legend(loc="upper left", fontsize=9, framealpha=.95)
ax[0].set_ylabel("fraction of runs per ns")
ax[0].text(.99, .62, f"model: up to {T_GEN:.2f} ns (gen 599 MHz)\n+ up to {T_RO:.2f} ns (capture 307 MHz)", transform=ax[0].transAxes, ha="right", va="top", fontsize=9, color=".25")
slip = np.abs((qc - qf) - np.median(qc - qf)) > 1
ax[1].text(.02, .62, f"QICK: the two pulses move together in most runs\n(spread {(qc - qf)[~slip].std():.2f} ns without the slips);\n"
           f"in {slip.sum()} of {nq} runs the const\ncame {-np.median(((qc - qf) - np.median(qc - qf))[slip]):.1f} ns early", transform=ax[1].transAxes, ha="left", va="top", fontsize=9, color=".25")
fig.suptitle("Run-to-run timing spread on the ZCU216: QICK tProc v2 against RISC-Q (generator 0, DAC 3_228 -> ADC 2_226, raw ADC)",
             x=.06, y=.975, ha="left", fontsize=13.5, fontweight="bold")
fig.text(.06, .905, va="top", fontsize=10, color=".3", s=
         "QICK's tProc times pulses on 430.08 MHz, its generators run on 599.04 MHz and its capture buffer on 307.2 MHz; each pulse command and the capture trigger\n"
         "cross between them and land on whichever edge comes first. RISC-Q times, plays and captures on one 500 MHz clock. Spread = standard deviation.")
fig.savefig(OUT, dpi=170)
print(f"QICK {nq} runs: const start spread {qc.std():.2f} range {np.ptp(qc):.2f} ns; const minus flat-top spread {(qc - qf).std():.2f} range {np.ptp(qc - qf):.2f} ns")
print(f"RISC-Q {nr} runs: const start spread {rc.std():.3f} range {np.ptp(rc):.3f} ns; const minus flat-top spread {(rc - rf).std():.3f} range {np.ptp(rc - rf):.3f} ns")
print(f"model: const start spread {np.sqrt((T_GEN ** 2 + T_RO ** 2) / 12):.2f} range {T_GEN + T_RO:.2f} ns")
print(f"-> {OUT}")
