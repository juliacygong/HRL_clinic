#!/usr/bin/env python3
"""Evidence for findings F1/F2 (tables/findings.csv) from the traced T9b run.

Usage (needs matplotlib -> QICKEmu venv):
    ~/projects/HRL_clinic/.venv/bin/python backpressure_snapshot.py runs/T9b/d0_trace

Writes into <run_dir>:
    f1_dispatcher_skip.png / .csv   tProc wave port changes tdata while tvalid && !tready
    f2_cdc_stale_read.png  / .csv   emulator CDC FIFO re-delivers a stale word
The CSVs are per-clock-edge cycle tables (values sampled just before each rising edge).
"""

import csv
import os
import sys

import wave_snapshot as ws

DUT = ws.DUT
CDC = f"{DUT}.u_axis_sgcdcsync_v1.cdcsync_i"
FIFO = f"{CDC}.gen_fifo_dc_sv.fifo_i"
GAIN168 = (88, 119)     # gain field in the 168-bit tProc command
GAIN160 = (96, 111)     # gain field in the 160-bit SGv6 command

F1 = {
    "window": (4749.0, 4786.0), "clock": "t_clk",
    "signals": {
        "t_clk": (f"{ws.H}.t_clk", None),
        "t_time_abs_o": (f"{ws.H}.t_time_abs_o", None),
        "wave_pop[0]": (f"{ws.DISP}.wave_pop", 0),
        "wave_pop_r[0]": (f"{ws.DISP}.wave_pop_r", 0),
        "m0 tvalid": (f"{DUT}.tproc_sg0cdc_axis_tvalid", None),
        "m0 tready": (f"{DUT}.tproc_sg0cdc_axis_tready", None),
        "m0 tdata gain": (f"{DUT}.tproc_sg0cdc_axis_tdata", GAIN168),
        "CDC fifo_full": (f"{CDC}.fifo_full", None),
    },
    "markers": [(4763.038, "851 offered, tready=0", "tab:red"),
                (4767.686, "tdata -> 0", "tab:orange"),
                (4770.010, "tdata -> 872 (851 lost)", "tab:orange"),
                (4781.630, "872 accepted", "tab:green"),
                (4783.954, "872 popped again -> duplicate", "tab:purple")],
    "title": "F1 (shared RTL, qproc_dispatcher.sv:384-400): held beat's tdata changes while tvalid=1, tready=0 -> 851 lost, 872 duplicated",
    "png": "f1_dispatcher_skip.png", "csv": "f1_dispatcher_skip.csv",
}
F2 = {
    "window": (4371.5, 4400.5), "clock": "sg_clk",
    "signals": {
        "sg_clk": (f"{ws.H}.sg_clk", None),
        "CDC rptr": (f"{FIFO}.rptr", None),
        "CDC wptr_c": (f"{FIFO}.wptr_c", None),
        "CDC empty": (f"{CDC}.fifo_empty", None),
        "CDC rd_en": (f"{CDC}.fifo_rd_en", None),
        "CDC dob gain": (f"{FIFO}.mem_i.dob", GAIN168),
        "sgt0 tvalid": (f"{DUT}.sgt0_sg0_axis_tvalid", None),
        "sgt0 tready": (f"{DUT}.sgt0_sg0_axis_tready", None),
        "sgt0 tdata gain": (f"{DUT}.sgt0_sg0_axis_tdata", GAIN160),
        "SGv6 fifo_full": (f"{DUT}.u_axis_signal_gen_v6_0.signal_gen_top_i.fifo_full", None),
    },
    "markers": [(4381.193, "3d6 accepted", "tab:green"),
                (4391.209, "new word written, rd_en=0: dob not refreshed", "tab:red"),
                (4396.217, "3d6 accepted AGAIN (stale)", "tab:purple"),
                (4397.887, "dob now lags rptr by one", "tab:orange")],
    "title": "F2 (emulator model: fifo_dc_sv + bram_dp_behav): stale CDC read -> duplicate 3d6, data lags pointer, last word lost",
    "png": "f2_cdc_stale_read.png", "csv": "f2_cdc_stale_read.csv",
}


def cycle_table(waves, clock, window, path):
    """Values of every signal sampled just before each rising edge of `clock`."""
    edges = [t for (t, v), (_, pv) in zip(waves[clock][1:], waves[clock][:-1]) if v == 1 and pv == 0]
    labels = [k for k in waves if k != clock]

    def at(label, t):
        val = waves[label][0][1]
        for tt, vv in waves[label]:
            if tt >= t:          # sample strictly before the edge
                break
            val = vv
        return val

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["edge_time_ns"] + labels)
        for t in edges:
            if window[0] <= t <= window[1]:
                w.writerow([f"{t:.3f}"] + [f"{at(l, t):x}" if "gain" in l else at(l, t) for l in labels])


def render(run_dir, spec):
    ws.SIGNALS = spec["signals"]
    waves = ws.extract(os.path.join(run_dir, "waveform.fst"), *spec["window"])
    labels = list(spec["signals"])
    ws.draw(waves, labels, spec["window"], spec["markers"], spec["title"],
            os.path.join(run_dir, spec["png"]),
            bus_labels=[l for l in labels if "gain" in l or "ptr" in l or l == "t_time_abs_o"])
    cycle_table(waves, spec["clock"], spec["window"], os.path.join(run_dir, spec["csv"]))
    print("wrote", spec["png"], spec["csv"])


if __name__ == "__main__":
    for spec in (F1, F2):
        render(os.path.abspath(sys.argv[1]), spec)
