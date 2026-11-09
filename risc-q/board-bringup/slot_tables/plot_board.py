"""Board figures for the slot-table build (ZCU216, bitstream riscvsoc-bd-qick-2loop-fast-explore).

    plot_board.py <data dir> <out dir>
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from analyze import load, segments, FS

data, out = Path(sys.argv[1]), Path(sys.argv[2])
RUN = int(sys.argv[3]) if len(sys.argv) > 3 else None     # plot one run (0-based) instead of the average
SUFFIX = "" if RUN is None else f"_run{RUN + 1}"
_load = load
def load(f):
    t, runs = _load(f)
    return (t, runs) if RUN is None else (t, runs[:, [RUN]])
def runs_text(n):
    return f"{n} runs averaged" if RUN is None else f"run {RUN + 1} of 20, no averaging"
def status_one(path):
    """This run's flags: 'none' if the 20-run summary has none set, else the summary (every run was flagged)."""
    st = status_line(path)
    if RUN is None:
        return st
    return "none" if st.startswith("0 of") else "late (set on all 20 runs)" if "late" in st else st
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, SHADE = "#2a78d6", "#eb6834", "#ecebe7"
plt.rcParams.update({"figure.facecolor": SURF, "axes.facecolor": SURF, "axes.edgecolor": INK2,
                     "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
                     "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6})


def envelope(runs, f0, smooth=8):
    """Average over runs of the carrier-demodulated magnitude (ADC counts)."""
    n = np.arange(runs.shape[0])
    envs = []
    for r in range(runs.shape[1]):
        x = runs[:, r] - np.median(runs[:, r][runs[:, r] != 0])
        bb = x * np.exp(-2j * np.pi * f0 / FS * n)
        envs.append(np.abs(np.convolve(bb, np.ones(smooth) / smooth, "same")) * 2)
    return np.mean(envs, axis=0)


def status_line(path):
    for line in open(path):
        if line.startswith("# pulse_status:"):
            return line.split(":", 1)[1].strip()
    return "?"


# ── figure 1: PulseUpdateProgram at the default 1 us initial delay, before / after ──
t, old = load(data / "old_pu_adc2.csv")
_, new = load(data / "new_pu_adc2.csv")
win = (t < 900)
e_old, e_new = envelope(old, 500e6)[win], envelope(new, 500e6)[win]
tt = t[win]
# scheduled windows: where the on-time (after) pulses are, from its average envelope (> 5 % of peak)
on = e_new > 0.05 * e_new.max()
edges = np.flatnonzero(np.diff(on.astype(int)))
sched = [(tt[a], tt[b]) for a, b in zip(edges[::2], edges[1::2])]

# per-pulse phase vs pulse 1 (after), circular average over the runs
ph = []
for r in range(new.shape[1]):
    s, _ = segments(new[:, r], 500e6)
    p = np.array([x["ph"] for x in s]); ph.append(np.exp(1j * np.radians(p - p[0])))
ph = np.degrees(np.angle(np.mean(ph, axis=0))) % 360
spread = np.degrees(np.sqrt(-2 * np.log(np.abs(np.mean(
    [np.exp(1j * np.radians(0)) for _ in range(1)])))))  # placeholder, replaced below
on_t = np.array([[x["t"] for x in segments(new[:, r], 500e6)[0]] for r in range(new.shape[1])])

fig, axes = plt.subplots(2, 1, figsize=(10, 6.2), sharex=True, sharey=True)
ymax = max(e_old.max(), e_new.max()) * 1.32
for ax, e, color, title, stat in (
        (axes[0], e_old, ORANGE, "Before: previous compiler output", data / "old_pu_adc2.csv"),
        (axes[1], e_new, BLUE, "After: slot tables (new compiler + RTL)", data / "new_pu_adc2.csv")):
    for a, b in sched:
        ax.axvspan(a, b, color=SHADE, lw=0, zorder=0)
    ax.plot(tt, e, color=color, lw=1.6, zorder=2)
    ax.set_ylim(0, ymax)
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    ax.set_title("pulse status flags: " + status_one(stat), loc="right", fontsize=9, color=INK2)
    ax.set_ylabel("envelope (ADC counts)")
axes[0].text(8, ymax * 0.90, "grey bands = when the program schedules each pulse", fontsize=9, color=INK2)
for (a, b), p in zip(sched, ph):
    axes[1].text((a + b) / 2, e_new.max() * 1.07, f"{p:.0f}°", ha="center", fontsize=9.5, color=INK)
axes[1].text(sched[-1][1] + 12, e_new.max() * 1.07, "carrier phase vs first pulse\n(virtual-Z 0, 90, 90, 180)",
             fontsize=8.5, color=INK2, va="center")
axes[1].set_xlabel("time in the readout window (ns)")
d = np.diff(on_t.mean(0))
fig.suptitle(f"PulseUpdateProgram on the ZCU216, default 1 µs initial delay, last shot of 2, {runs_text(20)}",
             x=0.01, ha="left", fontsize=12, color=INK)
fig.text(0.01, 0.005, f"After: pulse spacing {d[0]:.1f} / {d[1]:.1f} / {d[2]:.1f} ns (scheduled 200)"
         + ("" if RUN is not None else f", run-to-run onset spread {on_t.std(0).max():.2f} ns (ADC sample 0.5 ns)")
         + ". DAC 3_228 -> ADC 2_226 loopback.",
         fontsize=8.5, color=INK2)
fig.tight_layout(rect=(0, 0.03, 1, 0.97))
fig.savefig(out / f"board_1us_pulseupdate_before_after{SUFFIX}.png", dpi=160)
print("wrote", out / f"board_1us_pulseupdate_before_after{SUFFIX}.png")

# ── figure 2: two-gen stress program ──
t, g = load(data / "stress_adc2.csv")      # gen 0 -> DAC 3_228 -> ADC 2_226
_, h = load(data / "stress_adc0.csv")      # gen 1 -> DAC 1_228 -> ADC 0_226
eg = envelope(g, 500e6)
first = np.mean([segments(g[:, r], 500e6, thr=0.08)[0][0]["t"] for r in range(g.shape[1])]) - 2
# per-pulse phase (gen 0) relative to its first pulse, circular average over runs
n = np.arange(len(t))
P = []
for r in range(g.shape[1]):
    x = g[:, r] - np.median(g[:, r][g[:, r] != 0])
    z = [(x[a:a + 80] * np.exp(-2j * np.pi * 500e6 / FS * n[a:a + 80])).sum()
         for a in (int(round((first + 50 * i) * 2)) for i in range(30))]
    p = np.angle(z); P.append(np.exp(1j * (p - p[0])))
P = np.array(P)
pavg = (np.degrees(np.angle(P.mean(0))) + 22.5) % 360 - 22.5   # 0 deg pulses plot at 0, not 360
pspread = np.degrees(np.sqrt(-2 * np.log(np.abs(P.mean(0)))))
sched_ph = (45 * np.arange(30)) % 360
# gen 1 carrier per pulse (run 0) from an FFT of each 100 ns slot
x1 = h[:, 0] - np.median(h[:, 0][h[:, 0] != 0])
env1 = np.convolve(np.abs(x1), np.ones(8) / 8, "same")
h0 = np.flatnonzero(env1 > 0.3 * env1.max())[0] / 2
freqs = []
for i in range(15):
    a = int(round((h0 + 100 * i) * 2)); seg = x1[a:a + 140]
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 1 << 15)); freqs.append(np.argmax(spec) * FS / (1 << 15) / 1e6)

fig, axes = plt.subplots(3, 1, figsize=(11, 8.2), sharex=True,
                         gridspec_kw={"height_ratios": [1.2, 0.8, 1.2]})
ax = axes[0]
ax.plot(t, eg, color=BLUE, lw=1.4)
ax.set_ylabel("envelope (ADC counts)")
ax.set_title("Gen 0: 30 Gaussian pulses every 50 ns, gain stepped 1/8 to 1, phase +45° per pulse (500 MHz)",
             loc="left", fontsize=10.5)
ax = axes[1]
xs = first + 50 * np.arange(30) + 20
ax.plot(xs, sched_ph, "_", color=INK2, ms=13, mew=1.6, label="scheduled")
ax.plot(xs, pavg, "o", color=BLUE, ms=4.5, label="measured" + (" (average of 20 runs)" if RUN is None else ""))
ax.set_ylim(-30, 360); ax.set_yticks([0, 90, 180, 270])
ax.set_ylabel("gen 0 phase (°)")
ax.legend(loc="lower right", frameon=False, fontsize=8.5, ncol=1)
ax = axes[2]
ax.plot(t, x1, color=ORANGE, lw=0.7)
for i, f in enumerate(freqs):
    ax.text(h0 + 100 * i + 40, np.abs(x1).max() * 1.08, f"{f:.0f}", ha="center", fontsize=8.5, color=INK)
ax.text(1.0, 1.02, "carrier per pulse (MHz, measured)", transform=ax.transAxes, ha="right", va="bottom",
        fontsize=8.5, color=INK2)
ax.set_ylim(-np.abs(x1).max() * 1.2, np.abs(x1).max() * 1.25)
ax.set_ylabel("ADC counts" + (" (run 1)" if RUN is None else ""))
ax.set_title("Gen 1 at the same time: 15 pulses of 80 ns every 100 ns, carrier hopping 100/200/300/400 MHz",
             loc="left", fontsize=10.5)
ax.set_xlabel("time in the readout window (ns)")
ax.set_xlim(0, 2050)
fig.suptitle("Two generators at once, 45 pulses in 1.5 µs per shot, 1 µs initial delay, last shot of 3"
             + ("" if RUN is None else f", {runs_text(20)}"),
             x=0.01, ha="left", fontsize=12)
fig.text(0.01, 0.005, (f"20 runs: pulse status flags {status_line(data / 'stress_adc2.csv')}. "
          f"Gen 0 phase spread across runs at most {pspread.max():.1f}°. " if RUN is None else
          f"Pulse status flags this run: {status_one(data / 'stress_adc2.csv')}. ") +
         f"Gen 0: DAC 3_228 -> ADC 2_226, gen 1: DAC 1_228 -> ADC 0_226.", fontsize=8.5, color=INK2)
fig.tight_layout(rect=(0, 0.025, 1, 0.97))
fig.savefig(out / f"board_stress_two_gens{SUFFIX}.png", dpi=160)
print("wrote", out / f"board_stress_two_gens{SUFFIX}.png")
