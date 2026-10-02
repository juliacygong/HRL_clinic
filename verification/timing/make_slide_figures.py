#!/usr/bin/env python3
"""Slide figures for the timing study (light theme, 16:9-friendly PNGs).

Run with the QICKEmu venv (matplotlib):
    ~/projects/HRL_clinic/.venv/bin/python make_slide_figures.py
Writes verification/timing/figures/:
    fig1_pipeline.png   QICK vs RISC-Q command path, clock domains, event markers, measured intervals
    fig2_timeline.png   same due time, different output time (release early vs late)
    fig3_risks.png      measured waveform behavior, QICK vs native RISC-Q, per conversion risk
Palette: reference data-viz palette (dataviz skill references/palette.md), categorical slots 1-2
(QICK blue, RISC-Q orange), chrome/ink tokens from the same file. Meaning that matters (truncated,
dropped, stale) is carried by hatching + text, not color alone.
"""

import csv
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "figures")
QRUNS = os.path.join(HERE, "runs")
RRUNS = os.path.join(HERE, "riscq_runs")

# ── tokens (palette.md, light) ──
SURFACE, PAGE = "#fcfcfb", "#f9f9f7"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
QICK, RISCQ = "#2a78d6", "#eb6834"          # categorical slots 1, 2
QICK_DARK, RISCQ_DARK = "#1c5cab", "#b84a1d"  # darker steps for hatch ink / outlines
BAND = ["#f0efec", "#e8e7e2", "#f0efec"]    # neutral domain bands

SG_PS, T_PS = 1669.344, 2324.0
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": AXIS,
                     "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
                     "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE})


def rd(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def box(ax, x, y, w, h, text, edge, fill=SURFACE, fs=10, lw=1.6):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=fill, ec=edge, lw=lw, zorder=3))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=INK, zorder=4)


def arrow(ax, x0, x1, y, label="", color=INK2, label_y=None):
    ax.annotate("", (x1, y), (x0, y), arrowprops=dict(arrowstyle="-|>", color=color, lw=1.4,
                                                       shrinkA=0, shrinkB=0), zorder=2)
    if label:
        ax.text((x0 + x1) / 2, label_y, label, ha="center", va="top", fontsize=9, color=INK,
                zorder=4, bbox=dict(boxstyle="round,pad=0.2", fc=SURFACE, ec=AXIS, lw=0.8))


def event(ax, x, y, name, color):
    ax.plot([x], [y], marker="o", ms=9, mfc=SURFACE, mec=color, mew=2, zorder=5)
    ax.text(x, y + 0.28, name, ha="center", va="bottom", fontsize=9, fontweight="bold", color=INK, zorder=5)


# ───────────────────────── fig 1: pipeline ─────────────────────────
def fig_pipeline():
    fig, ax = plt.subplots(figsize=(13.33, 6.2))
    ax.set_xlim(0, 20); ax.set_ylim(0, 9.4); ax.axis("off")

    # QICK clock-domain bands
    doms = [(0.2, 5.4, "core  c_clk 200 MHz"), (5.6, 5.4, "timeline  t_clk 430 MHz"),
            (11.0, 8.8, "generator  sg_clk 599 MHz (16 samples/clk)")]
    for (x, w, lab), c in zip(doms, BAND):
        ax.add_patch(Rectangle((x, 5.0), w, 3.9, fc=c, ec="none", zorder=0))
        ax.text(x + 0.12, 8.72, lab, ha="left", va="top", fontsize=9.5, color=INK2)
    ax.add_patch(Rectangle((0.2, 9.0), 0.28, 0.28, fc=QICK, ec="none"))
    ax.text(0.6, 9.3, "QICK  (tProcV2 -> SGv6)", ha="left", va="top", fontsize=13, fontweight="bold", color=INK)

    y = 6.2
    box(ax, 0.5, y, 2.1, 1.1, "tProc core\nissues command", QICK, fs=9)
    box(ax, 3.1, y, 2.1, 1.1, "wave FIFO\n{cmd, due time}", QICK, fs=9)
    box(ax, 6.2, y, 2.2, 1.1, "comparator\nrelease if\ntime > due", QICK, fs=9.5)
    box(ax, 9.0, y, 1.6, 1.1, "CDC FIFO\n(shared\nSG0-2)", QICK, fs=8.5)
    box(ax, 11.5, y, 2.4, 1.1, "SGv6 FIFO\nplays when idle", QICK)
    box(ax, 14.5, y, 2.4, 1.1, "FSM + DDS\nnsamp cycles", QICK)
    ax.text(18.3, y + 0.55, "DAC", ha="center", va="center", fontsize=11, color=INK2)
    yl, ly = y + 0.55, y - 0.25
    arrow(ax, 2.6, 3.1, yl, "1 c_clk", label_y=ly)
    arrow(ax, 5.2, 6.2, yl, "~10 ns CDC", label_y=ly)
    arrow(ax, 8.4, 9.0, yl, "due + 4 t_clk", label_y=ly)
    arrow(ax, 10.6, 11.5, yl, "~16.5 sg_clk*", label_y=ly)
    arrow(ax, 13.9, 14.5, yl, "1 sg_clk", label_y=ly)
    arrow(ax, 16.9, 17.8, yl, "9 sg_clk", label_y=ly)
    for x, n in [(2.85, "E0i"), (4.15, "E0"), (5.7, "E1"), (8.7, "E2"), (11.05, "E3"), (14.2, "E4"), (17.35, "E5")]:
        event(ax, x, y + 1.3, n, QICK)
    # swap boundary: tProc (left of E2) is replaced by RISC-Q + adapter; CDC + SGv6 (right) stay
    ax.plot([8.7, 8.7], [5.05, 7.3], color=INK, lw=1.8, ls=(0, (5, 3)), zorder=3.5)
    ax.text(8.55, 5.2, "REPLACED by RISC-Q + adapter", ha="right", va="bottom", fontsize=10,
            fontweight="bold", color=INK, zorder=6)
    ax.text(8.85, 5.2, "KEPT: CDC + SGv6 unchanged", ha="left", va="bottom", fontsize=10,
            fontweight="bold", color=INK, zorder=6)

    # RISC-Q: one clock
    ax.add_patch(Rectangle((0.2, 0.35), 19.6, 3.9, fc=BAND[0], ec="none", zorder=0))
    ax.add_patch(Rectangle((0.2, 4.42), 0.28, 0.28, fc=RISCQ, ec="none"))
    ax.text(0.6, 4.72, "native RISC-Q", ha="left", va="top", fontsize=13, fontweight="bold", color=INK)
    ax.text(19.7, 4.12, "one clock  dspCd  (1 cycle = 1 batch = 16 samples)", ha="right", va="top", fontsize=9.5, color=INK2)
    y = 1.5
    box(ax, 0.5, y, 2.1, 1.1, "RISC-V CPU\nposted store", RISCQ)
    box(ax, 3.1, y, 2.1, 1.1, "RfLink\n4 pipe regs", RISCQ)
    box(ax, 5.7, y, 2.5, 1.1, "PulseParamBuffer\nfire + startTime", RISCQ, fs=9.5)
    box(ax, 8.9, y, 3.2, 1.1, "6 TimedQueues, depth ~5\npop EARLY by lead", RISCQ, fs=8.5)
    box(ax, 12.8, y, 3.0, 1.1, "native PulseGenerator\n(not used if SGv6 kept)", AXIS, fill=BAND[1], fs=9)
    ax.text(18.3, y + 0.55, "DAC", ha="center", va="center", fontsize=11, color=INK2)
    yl, ly = y + 0.55, y - 0.25
    arrow(ax, 2.6, 3.1, yl, "")
    arrow(ax, 5.2, 5.7, yl, "4 cyc", label_y=ly)
    arrow(ax, 8.2, 8.9, yl, "+2 cyc", label_y=ly)
    arrow(ax, 12.1, 12.8, yl, "due -52..-2", label_y=ly)
    arrow(ax, 15.8, 17.8, yl, "output AT due", color=MUTED, label_y=ly)
    for x, n in [(2.85, "E0i"), (5.45, "E0"), (8.55, "E1"), (12.45, "E2"), (16.8, "E5")]:
        event(ax, x, y + 1.3, n, RISCQ)
    ax.text(10.5, 0.45, "native path shown for reference: the adapter would hand RISC-Q's commands to QICK's CDC + SGv6 at E2",
            ha="center", va="bottom", fontsize=9, color=MUTED)
    fig.text(0.012, 0.01, "* emulator-model value (CDC synchronizer); other QICK intervals come from shared RTL. "
             "Measured in QICKEmu (Verilator) and the RISC-Q CPU-in-the-loop sim.", fontsize=8.5, color=MUTED)
    fig.savefig(os.path.join(OUT, "fig1_pipeline.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)


# ───────────────────────── fig 2: timeline contrast ─────────────────────────
def fig_timeline():
    # measured: QICK E4-due 37.687..39.338 ns over 322 on-time pulses; E5 = E4 + 9 sg_clk
    e4_lo, e4_hi = 37.687e3 / SG_PS, 39.338e3 / SG_PS
    rel = 4 * T_PS / SG_PS
    e3_lo, e3_hi = 36.018e3 / SG_PS, 37.669e3 / SG_PS
    out_lo, out_hi = e4_lo + 9, e4_hi + 9
    fig, ax = plt.subplots(figsize=(13.33, 4.6))
    ax.set_xlim(-60, 100); ax.set_ylim(-0.3, 2.5)
    for gx in range(-60, 101, 20):
        ax.axvline(gx, color=GRID, lw=0.8, zorder=0)
    ax.axvline(0, color=INK, lw=1.6, zorder=1)
    ax.text(0, 2.42, "due time", ha="center", va="bottom", fontsize=11, color=INK, fontweight="bold")

    yq, yr, h = 1.55, 0.35, 0.5
    # QICK row
    ax.add_patch(Rectangle((out_lo, yq), 60, h, fc=QICK, ec="none", zorder=3))
    ax.add_patch(Rectangle((out_lo - 0.02, yq - 0.06), out_hi - out_lo, h + 0.12, fc="none", ec=QICK_DARK, lw=1, ls=":", zorder=4))
    for x in (rel, (e3_lo + e3_hi) / 2, (e4_lo + e4_hi) / 2):
        ax.plot([x], [yq + h / 2], marker="o", ms=8, mfc=SURFACE, mec=QICK, mew=2, zorder=5)
    ax.text(rel, yq + h + 0.08, "release\n+4 t_clk", ha="center", va="bottom", fontsize=9, color=INK2)
    ax.text((e3_lo + e4_hi) / 2, yq + h + 0.08, "SGv6 accept,\nthen start", ha="center", va="bottom", fontsize=9, color=INK2)
    ax.text(out_lo + 30, yq + h / 2, "pulse (nsamp = 60)", ha="center", va="center", fontsize=10, color=SURFACE, zorder=5)
    ax.text(-59, yq + h / 2, "QICK", ha="left", va="center", fontsize=13, fontweight="bold", color=INK)

    # RISC-Q row
    ax.add_patch(Rectangle((0, yr), 60, h, fc=RISCQ, ec="none", zorder=3))
    ax.text(30, yr + h / 2, "pulse (dur = 60)", ha="center", va="center", fontsize=10, color=SURFACE, zorder=5)
    pops = [("freqP", -52), ("freqC", -36), ("phase", -35), ("amp", -34), ("addr", -11), ("dur", -2)]
    for n, x in pops:
        ax.plot([x, x], [yr, yr + h], color=RISCQ_DARK, lw=1.6, zorder=4)
    for x, lab in [(-52, "freqP"), (-35, "freqC / phase / amp"), (-11, "addr"), (-2, "dur")]:
        ax.text(x, yr - 0.05, lab, ha="center", va="top", fontsize=8.5, color=INK2)
    ax.text(-43, yr + h + 0.06, "parameters released EARLY (per-queue lead)", ha="center", va="bottom", fontsize=9, color=INK2)
    ax.text(-59, yr + h / 2 + 0.02, "RISC-Q", ha="left", va="center", fontsize=13, fontweight="bold", color=INK)

    # offset annotation
    ax.annotate("", (out_lo, 1.2), (0, 1.2), arrowprops=dict(arrowstyle="<->", color=INK, lw=1.3))
    ax.text(out_lo / 2 + 1, 1.24, f"~{(out_lo + out_hi) / 2:.0f} cycles (QICK starts later)", ha="center", va="bottom", fontsize=10.5, color=INK)
    ax.set_yticks([]); ax.set_xlabel("cycles relative to due  (1 cycle = 16 samples: QICK sg_clk = RISC-Q batch)")
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.set_title("Same due time, different output time: QICK releases late and queues; RISC-Q releases early and lands on due",
                 fontsize=12.5, color=INK, loc="left", pad=22)
    fig.text(0.012, -0.06, "QICK: 322 on-time pulses, start band 37.7-39.3 ns (dotted = jitter < 1 sg_clk; absolute value is "
             "emulator-model). RISC-Q: output at due+0, zero jitter (single clock).", fontsize=8.5, color=MUTED)
    fig.savefig(os.path.join(OUT, "fig2_timeline.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)


# ───────────────────────── fig 3: risk panels (measured) ─────────────────────────
def qick_intervals(test, n=None):
    """Per command (issue order): (start, length, gain) in sg_clk relative to the earliest due."""
    d = os.path.join(QRUNS, test, "d0")
    e0 = [r for r in rd(os.path.join(d, "ev_e0_sched.csv")) if r["port"] == "0"]
    e2 = {int(r["gain"], 16) & 0xFFFF: r for r in rd(os.path.join(d, "ev_e2_tproc_out.csv"))}
    e4 = {int(r["gain"], 16) & 0xFFFF: r for r in rd(os.path.join(d, "ev_e4_sg_load.csv"))}
    cmds = e0[:n] if n else e0
    due_sg = {}
    for r in cmds:
        g = int(r["gain"], 16) & 0xFFFF
        a, b = e2[g], e4[g]
        due_ps = float(a["time_ps"]) - (int(a["t_time_abs"]) - int(r["due"])) * T_PS
        due_sg[g] = int(b["sg_cyc"]) - (float(b["time_ps"]) - due_ps) / SG_PS
    ref = min(due_sg.values())
    out = []
    for r in cmds:
        g = int(r["gain"], 16) & 0xFFFF
        out.append((int(e4[g]["sg_cyc"]) + 9 - ref, int(r["nsamp"]), g, due_sg[g] - ref))
    return out


def riscq_intervals(probe):
    """Per planned pulse (issue order): (start, played, planned_len, due, status) relative to earliest due."""
    rows = rd(os.path.join(RRUNS, probe, "riscq_probe_report.csv"))
    rows = [r for r in rows if r["occurrence"] == "0"]
    dues = [int(r["captured_due"] or r["planned_due"]) for r in rows]
    ref = min(dues)
    out = []
    for r, due in zip(rows, dues):
        relo = r["release_offset"]
        start = due + (int(relo) + 2 if relo and int(relo) > -2 else 0)
        played = int(r["out_covered"]) if r["out_covered"] else 0
        out.append((start - ref, played, int(r["dur"]), due - ref, r["status"]))
    return out


def lane(ax, y, segs, color, dark, stale=None):
    """segs: (start, played, planned, label, dropped)."""
    span = ax.get_xlim()[1] - ax.get_xlim()[0]
    last_x, level = None, 0
    for s, played, planned, lab, dropped in segs:
        # stagger labels that would sit on top of each other
        level = (level + 1) % 2 if last_x is not None and abs(s - last_x) < span * 0.035 else 0
        last_x = s
        ly = y + 0.4 + 0.17 * level
        if dropped:
            ax.add_patch(Rectangle((s, y), planned, 0.34, fc="none", ec=dark, lw=1.2, ls="--", zorder=3))
            ax.text(s + planned / 2, y + 0.4, f"{lab} dropped", ha="center", va="bottom", fontsize=7.5, color=INK2, zorder=4)
            continue
        if played < planned:     # ghost of the part that never played
            ax.add_patch(Rectangle((s + played, y), planned - played, 0.34, fc="none", ec=dark, lw=1,
                                   hatch="////", zorder=2))
        ax.add_patch(Rectangle((s, y), max(played, 0.6), 0.34, fc=color, ec=SURFACE, lw=1.5, zorder=3))
        ax.text(s + 0.8, ly, lab, ha="left", va="bottom", fontsize=8, color=INK, zorder=4)
    if stale:
        s, w = stale
        ax.add_patch(Rectangle((s, y - 0.03), w, 0.40, fc="none", ec=INK, lw=1, hatch="xx", zorder=4))


def fig_risks():
    panels = [
        ("Overlap: 2nd pulse due before 1st ends", "T5", "P2_T5", None,
         "QICK chains B after A;  RISC-Q cuts A to 29/60"),
        ("Issue order != due order", "T6", "P4_T6", None,
         "QICK: A then B, both full;  RISC-Q: A cut to 2/60"),
        ("5 pulses, same due time", "T9b", "P6_same5", 5,
         "QICK: 5 back to back;  RISC-Q: 4 cut to 2/12"),
        ("Late command (due already passed)", "T8", "P5_T8", None,
         "RISC-Q plays B's first ~32 cycles with A's amp/phase (xx)"),
        ("8 pulses pending on one channel", "T9a", "P6_n8", 8,
         "QICK: all 8 (256/port, stalls);  RISC-Q: 5 kept, 3 silently dropped"),
    ]
    fig, axs = plt.subplots(3, 2, figsize=(13.33, 8.4))
    axs = axs.ravel()
    for ax, (title, qt, rp, n, note) in zip(axs, panels):
        q = qick_intervals(qt, n)
        r = riscq_intervals(rp)
        names = "ABCDEFGH"
        qsegs = [(s, ln, ln, names[i], False) for i, (s, ln, g, due) in enumerate(q)]
        rsegs = [(s, pl, pn, names[i], "DROPPED" in st) for i, (s, pl, pn, due, st) in enumerate(r)]
        stale = None
        if rp == "P5_T8":
            late = r[1]
            stale = (late[0], 32)
        xs = [s for s, *_ in qsegs + rsegs] + [s + p for s, _, p, *_ in qsegs + rsegs]
        lo, hi = min(xs + [0]) - 10, max(xs) + 10
        ax.set_xlim(lo, hi); ax.set_ylim(0, 1.9)
        lane(ax, 1.05, qsegs, QICK, QICK_DARK)
        lane(ax, 0.25, rsegs, RISCQ, RISCQ_DARK, stale)
        for due in sorted({round(d) for *_, d in q}):
            ax.axvline(due, color=INK, lw=0.9, ls=":", zorder=1)
        ax.set_yticks([0.42, 1.22]); ax.set_yticklabels(["RISC-Q", "QICK"], fontsize=10, color=INK)
        ax.tick_params(axis="y", length=0)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.grid(axis="x", color=GRID, lw=0.7); ax.set_axisbelow(True)
        ax.set_title(title, fontsize=11.5, color=INK, loc="left", fontweight="bold")
        ax.text(0.0, -0.3, note, transform=ax.transAxes, fontsize=9, color=INK2, va="top")
        ax.tick_params(axis="x", labelsize=8.5)
    # key panel
    k = axs[5]; k.axis("off")
    k.set_xlim(0, 10); k.set_ylim(0, 6)
    items = [(QICK, None, "solid", "QICK output (measured, QICKEmu)"),
             (RISCQ, None, "solid", "native RISC-Q output (measured, CPU-in-the-loop)"),
             ("none", "////", "solid", "planned but never played (truncated)"),
             ("none", None, "--", "pulse dropped at a full queue"),
             ("none", "xx", "solid", "plays with the previous pulse's parameters")]
    for i, (fc, hatch, ls, lab) in enumerate(items):
        yy = 5.4 - i * 0.95
        k.add_patch(Rectangle((0.2, yy), 1.3, 0.5, fc=fc, ec=INK2 if fc == "none" else "none", hatch=hatch, ls=ls, lw=1))
        k.text(1.8, yy + 0.25, lab, va="center", fontsize=10, color=INK)
    k.text(0.2, -0.55, "x-axis: cycles (16 samples) after the earliest due; dotted = due times.\n"
           "QICK sits ~32 cycles right of RISC-Q by design (fig 2).", fontsize=8.5, color=MUTED)
    fig.suptitle("Where a literal tProc -> RISC-Q conversion changes the waveform (measured)", fontsize=13.5,
                 color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.96), h_pad=3.2)
    fig.savefig(os.path.join(OUT, "fig3_risks.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)


# ───────────────────────── fig 4: testbench comparison ─────────────────────────
def fig_testbench():
    """How a test vector is checked at the E2 handover (golden = measured tProc run T2)."""
    e0 = [r for r in rd(os.path.join(QRUNS, "T2", "d0", "ev_e0_sched.csv")) if r["port"] == "0"]
    e2 = rd(os.path.join(QRUNS, "T2", "d0", "ev_e2_tproc_out.csv"))
    golden = [(int(a["gain"], 16) & 0xFFFF, int(a["due"]), int(b["t_time_abs"])) for a, b in zip(e0, e2)]

    fig = plt.figure(figsize=(13.33, 6.4))
    # ── top: flow ──
    ax = fig.add_axes([0.02, 0.50, 0.96, 0.46]); ax.axis("off"); ax.set_xlim(0, 20); ax.set_ylim(0, 6)
    box(ax, 0.3, 2.35, 2.6, 1.3, "test vector\npulses · due · tag", INK2, fs=10.5)
    box(ax, 4.2, 3.9, 2.8, 1.2, "tProc run", QICK, fs=11)
    box(ax, 4.2, 0.9, 2.8, 1.2, "candidate run\nRISC-Q / adapter", RISCQ, fs=10)
    box(ax, 8.3, 3.9, 3.0, 1.2, "golden E2 stream\n+ limits", QICK, fs=10.5)
    box(ax, 8.3, 0.9, 3.0, 1.2, "candidate\nE2 stream", RISCQ, fs=10.5)
    box(ax, 12.7, 3.55, 3.2, 1.25, "EQUIVALENCE\nsame as tProc?", INK, fs=10.5)
    box(ax, 12.7, 1.2, 3.2, 1.25, "LEGALITY\nsafe for SGv6?", INK, fs=10.5)
    box(ax, 17.2, 2.35, 2.4, 1.3, "PASS / FAIL", INK, fs=12)
    for (x0, y0, x1, y1) in [(2.9, 3.0, 4.2, 4.5), (2.9, 3.0, 4.2, 1.5), (7.0, 4.5, 8.3, 4.5), (7.0, 1.5, 8.3, 1.5),
                             (11.3, 4.5, 12.7, 4.2), (11.3, 1.5, 12.7, 4.0), (11.3, 1.5, 12.7, 1.8),
                             (15.9, 4.2, 17.2, 3.2), (15.9, 1.8, 17.2, 2.8)]:
        ax.annotate("", (x1, y1), (x0, y0), arrowprops=dict(arrowstyle="-|>", color=INK2, lw=1.4))
    ax.text(14.3, 3.35, "tick · order · fields", ha="center", va="top", fontsize=9, color=INK2)
    ax.text(14.3, 1.0, "3 ≤ nsamp · no early release · no backlog", ha="center", va="top", fontsize=9, color=INK2)
    ax.text(0.3, 5.75, "How a test vector is checked at E2", ha="left", va="top", fontsize=13.5, color=INK, fontweight="bold")

    # ── bottom: per-command timing comparison, one zoomed window per command ──
    cand = [golden[0][2], golden[1][2] - 3]          # illustrative candidate: #2 released 3 ticks early
    for i, (tag, due, rel) in enumerate(golden):
        bx = fig.add_axes([0.07 + i * 0.31, 0.10, 0.27, 0.30])
        bx.set_xlim(due - 6, due + 10); bx.set_ylim(-0.1, 2.0)
        for gx in range(due - 6, due + 11, 2):
            bx.axvline(gx, color=GRID, lw=0.6, zorder=0)
        bx.axvline(due, color=INK, lw=1.1, ls=":", zorder=1)
        bx.text(due, 1.72, "due", ha="center", va="bottom", fontsize=9.5, color=INK2)
        bx.plot([rel], [1.2], marker="o", ms=11, mfc=QICK, mec=SURFACE, mew=1.5, zorder=3)
        bx.plot([cand[i]], [0.45], marker="o", ms=11, mfc=RISCQ, mec=SURFACE, mew=1.5, zorder=3)
        bx.annotate("", (rel, 1.45), (due, 1.45), arrowprops=dict(arrowstyle="<->", color=INK2, lw=1))
        bx.text((due + rel) / 2, 1.5, "+4", ha="center", va="bottom", fontsize=9.5, color=INK2)
        d = cand[i] - rel
        bx.text(due + 9.6, 0.82, "Δ 0  ✓" if d == 0 else f"Δ {d:+d}  ✗", ha="right", va="center",
                fontsize=11, color=INK, fontweight="bold")
        bx.set_yticks([0.45, 1.2])
        bx.set_yticklabels(["candidate", "golden"] if i == 0 else ["", ""], fontsize=10.5, color=INK)
        bx.tick_params(axis="y", length=0); bx.tick_params(axis="x", labelsize=8.5)
        for sp in ("top", "right", "left"):
            bx.spines[sp].set_visible(False)
        bx.set_title(f"command {i + 1}", fontsize=10.5, color=INK, loc="left")
        bx.set_xlabel("timeline tick", fontsize=9.5)

    # rule panel
    rx = fig.add_axes([0.70, 0.08, 0.28, 0.33]); rx.axis("off"); rx.set_xlim(0, 10); rx.set_ylim(0, 10)
    rows = [("release − due", "== 4"), ("tag order", "== golden"), ("each tag", "once"), ("fields", "== golden")]
    rx.text(0, 9.6, "per command", fontsize=11, color=INK, fontweight="bold", va="top")
    for i, (a, b) in enumerate(rows):
        y = 7.6 - i * 2.0
        rx.text(0, y, a, fontsize=11, color=INK, va="center")
        rx.text(6.2, y, b, fontsize=11, color=INK, va="center", fontweight="bold")
        rx.plot([0, 9.8], [y - 1.0, y - 1.0], color=GRID, lw=0.8)
    fig.text(0.07, -0.02, "golden = measured tProc run (T2); candidate row illustrative", fontsize=8.5, color=MUTED)
    fig.savefig(os.path.join(OUT, "fig4_testbench.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    fig_pipeline(); fig_timeline(); fig_risks(); fig_testbench()
    print("wrote", *sorted(os.listdir(OUT)), sep="\n  ")
