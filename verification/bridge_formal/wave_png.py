#!/usr/bin/env python3
"""Render SymbiYosys counterexample/cover traces of the WaveWordBridge suite as PNG waveforms.

Run with a Python that has matplotlib (e.g. ~/projects/HRL_clinic/.venv/bin/python):
    python wave_png.py                 # all figures below -> waves/<name>.png
    python wave_png.py p7 p6_k10       # selected figures

One column per solver step (= one clock cycle). Values are taken at the start of each step.
"""
import pathlib
import sys

LEAD = 32   # must match bridge_formal.sv / WaveWordBridge.v

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = pathlib.Path(__file__).resolve().parent

# name: (trace, title, signals, note)
# signal = (label, vcd path "scope.name", kind) with kind "bit", "dec", "hex", or a callable on the raw int
NSAMP = lambda v: v >> 120 & 0xFFFFFFFF
FIGS = {
    "p7": ("bridge_p7/engine_0/trace.vcd",
           "P7 FAIL: word lost when the consumer is not ready on the release cycle",
           [("cyc", "bridge_formal.cyc", "dec"),
            ("reset", "bridge_formal.reset", "bit"),
            ("fire (CPU writes 0x1c)", "bridge_formal.fire", "bit"),
            ("startTime of fired word", "bridge_formal.sh_start", "fired"),
            ("io_time", "bridge_formal.time_ctr", "dec"),
            ("io_wave_valid", "bridge_formal.wave_valid", "bit"),
            ("io_wave_ready", "bridge_formal.wave_ready", "bit"),
            ("handshake", "bridge_formal.o_hs", "bit"),
            ("words fired", "bridge_formal.n_w", "dec"),
            ("words delivered", "bridge_formal.n_hs", "dec")],
           "valid is a 1-cycle pulse at startTime-LEAD; ready is low on that cycle, valid drops next cycle "
           "without a handshake -> the word never reaches SGv6 (AXIS rule: valid must hold until ready)."),
    "p6_k10": ("bridge_p6_k10/engine_0/trace.vcd",
               "P6 FAIL: 10th pending fire is silently dropped (capacity 9)",
               [("cyc", "bridge_formal.cyc", "dec"),
                ("fire (CPU writes 0x1c)", "bridge_formal.fire", "bit"),
                ("words fired", "bridge_formal.n_w", "dec"),
                ("queue push.ready", "bridge_formal.dut.q_io_push_ready", "bit"),
                ("io_wave_valid", "bridge_formal.wave_valid", "bit"),
                ("words delivered", "bridge_formal.n_hs", "dec")],
               "push.ready drops after 9 accepted fires (8 FIFO + 1 head stage); the bridge drives "
               "push.valid from the fire strobe and ignores ready, so the 10th fire is lost with no error."),
    "b4": ("bridge_b4/engine_0/trace.vcd",
           "B4 FAIL: nsamp < 3 passes straight through to SGv6",
           [("cyc", "bridge_formal.cyc", "dec"),
            ("fire", "bridge_formal.fire", "bit"),
            ("io_wave_valid", "bridge_formal.wave_valid", "bit"),
            ("word nsamp [151:120]", "bridge_formal.wave_data", NSAMP)],
           "The bridge forwards any nsamp. SGv6 plays ~65536 cycles for nsamp 0/1 (finding F9)."),
    "p2_m0": ("bridge_p2_m0/engine_0/trace.vcd",
              "P2: fired only LEAD = 32 cycles ahead (margin 0) -> word released late",
              [("cyc", "bridge_formal.cyc", "dec"),
               ("fire", "bridge_formal.fire", "bit"),
               ("startTime of fired word", "bridge_formal.sh_start", "fired"),
               ("io_time", "bridge_formal.time_ctr", "dec"),
               ("io_wave_valid", "bridge_formal.wave_valid", "bit"),
               ("words delivered", "bridge_formal.n_hs", "dec")],
              "Red band = due release (io_time = startTime - LEAD, LEAD = 32). With less than LEAD+3 = 35 cycles of lead the TimedQueue "
              "pops late (1 cycle late per missing cycle, up to 3). Never early."),
    "p4_g0": ("bridge_p4_g0/engine_0/trace.vcd",
              "P4: startTimes closer than 2 cycles -> later words slip (queue pops every 2 cycles)",
              [("cyc", "bridge_formal.cyc", "dec"),
               ("fire", "bridge_formal.fire", "bit"),
               ("startTime of fired word", "bridge_formal.sh_start", "fired"),
               ("io_time", "bridge_formal.time_ctr", "dec"),
               ("io_wave_valid", "bridge_formal.wave_valid", "bit"),
               ("words fired", "bridge_formal.n_w", "dec"),
               ("words delivered", "bridge_formal.n_hs", "dec")],
              "Red bands = due release of each word. Words due < 2 cycles apart cannot all pop on time "
              "(TimedQueue pops at most every 2 cycles), so later ones come out late."),
    "p3": ("bridge_p3/engine_0/trace.vcd",
           "P3: startTimes fired out of order -> head-of-line blocking",
           [("cyc", "bridge_formal.cyc", "dec"),
            ("fire", "bridge_formal.fire", "bit"),
            ("startTime of fired word", "bridge_formal.sh_start", "fired"),
            ("io_time", "bridge_formal.time_ctr", "dec"),
            ("io_wave_valid", "bridge_formal.wave_valid", "bit"),
            ("words delivered", "bridge_formal.n_hs", "dec")],
           "Word 2 is due earlier than word 1 but was fired after it; it waits behind word 1 at the head of the "
           "FIFO and comes out late (same behaviour as tProc's head-only wave FIFO)."),
    "cov": ("bridge_cov/engine_0/trace1.vcd",
            "Cover (PASS): two words released back to back, exactly on time",
            [("cyc", "bridge_formal.cyc", "dec"),
             ("fire", "bridge_formal.fire", "bit"),
             ("startTime of fired word", "bridge_formal.sh_start", "fired"),
             ("io_time", "bridge_formal.time_ctr", "dec"),
             ("io_wave_valid", "bridge_formal.wave_valid", "bit"),
             ("words delivered", "bridge_formal.n_hs", "dec")],
            "Reference picture of correct behaviour: each word out at io_time = startTime-LEAD."),
}


def parse_vcd(path, wanted):
    """Return {path: [value per step]} for the wanted hierarchical names."""
    ids, scope, cur, steps = {}, [], {}, []
    step_id = None
    with open(path) as f:
        for line in f:
            tok = line.split()
            if not tok:
                continue
            if tok[0] == "$scope":
                scope.append(tok[2])
            elif tok[0] == "$upscope":
                scope.pop()
            elif tok[0] == "$var":
                name = ".".join(scope + [tok[4]])
                if tok[4] == "smt_step" and not scope:
                    step_id = tok[3]
                if name in wanted:
                    ids.setdefault(tok[3], []).append(name)
            elif tok[0][0] == "b" and len(tok) > 1:
                val = int(tok[0][1:].replace("x", "0").replace("z", "0"), 2)
                if tok[1] == step_id:
                    steps.append(dict(cur))
                for n in ids.get(tok[1], []):
                    cur[n] = val
            elif tok[0][0] in "01xz" and len(tok[0]) > 1:
                for n in ids.get(tok[0][1:], []):
                    cur[n] = 1 if tok[0][0] == "1" else 0
    steps = steps[1:]          # entry i = values just before step i+1 starts, i.e. during step i
    return {n: [s.get(n, 0) for s in steps] for n in wanted}


def render(name):
    trace, title, sigs, note = FIGS[name]
    vcd = HERE / trace
    if not vcd.exists():
        print(f"skip {name}: {vcd} not found (run ./run_all.sh first)")
        return
    data = parse_vcd(vcd, {p for _, p, _ in sigs} | {"bridge_formal.fire", "bridge_formal.sh_start",
                                                      "bridge_formal.time_ctr"})
    fire, start, tim = (data["bridge_formal.fire"], data["bridge_formal.sh_start"],
                        data["bridge_formal.time_ctr"])
    # Due release step of each fired word: io_time == startTime - 8.
    dues = []
    for i, f in enumerate(fire):
        if f:
            due = [k for k, t in enumerate(tim) if t == start[i] - LEAD]
            dues.append((len(dues) + 1, due[0] if due else None, start[i]))
    n = len(next(iter(data.values())))
    fig, ax = plt.subplots(figsize=(max(8, 0.55 * n + 3), 0.55 * len(sigs) + 1.6))
    for row, (label, path, kind) in enumerate(sigs):
        y = len(sigs) - 1 - row
        vals = data[path]
        if kind == "fired":
            for i, v in enumerate(vals):
                if fire[i]:
                    ax.text(i + 0.5, y + 0.4, str(v), ha="center", va="center", fontsize=8,
                            bbox=dict(boxstyle="round,pad=0.2", fc="#fff3e0", ec="#eb6834"))
        elif kind == "bit":
            xs, ys = [], []
            for i, v in enumerate(vals):
                xs += [i, i + 1]
                ys += [y + 0.1 + 0.6 * v] * 2
            ax.plot(xs, ys, color="#2a78d6", lw=1.8)
        else:
            fmt = (lambda v: str(v)) if kind == "dec" else (lambda v: hex(v)) if kind == "hex" else (lambda v, k=kind: str(k(v)))
            start = 0
            for i in range(1, n + 1):
                if i == n or vals[i] != vals[start]:
                    ax.add_patch(plt.Polygon([(start + .08, y + .4), (start + .2, y + .7), (i - .2, y + .7),
                                              (i - .08, y + .4), (i - .2, y + .1), (start + .2, y + .1)],
                                             closed=True, fill=False, ec="#555", lw=1))
                    ax.text((start + i) / 2, y + 0.4, fmt(vals[start]), ha="center", va="center", fontsize=8)
                    start = i
        ax.text(-0.3, y + 0.4, label, ha="right", va="center", fontsize=9)
    for i in range(n + 1):
        ax.axvline(i, color="#ddd", lw=0.5, zorder=0)
    by_step = {}
    for k, step, st in dues:
        if step is not None and step < n:
            by_step.setdefault(step, []).append(f"w{k}")
    for step, ws in by_step.items():
        ax.axvspan(step, step + 1, color="#d62728", alpha=0.10, zorder=0)
        ax.text(step + 0.5, len(sigs) - 0.05, "due " + ",".join(ws), ha="center", va="bottom",
                fontsize=7, color="#d62728")
    ax.set_xlim(-0.1, n + 0.1)
    ax.set_ylim(-0.2, len(sigs))
    ax.set_xticks([i + 0.5 for i in range(n)])
    ax.set_xticklabels([str(i) for i in range(n)], fontsize=7)
    ax.set_xlabel("solver step (clock cycle, 2 ns at 500 MHz)", fontsize=9)
    ax.set_yticks([])
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.set_title(title, fontsize=11, loc="left")
    fig.text(0.01, 0.01, note, fontsize=8, wrap=True, va="bottom")
    fig.subplots_adjust(left=0.24, right=0.98, top=0.9, bottom=0.22)
    out = HERE / "waves" / f"{name}.png"
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"{name}: {out.relative_to(HERE)}  ({n} steps)")


if __name__ == "__main__":
    for nm in (sys.argv[1:] or FIGS):
        render(nm)
