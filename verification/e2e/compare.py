#!/usr/bin/env python3
"""L1 comparison: pulses a compiled RISC-Q program commands vs the same program on QICK (QICKEmu).

RISC-Q side: runs/<P>/riscq/ev_rfcmd.csv (every CPU -> RF register write, from TimingSocCpuSim),
decoded with the QICK-channel PulseParamBuffer rules (risc-q/src/riscq/soc/rf/PulseParamBuffer.scala with
freqWidth = phaseWidth = 32, and QickGenChannel in soc/qick/QickGen.scala):
    +0x0004 freq (32 bit)         +0x000C phaseOffset (32 bit)
    slot i at (i+1)*0x10: +0 phase (32 bit), +4 amp = data[31:16] (signed), +8 env = data[25:16], +12 dur = data[31:16]
    +0x4100 startTime             +0x4104 conf (bridge conf, data[15:0])
    +0x0000 fire = slot index -> word {freq, phase + phaseOffset, gain = amp, env, nsamp = dur, conf} at
            startTime; then startTime += dur (an explicit startTime write wins)
  (QICK gens run at the 500 MHz dsp rate, claude-newdesign e77f1a69, so nsamp = dur.)
QICK side: runs/<P>/qick/ev_sg1_e3_sg_in.csv (commands accepted by signal generator <gen>) and
ev_sg1_e2_tproc_out.csv (their scheduled tProc times, head_due).

Fields are compared as SGv6 decodes them (ctrl_sg_v6.sv:427-435): freq, phase 32 bit, gain/addr/nsamp
16 bit, conf bits [4:0]. Times are compared relative to each side's first command, in ns.

    python3 compare.py MultiPulseProgram [--gen 1] [--ch-base 0x10000] [--tol-ns 2.4]
"""
import argparse
import csv
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
T_TPROC_NS = 1e3 / 430.08      # tProc timing clock
T_DSP_NS = 1e3 / 500.0         # RISC-Q dsp clock (zcu216-qick-1q)


def rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def decode_riscq(path, base, lsb=False):
    """Return the list of commands the QICK channel at RF offset `base` would send to its generator."""
    freq = phase_off = conf = start = 0
    table = {}
    out = []
    for r in rows(path):
        a, d = int(r["addr"], 16), int(r["data"], 16)
        if not base <= a < base + 0x10000:
            continue
        off = a - base
        if off == 0x4:
            freq = d
        elif off == 0xC:
            phase_off = d
        elif off == 0x4100:
            start = d
        elif off == 0x4104:
            conf = d & 0xFFFF
        elif off == 0x0:                                    # fire
            e = table.get(d & 0x7, {})
            amp = e.get("amp", 0)
            out.append({"cyc": int(r["cyc"]), "t_cyc": start, "freq": freq,
                        "phase": (e.get("phase", 0) + phase_off) & 0xFFFFFFFF,
                        "gain": amp & 0xFFFF, "addr": e.get("env", 0) & 0xFFFF,
                        "nsamp": e.get("dur", 0) & 0xFFFF, "conf": conf & 0x1F})
            start = (start + e.get("dur", 0)) & 0xFFFFFFFF
        elif 0x10 <= off < 0x10 * 9:
            slot, f = off // 0x10 - 1, off % 0x10
            e = table.setdefault(slot, {})
            sh = 0 if lsb else 16                           # hardware reads data[31:16] (bitOffset 16)
            if f == 0x0:
                e["phase"] = d
            elif f == 0x4:
                e["amp"] = (d >> sh) & 0xFFFF
            elif f == 0x8:
                e["env"] = (d >> sh) & 0x3FF
            elif f == 0xC:
                e["dur"] = (d >> sh) & 0xFFFF
    return out


def qick_commands(run, gen):
    pre = "ev_" if gen == 0 else f"ev_sg{gen}_"
    e3 = rows(run / f"{pre}e3_sg_in.csv")
    e2 = rows(run / f"{pre}e2_tproc_out.csv")
    out = []
    for i, r in enumerate(e3):
        out.append({"due": int(e2[i]["head_due"]) if i < len(e2) else None,
                    "freq": int(r["freq"], 16), "phase": int(r["phase"], 16), "gain": int(r["gain"], 16),
                    "addr": int(r["addr"], 16), "nsamp": int(r["nsamp"]), "conf": int(r["conf"], 16) & 0x1F})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("program")
    ap.add_argument("--gen", type=int, default=1, help="QICKEmu generator the QICK program drives")
    ap.add_argument("--ch-base", type=lambda s: int(s, 0), default=0x10000,
                    help="RF offset of the RISC-Q channel (RF_CH1 = CPU 0x20000 -> 0x10000 after the link)")
    ap.add_argument("--tol-ns", type=float, default=T_TPROC_NS, help="time tolerance (one tProc tick)")
    ap.add_argument("--abs-time", action="store_true",
                    help="compare play starts relative to command 0 instead of gaps between commands")
    ap.add_argument("--prefix", action="store_true",
                    help="long programs simulated only partly: compare the first min(N_QICK, N_RISC-Q) commands")
    ap.add_argument("--lsb", action="store_true",
                    help="decode amp/env/dur from data[15:0] (what the compiler writes) instead of data[31:16] (what the RTL reads)")
    a = ap.parse_args()

    run = HERE / "runs" / a.program
    rq = decode_riscq(run / "riscq" / "ev_rfcmd.csv", a.ch_base, a.lsb)
    qk = qick_commands(run / "qick", a.gen)
    fields = ["freq", "phase", "gain", "addr", "nsamp", "conf"]
    lines, bad = [], 0
    n = min(len(rq), len(qk)) if a.prefix else max(len(rq), len(qk))
    def play_starts(cmds, t_of, period_ns):
        """SGv6 starts a command at its scheduled time, or when the previous command ends if later."""
        out, end = [], None
        for c in cmds:
            t = t_of(c)
            st = t if end is None else max(t, end)
            out.append(st)
            end = st + c["nsamp"] * period_ns
        return out
    T_GEN_NS = 2.0                                          # 500 MHz generator cycle
    t0q = qk[0]["due"] * T_TPROC_NS if qk else 0
    t0r = rq[0]["t_cyc"] * T_DSP_NS if rq else 0
    pq = play_starts(qk, lambda c: c["due"] * T_TPROC_NS - t0q, T_GEN_NS)
    pr = play_starts(rq, lambda c: c["t_cyc"] * T_DSP_NS - t0r, T_GEN_NS)
    hdr = f"{'#':>2} {'field':6} {'QICK':>12} {'RISC-Q':>12}  ok"
    for i in range(n):
        q = qk[i] if i < len(qk) else None
        r = rq[i] if i < len(rq) else None
        if q is None or r is None:
            lines.append(f"{i:>2} {'missing on ' + ('QICK' if q is None else 'RISC-Q')}")
            bad += 1
            continue
        for f in fields:
            ok = q[f] == r[f]
            bad += not ok
            fmt = (lambda v: f"0x{v:08x}") if f in ("freq", "phase") else str
            lines.append(f"{i:>2} {f:6} {fmt(q[f]):>12} {fmt(r[f]):>12}  {'✓' if ok else '✗'}")
        tq, tr = pq[i], pr[i]
        if a.abs_time or i == 0:
            ok = abs(tq - tr) <= a.tol_ns
            what = "ns, play start relative to command 0"
            vq, vr = tq, tr
        else:
            # gap to the previous command: each side rounds a requested gap to its own clock
            # (tProc 2.325 ns, RISC-Q 2 ns), so compare gaps; absolute times drift by the rounding
            vq, vr = tq - pq[i - 1], tr - pr[i - 1]
            ok = abs(vq - vr) <= a.tol_ns
            what = "ns, gap to previous command"
        bad += not ok
        lines.append(f"{i:>2} {'start':6} {vq:12.2f} {vr:12.2f}  {'✓' if ok else '✗'}  {what}")
    print(f"decode: amp/env/dur from {'data[15:0] (compiler intent)' if a.lsb else 'data[31:16] (as the RTL reads them)'}")
    if a.prefix:
        print(f"prefix mode: comparing the first {n} commands (simulations were cut off; counts differ only by where)")
    print(f"{a.program}: QICK gen {a.gen} commands = {len(qk)}, RISC-Q channel 0x{a.ch_base:x} commands = {len(rq)}")
    print(hdr)
    print("\n".join(lines))
    if 0 < n <= min(len(pq), len(pr)):
        drift = (pr[n - 1] - pq[n - 1])
        print(f"time-grid drift at command {n - 1}: RISC-Q - QICK = {drift:+.2f} ns "
              f"(tProc rounds to 2.325 ns ticks, RISC-Q to 2 ns cycles; informational)")
    print(f"RESULT: {'PASS' if bad == 0 else 'FAIL'} ({bad} mismatches)")
    (run / ("compare_lsb.txt" if a.lsb else "compare.txt")).write_text("\n".join([hdr] + lines + [f"RESULT: {'PASS' if bad == 0 else 'FAIL'} ({bad} mismatches)"]) + "\n")


if __name__ == "__main__":
    main()
