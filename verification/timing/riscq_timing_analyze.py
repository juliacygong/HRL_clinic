#!/usr/bin/env python3
"""Analyze native RISC-Q timing events logged by risc-q/.../TimingSocCpuSim.scala.

Usage:
    riscq_timing_analyze.py <run_dir> [--ch 0|1]   -> riscq_timing_report.csv + riscq_timing_summary.txt

Event ladder (dspCd cycles; `ch_time` = the channel's local batch-time copy that its
TimedQueues compare against, so due/offsets are measured in that base):
    E0i CPU posted store to the channel's fire register (riscvSoc.cmd)
    E0  fire decoded by the channel's PulseParamBuffer
    E1  dur TimedQueue push, due = startTime captured at push
    E2  dur TimedQueue pop (other five queues' pop cycles alongside)
    E5  generator output valid rise / fall
No E3/E4: native RISC-Q has no SGv6 input FIFO / load stage.

Only events after the final reset release (ev_meta.csv final_release_cyc) are analyzed;
pre-release traffic is counted separately. Commands are matched by position per channel
(every stage is in order); the E1 amp/dur fields are reported as the fingerprint.

Standard library only.
"""

import argparse
import csv
import json
import os
import sys

QUEUES = ("amp", "phase", "freqC", "freqP", "addr", "dur")
# Nominal pop lead of each TimedQueue relative to the output-start cycle, measured on an on-time
# isolated pulse (P1_T1): the parameter popped this many cycles early is the one in effect when the
# output starts. The output rises 2 cycles after the dur pop.
NOMINAL_LEAD = {"amp": -34, "phase": -35, "freqC": -36, "freqP": -52, "addr": -11, "dur": -2}


def read_csv(run_dir, name):
    with open(os.path.join(run_dir, name), newline="") as f:
        return list(csv.DictReader(f))


def analyze(run_dir, ch=0):
    meta = {r["key"]: r["value"] for r in read_csv(run_dir, "ev_meta.csv")}
    # analysis window: first release after the host's release write (window_start_cyc);
    # older runs only have final_release_cyc.
    rel = int(meta.get("window_start_cyc", meta["final_release_cyc"]))
    load = lambda name: [r for r in read_csv(run_dir, name) if int(r["ch"]) == ch]
    ev = {k: load(f) for k, f in (("E0i", "ev_e0i_issue.csv"), ("E0", "ev_e0_sched.csv"),
                                   ("E1", "ev_e1_timeline.csv"), ("E2", "ev_e2_release.csv"),
                                   ("E5", "ev_e5_out.csv"))}
    post = {k: [r for r in v if int(r["cyc"]) >= rel] for k, v in ev.items()}
    pre = {k: [r for r in v if int(r["cyc"]) < rel] for k, v in ev.items()}
    rf = read_csv(run_dir, "ev_rfcmd.csv")
    flags = read_csv(run_dir, "ev_flags.csv")

    rises = [r for r in post["E5"] if r["edge"] == "rise"]
    falls = [r for r in post["E5"] if r["edge"] == "fall"]
    n = len(post["E1"])
    counts = {k: len(v) for k, v in post.items()}
    rows = []
    for k in range(n):
        e1 = post["E1"][k]
        e0i = post["E0i"][k] if k < len(post["E0i"]) else None
        e0 = post["E0"][k] if k < len(post["E0"]) else None
        e2 = post["E2"][k] if k < len(post["E2"]) else None
        due = int(e1["due"])
        row = {"k": k, "amp": int(e1["amp"]), "dur": int(e1["dur"]), "due_time": due,
               "accept_cyc": (int(e0["cyc"]) - int(e0i["cyc"])) if e0 and e0i else "",
               "push_cyc": (int(e1["cyc"]) - int(e0["cyc"])) if e0 else "",
               "lead_at_timeline": due - int(e1["ch_time"]),
               "release_offset": "", "pop_leads": "", "start_offset": "", "duration": "",
               "issue_to_start_cyc": ""}
        if e2:
            due_cyc = int(e2["cyc"]) + (due - int(e2["ch_time"]))       # cycle where ch_time == due
            row["release_offset"] = int(e2["ch_time"]) - due
            row["pop_leads"] = " ".join(f"{q}{int(e2[f'pop_{q}_cyc']) - due_cyc:+d}" for q in QUEUES)
        # Output bursts: a pulse whose start equals the previous pulse's end merges into one burst,
        # and an overlapping pulse truncates the previous one (dur counter reload), so rises map to
        # commands only when every command has its own burst.
        if len(rises) == n and k < len(rises):
            row["start_offset"] = int(rises[k]["ch_time"]) - due
            if k < len(falls):
                row["duration"] = int(falls[k]["ch_time"]) - int(rises[k]["ch_time"])
            if e0i:
                row["issue_to_start_cyc"] = int(rises[k]["cyc"]) - int(e0i["cyc"])
        rows.append(row)

    pre_rf = sum(int(r["cyc"]) < rel for r in rf)
    pre_pulses = sum(r["edge"] == "rise" for r in pre["E5"])
    drops = {}
    for f in flags:
        key = ("pre-release " if int(f["cyc"]) < rel else "POST-release ") + f["kind"]
        drops[key] = drops.get(key, 0) + 1
    return {"run_dir": run_dir, "ch": ch, "meta": meta, "rows": rows, "counts": counts,
            "bursts": list(zip(rises, falls)), "pre_rf": pre_rf, "pre_pulses": pre_pulses,
            "pre_fires": len(pre["E0i"]), "drops": drops, "release_cyc": rel}


def rng(vals):
    vals = [v for v in vals if v != ""]
    if not vals:
        return "n/a"
    return f"{min(vals)}" if min(vals) == max(vals) else f"{min(vals)}..{max(vals)}"


def summary(res):
    rows, c = res["rows"], res["counts"]
    ok_counts = len({c["E0i"], c["E0"], c["E1"], c["E2"]}) == 1
    lines = [
        f"RISC-Q timing summary: {res['run_dir']}  channel {res['ch']} ({'gate' if res['ch'] == 0 else 'readout drive'})",
        f"elf={res['meta'].get('elf')}  mode={res['meta'].get('mode', 'powerup')}  abort={res['meta'].get('abort', 'none')}  window starts at cyc {res['release_cyc']}",
        f"post-release counts: E0i {c['E0i']}, E0 {c['E0']}, E1 {c['E1']}, E2 {c['E2']}, "
        f"output bursts {len(res['bursts'])}",
        "",
        "INTEGRITY",
        "  " + ("PASS: every fire reached E0, E1, E2" if ok_counts else f"FAIL: layer counts differ {c}"),
        "",
        "ACCEPTANCE",
        f"  store -> fire decoded E0-E0i [cyc]     : {rng([r['accept_cyc'] for r in rows])}",
        f"  fire -> queue push E1-E0 [cyc]         : {rng([r['push_cyc'] for r in rows])}",
        f"  lead at timeline (due - ch_time) [cyc] : {rng([r['lead_at_timeline'] for r in rows])}",
        "",
        "START",
        f"  dur pop - due [cyc]                    : {rng([r['release_offset'] for r in rows])}",
        f"  per-queue pop lead vs due              : {rows[0]['pop_leads'] if rows else 'n/a'}",
        f"  output rise - due [cyc]                : {rng([r['start_offset'] for r in rows])}",
        f"  output duration vs dur                 : {rng([r['duration'] for r in rows])} vs {rng([r['dur'] for r in rows])}",
        f"  store -> output rise [cyc]             : {rng([r['issue_to_start_cyc'] for r in rows])}",
        "",
        "BEFORE WINDOW (power-up / load traffic; channels are not reset by riscqReset)",
        f"  RfCmds {res['pre_rf']}, fires {res['pre_fires']}, output pulses {res['pre_pulses']}",
        "",
        "QUEUE PUSH DROPS (push.valid && !push.ready; queue depth 4, no backpressure to the CPU)",
    ]
    lines += [f"  {k}: {v}" for k, v in res["drops"].items()] or ["  none"]
    return "\n".join(lines)


def signed16(v):
    v = int(v)
    return v - (1 << 16) if v >= (1 << 15) else v


def probe_checks(run_dir):
    """Per planned pulse (manifest.json from gen_riscq_programs.py) -> what actually happened.

    Pulses are matched by their unique amp fingerprint; a program that runs twice (P8 rerun)
    produces two occurrences per pulse. Returns (rows, attention lines, info lines).
    """
    man_path = os.path.join(run_dir, "manifest.json")
    if not os.path.exists(man_path):
        return [], [], ["no manifest.json: probe checks skipped"]
    man = json.load(open(man_path))
    meta = {r["key"]: r["value"] for r in read_csv(run_dir, "ev_meta.csv")}
    rel = int(meta.get("window_start_cyc", meta["final_release_cyc"]))
    post = lambda name: [r for r in read_csv(run_dir, name) if int(r["cyc"]) >= rel]
    E1, E2, E5, flags = post("ev_e1_timeline.csv"), post("ev_e2_release.csv"), post("ev_e5_out.csv"), post("ev_flags.csv")
    pre5 = [r for r in read_csv(run_dir, "ev_e5_out.csv") if int(r["cyc"]) < rel and r["edge"] == "rise"]
    qlog = None
    if os.path.exists(os.path.join(run_dir, "ev_queue_pop.csv")):
        qlog = {"push": {}, "pop": {}}
        for x in read_csv(run_dir, "ev_queue_push.csv"):
            if x["accepted"] == "1":
                qlog["push"].setdefault((int(x["ch"]), x["queue"]), []).append((int(x["cyc"]), int(x["value"])))
        for x in read_csv(run_dir, "ev_queue_pop.csv"):
            qlog["pop"].setdefault((int(x["ch"]), x["queue"]), []).append((int(x["cyc"]), int(x["value"])))

    rows, attention, info = [], [], []
    chans = sorted({p["ch"] for p in man["pulses"]})
    outputs, starts = {}, {}
    for ch in chans:
        e1 = [r for r in E1 if int(r["ch"]) == ch]
        e2 = [r for r in E2 if int(r["ch"]) == ch]
        e5 = [r for r in E5 if int(r["ch"]) == ch]
        drop_cyc = {int(f["cyc"]) for f in flags if f["kind"] == f"ch{ch}_durQ_push_dropped"}
        accepted = [r for r in e1 if int(r["cyc"]) not in drop_cyc]
        rel_of = {id(r): (e2[i] if i < len(e2) else None) for i, r in enumerate(accepted)}
        rises = [int(r["ch_time"]) for r in e5 if r["edge"] == "rise"]
        falls = [int(r["ch_time"]) for r in e5 if r["edge"] == "fall"]
        intervals = list(zip(rises, falls))
        outputs[ch] = intervals
        # output-start ch_time of every released pulse on this channel (release + 2 = output start)
        starts[ch] = sorted({max(int(r["due"]), int(rel_of[id(r)]["ch_time"]) + 2)
                             for r in accepted if rel_of.get(id(r)) is not None})
        planned = [p for p in man["pulses"] if p["ch"] == ch]
        first = planned[0]
        base_rows = [r for r in e1 if int(r["amp"]) == first["amp"]]
        base = int(base_rows[0]["due"]) - first["start_offset"] if base_rows else None
        used = set()
        for p in planned:
            occ = [r for r in e1 if int(r["amp"]) == p["amp"]] or [None]
            for n, r in enumerate(occ):
                row = {"ch": ch, "k": p["k"], "occurrence": n, "amp": p["amp"], "dur": p["dur"],
                       "planned_due": (base + p["start_offset"]) if base is not None else "",
                       "pushed": r is not None, "captured_due": "", "due_delta": "", "queued": "",
                       "release_offset": "", "pop_leads": "", "paired_amp": "", "paired_freq": "",
                       "out_start_offset": "", "out_covered": "", "status": ""}
                if r is None:
                    row["status"] = "never pushed"; rows.append(row); continue
                due = int(r["due"]); row["captured_due"] = due
                if row["planned_due"] != "":
                    row["due_delta"] = due - row["planned_due"]
                e2r = rel_of.get(id(r))
                row["queued"] = int(r["cyc"]) not in drop_cyc
                status = []
                if not row["queued"]:
                    status.append("DROPPED at dur queue")
                elif e2r is None:
                    status.append("not released in window")
                else:
                    row["release_offset"] = int(e2r["ch_time"]) - due
                    out_cyc = int(e2r["cyc"]) + 2                        # output-start cycle
                    if qlog:
                        # this pulse's own entry in each queue (FIFO: k-th accepted push <-> k-th pop)
                        leads, bad = [], []
                        for q in QUEUES:
                            pushes = qlog["push"].get((ch, q), [])
                            pops = qlog["pop"].get((ch, q), [])
                            if q in ("freqC", "freqP"):
                                # freq entries are pushed by the freq write before the fire
                                cand = [i for i, x in enumerate(pushes) if x[0] <= int(r["cyc"])]
                            else:
                                cand = [i for i, x in enumerate(pushes) if x[0] == int(r["cyc"])]
                            idx = cand[-1] if cand else None
                            if idx is not None and idx < len(pops):
                                lead = pops[idx][0] - out_cyc
                                leads.append(f"{q}{lead:+d}")
                                if lead != NOMINAL_LEAD[q]:
                                    bad.append(f"{q} {lead:+d} (nominal {NOMINAL_LEAD[q]:+d})")
                            else:
                                leads.append(f"{q}?")
                                bad.append(f"{q} entry not popped")
                        row["pop_leads"] = " ".join(leads)
                        # value in effect at output start: last pop at or before out_cyc + nominal lead
                        def effective(q):
                            vals = [v for c, v in qlog["pop"].get((ch, q), []) if c <= out_cyc + NOMINAL_LEAD[q]]
                            return vals[-1] if vals else None
                        eff_amp, eff_freq = effective("amp"), effective("freqC")
                        row["paired_amp"] = eff_amp == p["amp"]
                        row["paired_freq"] = eff_freq == signed16(p["freq16"])
                        if not row["paired_amp"] or not row["paired_freq"]:
                            status.append(f"PAIRING at output start: amp={eff_amp} (want {p['amp']}), "
                                          f"freq={eff_freq} (want {signed16(p['freq16'])})")
                        if bad:
                            status.append("MISALIGNED pops: " + ", ".join(bad))
                    if row["release_offset"] > -2:
                        status.append(f"LATE release (+{row['release_offset'] + 2} cyc)")
                    # output interval covering this pulse: starts at due (or at release if late)
                    start = max(due, int(e2r["ch_time"]) + 2)
                    hit = [(a, b) for a, b in intervals if a <= start < b]
                    if hit:
                        a, b = hit[0]
                        used.add(hit[0])
                        row["out_start_offset"] = a - due if a >= due else f"inside burst from {a - due:+d}"
                        # the dur counter reloads when a later pulse's dur pops, so another pulse
                        # starting inside this window cuts it short even though valid stays high
                        later = [x for x in starts.get(ch, []) if start < x < start + p["dur"]]
                        end = min(b, start + p["dur"], *later) if later else min(b, start + p["dur"])
                        row["out_covered"] = end - start
                        if row["out_covered"] < p["dur"]:
                            status.append(f"TRUNCATED to {row['out_covered']}/{p['dur']}")
                    else:
                        status.append("NO OUTPUT")
                if row["due_delta"] not in ("", 0):
                    status.append(f"due {row['due_delta']:+d} vs planned")
                row["status"] = "; ".join(status) or "ok"
                rows.append(row)
        extra = [iv for iv in intervals if iv not in used]
        if extra:
            attention.append(f"ch{ch}: {len(extra)} output burst(s) not attributable to a single planned pulse "
                             f"(ch_time {extra[:4]})")
        info.append(f"ch{ch}: planned {len(planned)}, pushed {len(e1)}, dur-queue drops {len(drop_cyc)}, "
                    f"released {len(e2)}, output bursts {len(intervals)}")
    # cross-channel alignment for equal planned start offsets
    if len(chans) > 1:
        for p0 in [p for p in man["pulses"] if p["ch"] == chans[0]]:
            for p1 in [p for p in man["pulses"] if p["ch"] == chans[1] and p["start_offset"] == p0["start_offset"]]:
                r0 = [r for r in rows if r["ch"] == chans[0] and r["k"] == p0["k"] and r["captured_due"] != ""]
                r1 = [r for r in rows if r["ch"] == chans[1] and r["k"] == p1["k"] and r["captured_due"] != ""]
                if r0 and r1:
                    e5 = post("ev_e5_out.csv")
                    c0 = [int(r["cyc"]) for r in e5 if int(r["ch"]) == chans[0] and r["edge"] == "rise"]
                    c1 = [int(r["cyc"]) for r in e5 if int(r["ch"]) == chans[1] and r["edge"] == "rise"]
                    skew = (c1[0] - c0[0]) if c0 and c1 else None
                    line = f"cross-channel ch{chans[0]} k{p0['k']} vs ch{chans[1]} k{p1['k']}: output rise skew {skew} cyc"
                    (attention if skew not in (0, None) else info).append(line)
    for r in rows:
        if r["status"] != "ok":
            attention.append(f"ch{r['ch']} pulse {r['k']} (occ {r['occurrence']}): {r['status']}")
    all_drops = {}
    for f in flags:
        all_drops[f["kind"]] = all_drops.get(f["kind"], 0) + 1
    if all_drops:
        attention.append(f"queue push drops in window: {all_drops}")
    if pre5:
        attention.append(f"{len(pre5)} output pulse(s) BEFORE the analysis window (power-up / load traffic)")
    if man["probe"].startswith("P8"):
        n_out = sum(len(v) for v in outputs.values())
        (attention if n_out != len(man["pulses"]) else info).append(
            f"rerun after abort: {n_out} output bursts for {len(man['pulses'])} planned pulses")
    return rows, attention, info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--ch", type=int, default=0, help="0 = gate channel, 1 = readout drive channel")
    a = ap.parse_args()
    res = analyze(a.run_dir, a.ch)
    if res["rows"]:
        with open(os.path.join(a.run_dir, f"riscq_timing_report_ch{a.ch}.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(res["rows"][0].keys()))
            w.writeheader()
            w.writerows(res["rows"])
    text = summary(res)
    prows, attention, info = probe_checks(a.run_dir)
    if prows:
        with open(os.path.join(a.run_dir, "riscq_probe_report.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(prows[0].keys()))
            w.writeheader()
            w.writerows(prows)
    text += "\n\nPROBE CHECKS (planned pulses from manifest.json)\n"
    text += "\n".join("  " + l for l in info)
    text += "\n\nATTENTION\n" + ("\n".join("  - " + l for l in attention) if attention else "  none")
    with open(os.path.join(a.run_dir, f"riscq_timing_summary_ch{a.ch}.txt"), "w") as f:
        f.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
