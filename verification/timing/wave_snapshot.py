#!/usr/bin/env python3
"""Render annotated waveform snapshots from a QICKEmu FST trace.

Usage (needs matplotlib -> run with the QICKEmu venv):
    ~/projects/HRL_clinic/.venv/bin/python wave_snapshot.py <run_dir>

<run_dir> must contain waveform.fst (traced run) and the ev_*.csv event logs.
Writes wave_*.png and waveform_view.gtkw (GTKWave save file) into <run_dir>.
Only the first SG0 command group (commands 0-2 of test_sim) is drawn; the
event markers come from the ev_*.csv files, so the picture and the numbers
in timing_report.csv are the same measurement.
"""

import csv
import os
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

H = "QICKEmu_harness"
DUT = f"{H}.qick_dut"
QPROC = f"{DUT}.AXIS_QPROC.QPROC"
DISP = f"{QPROC}.DISPATCHER"
SGC = f"{DUT}.u_axis_signal_gen_v6_0.signal_gen_top_i.signal_gen_i.ctrl_i"

# (label, full path, bit index or None for the whole vector)
SIGNALS = {
    "c_clk": (f"{H}.c_clk", None),
    "t_clk": (f"{H}.t_clk", None),
    "t_time_abs_o": (f"{H}.t_time_abs_o", None),
    "port_we (E0i)": (f"{QPROC}.port_we", None),
    "c_fifo_wave_push_s[0] (E0)": (f"{DISP}.c_fifo_wave_push_s", 0),
    "t_fifo_wave_empty[0] (E1)": (f"{DISP}.t_fifo_wave_empty", 0),
    "wave_t_gr_r[0]": (f"{DISP}.wave_t_gr_r", 0),
    "wave_pop[0]": (f"{DISP}.wave_pop", 0),
    "m0 tvalid (E2)": (f"{DUT}.tproc_sg0cdc_axis_tvalid", None),
    "m0 tready": (f"{DUT}.tproc_sg0cdc_axis_tready", None),
    "sgt0 tvalid (E3)": (f"{DUT}.sgt0_sg0_axis_tvalid", None),
    "load_int (E4)": (f"{SGC}.load_int", None),
    "en_o (E5)": (f"{SGC}.en_o", None),
}

FS_PER_NS = 1_000_000


def parse_header(lines):
    """Map full hierarchical path -> (vcd id, width)."""
    scope, paths = [], {}
    for line in lines:
        tok = line.split()
        if not tok:
            continue
        if tok[0] == "$scope":
            scope.append(tok[2])
        elif tok[0] == "$upscope":
            scope.pop()
        elif tok[0] == "$var":
            width, vid, name = int(tok[2]), tok[3], tok[4]
            paths.setdefault(".".join(scope + [name]), (vid, width))
        elif tok[0] == "$enddefinitions":
            break
    return paths


def extract(fst, t0_ns, t1_ns):
    """Return {label: [(t_ns, int_value), ...]} for SIGNALS inside [t0, t1]."""
    proc = subprocess.Popen(["fst2vcd", "-f", fst], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1 << 20)
    header = []
    for line in proc.stdout:
        header.append(line)
        if line.startswith("$enddefinitions"):
            break
    paths = parse_header(header)
    wanted = {}
    for label, (path, bit) in SIGNALS.items():
        if path not in paths:
            raise KeyError(f"signal not in trace: {path}")
        wanted.setdefault(paths[path][0], []).append((label, bit))

    t0, t1 = t0_ns * FS_PER_NS, t1_ns * FS_PER_NS
    last = {label: 0 for label in SIGNALS}
    out = {label: [] for label in SIGNALS}
    now = 0
    first = next(iter(SIGNALS))   # any signal: marks that the window has started

    def apply(vid, value):
        for label, bit in wanted[vid]:
            if isinstance(bit, tuple):          # (lo, hi) bit-field, e.g. a gain field
                v = (value >> bit[0]) & ((1 << (bit[1] - bit[0] + 1)) - 1)
            else:
                v = (value >> bit) & 1 if bit is not None else value
            if now < t0:
                last[label] = v
            elif not out[label] or out[label][-1][1] != v:
                out[label].append((now / FS_PER_NS, v))

    for line in proc.stdout:
        c = line[0]
        if c == "#":
            now = int(line[1:])
            if now > t1:
                break
            if now >= t0 and not out[first]:
                for label in SIGNALS:
                    out[label].append((t0_ns, last[label]))
        elif c in "01xz":
            vid = line[1:].strip()
            if vid in wanted:
                apply(vid, 1 if c == "1" else 0)
        elif c == "b":
            val, vid = line[1:].split()
            if vid in wanted:
                apply(vid, int(val.replace("x", "0").replace("z", "0"), 2))
    proc.kill()
    return out


def read_events(run_dir):
    def rd(name):
        with open(os.path.join(run_dir, name), newline="") as f:
            return list(csv.DictReader(f))
    ps = lambda r: float(r["time_ps"]) / 1000.0
    e0i = [r for r in rd("ev_e0i_issue.csv") if r["p_addr"] == "0"]
    e0 = [r for r in rd("ev_e0_sched.csv") if r["port"] == "0"]
    return {
        "E0i": [ps(r) for r in e0i], "E0": [ps(r) for r in e0],
        "E1": [ps(r) for r in rd("ev_e1_timeline.csv")],
        "E2": [ps(r) for r in rd("ev_e2_tproc_out.csv")],
        "E3": [ps(r) for r in rd("ev_e3_sg_in.csv")],
        "E4": [ps(r) for r in rd("ev_e4_sg_load.csv")],
        "E5": [ps(r) for r in rd("ev_e5_sg_en.csv")],
        "due": [int(r["due"]) for r in e0],
        "e2_abs": [int(r["t_time_abs"]) for r in rd("ev_e2_tproc_out.csv")],
    }


def draw(waves, labels, window, markers, title, path, bus_labels=()):
    fig, axes = plt.subplots(len(labels), 1, sharex=True,
                             figsize=(14, 0.55 * len(labels) + 1.6))
    t0, t1 = window
    for ax, label in zip(axes, labels):
        pts = waves[label] + [(t1, waves[label][-1][1])]
        ts = [p[0] for p in pts]
        if label in bus_labels:
            # bus: draw value boxes
            for (ta, va), (tb, _) in zip(pts[:-1], pts[1:]):
                ax.plot([ta, tb], [0.9, 0.9], color="tab:blue", lw=1)
                ax.plot([ta, tb], [0.1, 0.1], color="tab:blue", lw=1)
                ax.plot([ta, ta], [0.1, 0.9], color="tab:blue", lw=1)
                if tb - ta > (t1 - t0) / 60:
                    txt = f"{va:x}" if "gain" in label else str(va)
                    ax.text((ta + tb) / 2, 0.5, txt, ha="center", va="center", fontsize=7)
        else:
            ax.step(ts, [p[1] for p in pts], where="post", color="tab:blue", lw=1.2)
        ax.set_ylim(-0.2, 1.2)
        ax.set_yticks([])
        ax.set_ylabel(label, rotation=0, ha="right", va="center", fontsize=8)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        for tm, _, color in markers:
            ax.axvline(tm, color=color, lw=0.8, ls="--", alpha=0.8)
    for i, (tm, text, color) in enumerate(markers):
        # stagger labels on two rows so close markers stay readable
        axes[0].annotate(text, (tm, 1.25 + 0.45 * (i % 2)), xycoords=("data", "axes fraction"),
                         ha="center", fontsize=7, color=color, annotation_clip=False)
    axes[-1].set_xlim(t0, t1)
    axes[-1].set_xlabel("simulation time [ns]")
    fig.suptitle(title, fontsize=10, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_gtkw(run_dir, window):
    lines = [f'[dumpfile] "{os.path.join(run_dir, "waveform.fst")}"',
             f"[timestart] {int(window[0] * FS_PER_NS)}",
             "@28"]
    for label, (path, bit) in SIGNALS.items():
        if label == "t_time_abs_o":
            lines += ["@22", f"{path}[47:0]", "@28"]
        elif bit is not None:
            lines.append(f"({bit}){path}[4:0]")
        else:
            lines.append(path)
    with open(os.path.join(run_dir, "waveform_view.gtkw"), "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    run_dir = os.path.abspath(sys.argv[1])
    ev = read_events(run_dir)
    fst = os.path.join(run_dir, "waveform.fst")

    # Figure 1: acceptance (E0i -> E0 -> E1) for command 0, c_clk/t_clk side.
    w1 = (ev["E0i"][0] - 12, ev["E1"][0] + 12)
    # Figure 2: release decision (due -> compare -> pop -> E2), t_clk side.
    w2 = (ev["E2"][0] - 22, ev["E2"][0] + 8)
    # Figure 3: whole chain for the first same-due group (cmds 0-2) to the output burst.
    w3 = (ev["E2"][0] - 15, ev["E5"][1] + 15)

    waves = extract(fst, min(w1[0], w2[0], w3[0]), max(w1[1], w2[1], w3[1]))

    def clip(win):
        out = {}
        for k, pts in waves.items():
            before = [p for p in pts if p[0] <= win[0]]
            inside = [p for p in pts if win[0] < p[0] <= win[1]]
            out[k] = [(win[0], before[-1][1] if before else pts[0][1])] + inside
        return out

    due0 = ev["due"][0]
    draw(clip(w1), ["c_clk", "port_we (E0i)", "c_fifo_wave_push_s[0] (E0)", "t_clk",
                    "t_fifo_wave_empty[0] (E1)", "t_time_abs_o"],
         w1, [(ev["E0i"][0], "E0i", "tab:green"), (ev["E0"][0], "E0 (+1 c_clk)", "tab:green"),
              (ev["E1"][0], "E1 (on timeline)", "tab:purple")],
         f"Acceptance, command 0: issue -> dispatcher FIFO -> visible on t_clk side (due = {due0})",
         os.path.join(run_dir, "wave_1_acceptance.png"), bus_labels=("t_time_abs_o",))

    abs_series = clip(w2)["t_time_abs_o"]
    t_due_cross = next(t for t, v in abs_series if v == due0 + 1)
    draw(clip(w2), ["t_clk", "t_time_abs_o", "wave_t_gr_r[0]", "wave_pop[0]", "m0 tvalid (E2)", "m0 tready"],
         w2, [(t_due_cross, f"time_abs > {due0}", "tab:orange"),
              (ev["E2"][0], f"E2 sampled, time_abs = {ev['e2_abs'][0]} (due+{ev['e2_abs'][0] - due0})", "tab:red")],
         f"Release decision, command 0: strict compare -> pop -> tvalid (release offset = +{ev['e2_abs'][0] - due0} t_clk)",
         os.path.join(run_dir, "wave_2_release.png"), bus_labels=("t_time_abs_o",))

    marks3 = [(ev["E2"][0], "E2", "tab:red"), (ev["E3"][0], "E3", "tab:purple"),
              (ev["E4"][0], "E4 cmd0", "tab:green"), (ev["E5"][0], "E5 rise", "tab:brown"),
              (ev["E4"][1], "E4 cmd1 (+60)", "tab:green"), (ev["E4"][2], "E4 cmd2 (+60)", "tab:green"),
              (ev["E5"][1], "E5 fall (180 = 3x60)", "tab:brown")]
    draw(clip(w3), ["m0 tvalid (E2)", "sgt0 tvalid (E3)", "load_int (E4)", "en_o (E5)"],
         w3, marks3,
         "Commands 0-2 (same due): E2 x3 released 4 t_clk apart -> E3 -> chained at nsamp=60 -> one 180 sg_clk burst",
         os.path.join(run_dir, "wave_3_chain.png"))

    write_gtkw(run_dir, w2)
    print("wrote", *(os.path.join(run_dir, f) for f in
                     ("wave_1_acceptance.png", "wave_2_release.png", "wave_3_chain.png", "waveform_view.gtkw")),
          sep="\n  ")


if __name__ == "__main__":
    main()
