#!/usr/bin/env python3
"""Analyze QICK controller-level timing events logged by timing_monitors.svh.

Usage:
    timing_analyze.py <run_dir>                 one run -> timing_report.csv + timing_summary.txt
    timing_analyze.py --sweep <run_dir> ...     same test at several PRE_RUN_DELAY_NS values

Events (see verification/timing/timing_reference.txt):
    E0i issue -> E0 schedule -> E1 on timeline -> E2 release
    -> E3 SGv6 accept -> E4 SGv6 load -> E5 output burst edges

Commands are matched across layers by position within one wave port (every
stage is an in-order FIFO), then checked by their field fingerprint
(nsamp, gain, addr, phase, freq). A fingerprint mismatch is an ordering error.

Standard library only.
"""

import argparse
import csv
import os
import statistics
import sys


FIELDS = ("nsamp", "gain", "addr", "phase", "freq")


def read_csv(run_dir, name):
    path = os.path.join(run_dir, name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"missing {path}")
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def read_meta(run_dir):
    return {r["key"]: r["value"] for r in read_csv(run_dir, "ev_meta.csv")}


def signed32(v):
    v = int(v)
    return v - (1 << 32) if v >= (1 << 31) else v


def fingerprint(row):
    # SGv6 carries 16-bit gain/addr; the tProc side carries wider fields.
    return (
        int(row["nsamp"]),
        int(row["gain"], 16) & 0xFFFF,
        int(row["addr"], 16) & 0xFFFF,
        int(row["phase"], 16),
        int(row["freq"], 16),
    )


def load_run(run_dir, port):
    meta = read_meta(run_dir)
    # SG0 (wave port 0) logs to ev_e*.csv; SG1 (wave port 1) to ev_sg1_e*.csv.
    pre = "ev_" if port == 0 else f"ev_sg{port}_"
    ev = {
        "E0i": [r for r in read_csv(run_dir, "ev_e0i_issue.csv") if int(r["p_addr"]) == port],
        "E0": [r for r in read_csv(run_dir, "ev_e0_sched.csv") if int(r["port"]) == port],
        "E1": read_csv(run_dir, pre + "e1_timeline.csv"),
        "E2": read_csv(run_dir, pre + "e2_tproc_out.csv"),
        "E3": read_csv(run_dir, pre + "e3_sg_in.csv"),
        "E4": read_csv(run_dir, pre + "e4_sg_load.csv"),
        "E5": read_csv(run_dir, pre + "e5_sg_en.csv"),
        "flags": read_csv(run_dir, "ev_flags.csv"),
    }
    return meta, ev


def align(ev):
    """Align E2/E3/E4 rows to E0 commands; report losses, duplicates, reordering.

    With unique fingerprints each layer row is matched to its E0 command by
    fingerprint, so a lost or duplicated command does not shift the others.
    Otherwise rows are matched by position (every stage is an in-order FIFO).
    Returns (aligned {layer: [row or None per command]}, integrity dict, unique).
    """
    ref = [fingerprint(r) for r in ev["E0"]]
    unique = len(set(ref)) == len(ref)
    index = {fp: k for k, fp in enumerate(ref)}
    aligned, integrity = {"E0i": ev["E0i"]}, {}
    for layer in ("E2", "E3", "E4"):
        rows = ev[layer]
        slots = [None] * len(ref)
        dups, unknown, order = 0, 0, []
        if unique:
            for r in rows:
                k = index.get(fingerprint(r))
                if k is None:
                    unknown += 1          # e.g. an all-zero command
                elif slots[k] is not None:
                    dups += 1
                else:
                    slots[k] = r
                    order.append(k)
        else:
            for k, r in enumerate(rows[:len(ref)]):
                if fingerprint(r) == ref[k]:
                    slots[k] = r
                    order.append(k)
                else:
                    unknown += 1
            unknown += max(0, len(rows) - len(ref))
        integrity[layer] = {
            "rows": len(rows), "lost": sum(s is None for s in slots),
            "duplicates": dups, "unknown": unknown,
            "reordered": any(b < a for a, b in zip(order, order[1:])),
        }
        aligned[layer] = slots
    return aligned, integrity, unique


def integrity_errors(integrity):
    errs = []
    for layer, i in integrity.items():
        bad = {k: v for k, v in i.items() if k in ("lost", "duplicates", "unknown") and v}
        if bad or i["reordered"]:
            errs.append(f"{layer}: " + ", ".join(f"{k}={v}" for k, v in bad.items())
                        + (" REORDERED" if i["reordered"] else ""))
    return errs


def classify_e1(ev):
    """Split E1 rows into true arrivals and head refills.

    In the Verilator BRAM_FIFO_DC_2 variant the empty flag blips for a cycle
    after every pop while the next head is fetched, so E1 also fires on
    refills. A row within 4 t_clk after a pop is a refill.
    """
    pops = [int(r["pop_t_cyc"]) for r in ev["E2"]]
    arrivals, refills = [], []
    for r in ev["E1"]:
        t = int(r["t_cyc"])
        (refills if any(0 < t - p <= 4 for p in pops) else arrivals).append(r)
    return arrivals, refills


def analyze(run_dir, port=0):
    meta, ev = load_run(run_dir, port)
    t_ps = float(meta["t_clk_period_ps"])
    sg_ps = float(meta["sg_clk_period_ps"])
    n = len(ev["E0"])

    aligned, integrity, unique_fp = align(ev)
    order_errors = integrity_errors(integrity)
    arrivals, refills = classify_e1(ev)
    E2, E3, E4 = aligned["E2"], aligned["E3"], aligned["E4"]

    def prev(layer, k):
        """Nearest earlier command that exists at this layer."""
        for j in range(k - 1, -1, -1):
            if layer[j] is not None:
                return layer[j]
        return None

    # Commands that entered an empty FIFO get a true E1 (in order).
    entered_empty = []
    for k in range(n):
        t_e0 = float(ev["E0"][k]["time_ps"])
        p1 = prev(E2, k)
        entered_empty.append(p1 is None or float(p1["time_ps"]) < t_e0)
    arrival_iter = iter(arrivals)
    e1_for = {k: next(arrival_iter, None) for k in range(n) if entered_empty[k]}

    rows = []
    for k in range(n):
        e0i, e0, e2, e3, e4 = ev["E0i"][k], ev["E0"][k], E2[k], E3[k], E4[k]
        due = int(e0["due"])
        e1 = e1_for.get(k)
        row = {
            "k": k,
            "fingerprint_gain": f"{int(e0['gain'], 16) & 0xFFFF:04x}",
            "nsamp": int(e0["nsamp"]),
            "due_tclk": due,
            "p_time": int(e0i["p_time"]),
            "lead_at_issue_tclk": int(e0i["p_time"]) - signed32(e0i["c_time_usr"]),
            "accept_cclk": int(e0["c_cyc"]) - int(e0i["c_cyc"]),
            "lead_at_timeline_tclk": (due - int(e1["t_time_abs"])) if e1 else "",
            "status": ("lost@E2" if e2 is None else "lost@E3" if e3 is None
                       else "lost@E4" if e4 is None else "ok"),
            "release_kind": "", "release_offset_tclk": "", "compare_to_pop_tclk": "",
            "release_spacing_tclk": "", "transport_ps": "", "transport_sgclk": "",
            "queue_wait_sgclk": "", "start_spacing_sgclk": "", "due_to_start_ns": "",
            "chained": False,
        }
        if e2 is not None:
            t_abs_e2 = int(e2["t_time_abs"])
            p1 = prev(E2, k)
            # Queued: its due time had already passed when the previous command released.
            queued = p1 is not None and due < int(p1["t_time_abs"])
            row.update({
                "release_kind": "queued" if queued else "head",
                "release_offset_tclk": t_abs_e2 - due,
                # Only meaningful for a head release; a queued entry inherits the
                # previous head's compare-rise cycle.
                "compare_to_pop_tclk": "" if queued else int(e2["pop_t_cyc"]) - int(e2["gr_rise_t_cyc"]),
                "release_spacing_tclk": (int(e2["t_cyc"]) - int(p1["t_cyc"])) if p1 else "",
            })
        if e2 is not None and e3 is not None:
            d13 = float(e3["time_ps"]) - float(e2["time_ps"])
            row.update({"transport_ps": round(d13, 3), "transport_sgclk": round(d13 / sg_ps, 3)})
        if e3 is not None and e4 is not None:
            row["queue_wait_sgclk"] = int(e4["sg_cyc"]) - int(e3["sg_cyc"])
        if e4 is not None:
            p4 = prev(E4, k)
            row["start_spacing_sgclk"] = (int(e4["sg_cyc"]) - int(p4["sg_cyc"])) if p4 else ""
            if e2 is not None:
                # Wall-clock moment time_abs == due, anchored on the E2 sample.
                due_ps = float(e2["time_ps"]) - (int(e2["t_time_abs"]) - due) * t_ps
                row["due_to_start_ns"] = round((float(e4["time_ps"]) - due_ps) / 1000.0, 3)
            prev_nsamp = int(ev["E0"][k - 1]["nsamp"]) if k else None
            # Chained: started exactly when the previous pulse ended (gapless),
            # whether it waited in the SGv6 FIFO or arrived just in time (T4).
            row["chained"] = bool(k and row["start_spacing_sgclk"] == prev_nsamp)
        rows.append(row)

    bursts = check_bursts(E4, ev["E5"], rows)
    flags = classify_flags(ev["flags"], meta)
    return {
        "run_dir": run_dir, "meta": meta, "rows": rows, "bursts": bursts, "flags": flags,
        "order_errors": order_errors, "unique_fp": unique_fp, "integrity": integrity,
        "e1_arrivals": len(arrivals), "e1_refills": len(refills),
    }


def check_bursts(E4, E5, rows):
    """Group chained commands into output bursts and match them to E5 edges."""
    groups = []
    for r in rows:
        if E4[r["k"]] is None:
            continue
        if r["chained"] and groups:
            groups[-1].append(r["k"])
        else:
            groups.append([r["k"]])
    rises = [e for e in E5 if e["edge"] == "rise"]
    falls = [e for e in E5 if e["edge"] == "fall"]
    out = []
    for i, g in enumerate(groups):
        exp_len = sum(rows[k]["nsamp"] for k in g)
        rise = rises[i] if i < len(rises) else None
        fall = falls[i] if i < len(falls) else None
        e4_first = int(E4[g[0]]["sg_cyc"])
        out.append({
            "burst": i, "commands": g, "expected_len_sgclk": exp_len,
            "pipeline_sgclk": (int(rise["sg_cyc"]) - e4_first) if rise else None,
            "len_sgclk": (int(fall["sg_cyc"]) - int(rise["sg_cyc"])) if rise and fall else None,
        })
    return out


def classify_flags(flags, meta):
    """some_fifo_full pulses at reset or program start are FIFO clears, not stalls."""
    start_ps = float(meta.get("proc_start_time_ps", "0"))
    out = []
    for f in flags:
        kind = f["kind"]
        t = float(f["time_ps"])
        if kind.startswith("some_fifo_full") and (int(f["cyc"]) < 20 or abs(t - start_ps) < 100_000):
            kind += " (fifo clear, benign)"
        out.append((t, f["domain"], kind))
    return out


def stats(values):
    vals = [v for v in values if v != "" and v is not None]
    if not vals:
        return "n/a"
    lo, hi = min(vals), max(vals)
    if lo == hi:
        return f"{lo} (constant, n={len(vals)})"
    return f"min {lo}  max {hi}  mean {statistics.mean(vals):.3f}  (n={len(vals)})"


def summary_text(res):
    rows = res["rows"]
    heads = [r for r in rows if r["release_kind"] == "head"]
    queued = [r for r in rows if r["release_kind"] == "queued"]
    idle = [r for r in rows if not r["chained"] and r["queue_wait_sgclk"] != ""]
    lines = [
        f"QICK timing summary: {res['run_dir']}",
        f"pre_run_delay_ns={res['meta'].get('pre_run_delay_ns')}  "
        f"t_clk={res['meta']['t_clk_period_ps']} ps  sg_clk={res['meta']['sg_clk_period_ps']} ps  "
        f"c_clk={res['meta']['c_clk_period_ps']} ps",
        f"commands on port: {len(rows)}   E1 arrivals {res['e1_arrivals']}, head refills {res['e1_refills']}",
        "",
        "ORDERING AND INTEGRITY (every E0 command delivered once, in order)",
        "  " + ("PASS: every command reached E2, E3, E4 exactly once, in E0 order"
                if not res["order_errors"] else "FAIL: " + "; ".join(res["order_errors"])),
        "  fingerprints unique: " + ("yes" if res["unique_fp"] else
                                     "NO (repeated fields; matched by position + full field set)"),
        "",
        "ACCEPTANCE",
        f"  core acceptance E0-E0i [c_clk]        : {stats([r['accept_cclk'] for r in rows])}",
        f"  lead at issue (due - user time) [t_clk]: {stats([r['lead_at_issue_tclk'] for r in rows])}",
        f"  lead at timeline (true E1) [t_clk]    : {stats([r['lead_at_timeline_tclk'] for r in rows])}",
        "",
        "START",
        f"  release offset, head [t_clk]          : {stats([r['release_offset_tclk'] for r in heads])}",
        f"  release offset, queued [t_clk]        : {stats([r['release_offset_tclk'] for r in queued])}",
        f"  compare-rise -> pop [t_clk]           : {stats([r['compare_to_pop_tclk'] for r in heads])}",
        f"  release spacing, queued [t_clk]       : {stats([r['release_spacing_tclk'] for r in queued])}",
        f"  transport E3-E2 [ps]                  : {stats([r['transport_ps'] for r in rows])}",
        f"  transport E3-E2 [sg_clk]              : {stats([r['transport_sgclk'] for r in rows])}",
        f"  queue wait E4-E3, SG idle [sg_clk]    : {stats([r['queue_wait_sgclk'] for r in idle])}",
        f"  due -> SG start, head+idle [ns]       : {stats([r['due_to_start_ns'] for r in heads if not r['chained']])}",
        "",
        "OUTPUT BURSTS (E5)",
    ]
    for b in res["bursts"]:
        ok = b["len_sgclk"] == b["expected_len_sgclk"]
        lines.append(f"  burst {b['burst']}: cmds {b['commands']}  E5rise-E4 = {b['pipeline_sgclk']} sg_clk  "
                     f"length {b['len_sgclk']} vs sum(nsamp) {b['expected_len_sgclk']}  "
                     f"{'OK' if ok else 'MISMATCH'}")
    stall = core_stall(res["flags"])
    lines += ["", "CORE ACCEPTANCE STALL (dispatcher FIFO full -> core_en=0)",
              f"  {stall[0]} interval(s), total {stall[1]:.1f} ns" if stall[0] else "  none"]
    lines += ["", "FLAGS (count, first..last)"]
    groups = {}
    for t, d, k in res["flags"]:
        groups.setdefault((d, k), []).append(t)
    lines += [f"  {d:<6} {k:<45} x{len(ts):<6} {min(ts):.0f}..{max(ts):.0f} ps"
              for (d, k), ts in groups.items()] or ["  none"]
    return "\n".join(lines)


def core_stall(flags):
    """(count, total ns) of non-benign some_fifo_full intervals."""
    rises = [t for t, _, k in flags if k == "some_fifo_full_rise"]
    falls = [t for t, _, k in flags if k == "some_fifo_full_fall"]
    return len(rises), sum(f - r for r, f in zip(rises, falls)) / 1000.0


def brief(res):
    """One line per run for the suite overview."""
    rows = res["rows"]
    heads = [r for r in rows if r["release_kind"] == "head"]
    idle = [r for r in heads if not r["chained"] and r["due_to_start_ns"] != ""]
    rng = lambda v: (f"{min(v)}" if min(v) == max(v) else f"{min(v)}..{max(v)}") if v else "-"
    kinds = {}
    for _, _, k in res["flags"]:
        if "benign" not in k:
            kinds[k] = kinds.get(k, 0) + 1
    bursts_ok = all(b["len_sgclk"] == b["expected_len_sgclk"] for b in res["bursts"])
    return (f"{os.path.relpath(res['run_dir']):<22} n={len(rows):<4} "
            f"integrity={'PASS' if not res['order_errors'] else 'FAIL[' + '; '.join(res['order_errors']) + ']'} "
            f"accept={rng([r['accept_cclk'] for r in rows])} "
            f"rel_head={rng([r['release_offset_tclk'] for r in heads])} "
            f"queued={sum(r['release_kind'] == 'queued' for r in rows)} "
            f"E3-E2={rng([round(r['transport_sgclk'], 2) for r in rows if r['transport_sgclk'] != ''])} "
            f"wait_idle={rng([r['queue_wait_sgclk'] for r in idle])} "
            f"due->start={rng([r['due_to_start_ns'] for r in idle])}ns "
            f"bursts={len(res['bursts'])}{'' if bursts_ok else '(MISMATCH)'} "
            f"core_stall={core_stall(res['flags'])[0]}x/{core_stall(res['flags'])[1]:.0f}ns "
            f"flags={kinds or 'none'}")


def write_report(res):
    path = os.path.join(res["run_dir"], "timing_report.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(res["rows"][0].keys()))
        w.writeheader()
        w.writerows(res["rows"])
    text = summary_text(res)
    with open(os.path.join(res["run_dir"], "timing_summary.txt"), "w") as f:
        f.write(text + "\n")
    return path, text


def sweep(run_dirs, port):
    """Per-command spread of each metric across runs (e.g. PRE_RUN_DELAY_NS sweep)."""
    results = [analyze(d, port) for d in run_dirs]
    metrics = ("release_offset_tclk", "transport_ps", "queue_wait_sgclk", "due_to_start_ns")
    print(f"SWEEP over {len(results)} runs: " +
          ", ".join(f"{os.path.basename(r['run_dir'].rstrip('/'))}(d={r['meta'].get('pre_run_delay_ns')})"
                    for r in results))
    n = min(len(r["rows"]) for r in results)
    for m in metrics:
        spreads = []
        for k in range(n):
            vals = [r["rows"][k][m] for r in results]
            spreads.append(max(vals) - min(vals))
        print(f"  {m:<22} max spread across runs: {max(spreads):.3f}   per-command: {spreads}")


def cross(run_dir):
    """SG0 vs SG1 for commands with the same due time (shared SG CDC FIFO)."""
    a, b = analyze(run_dir, 0), analyze(run_dir, 1)
    meta = a["meta"]
    sg_ps = float(meta["sg_clk_period_ps"])
    ev0, ev1 = load_run(run_dir, 0)[1], load_run(run_dir, 1)[1]
    rise = lambda ev: [float(e["time_ps"]) for e in ev["E5"] if e["edge"] == "rise"]
    print(f"CROSS-PORT {run_dir}: SG0 integrity {'PASS' if not a['order_errors'] else a['order_errors']}, "
          f"SG1 integrity {'PASS' if not b['order_errors'] else b['order_errors']}")
    by_due = {}
    for port, res, ev in ((0, a, ev0), (1, b, ev1)):
        for r in res["rows"]:
            by_due.setdefault(r["due_tclk"], {})[port] = (r, ev, r["k"])
    for due, d in sorted(by_due.items()):
        if 0 not in d or 1 not in d:
            continue
        (r0, e0, k0), (r1, e2, k1) = d[0], d[1]
        t = lambda ev, layer, k: float(ev[layer][k]["time_ps"])
        print(f"  due {due}: release SG0 +{r0['release_offset_tclk']} / SG1 +{r1['release_offset_tclk']} t_clk; "
              f"E2 skew {(t(e2,'E2',k1)-t(e0,'E2',k0))/1000:+.3f} ns; "
              f"E3 skew {(t(e2,'E3',k1)-t(e0,'E3',k0))/sg_ps:+.2f} sg_clk; "
              f"E4 skew {(t(e2,'E4',k1)-t(e0,'E4',k0))/sg_ps:+.2f} sg_clk; "
              f"E5 rise skew {(rise(e2)[0]-rise(e0)[0])/sg_ps:+.2f} sg_clk; "
              f"due->start SG0 {r0['due_to_start_ns']} / SG1 {r1['due_to_start_ns']} ns")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--port", type=int, default=0, help="tProc wave port (0 = SG0)")
    ap.add_argument("--sweep", action="store_true", help="compare the same test across runs")
    ap.add_argument("--brief", action="store_true", help="one summary line per run (no files written)")
    ap.add_argument("--cross", action="store_true", help="SG0 vs SG1 skew for equal due times")
    args = ap.parse_args()

    if args.sweep:
        sweep(args.run_dirs, args.port)
        return 0
    if args.cross:
        for d in args.run_dirs:
            cross(d)
        return 0
    if args.brief:
        for d in args.run_dirs:
            print(brief(analyze(d, args.port)))
        return 0
    status = 0
    for d in args.run_dirs:
        res = analyze(d, args.port)
        path, text = write_report(res)
        print(text)
        print(f"\nwrote {path}")
        status |= bool(res["order_errors"])
    return status


if __name__ == "__main__":
    sys.exit(main())
