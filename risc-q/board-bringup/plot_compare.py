#!/usr/bin/env python3
"""Plot a RISC-Q loopback capture (bringup.py --capture) against a QICK tProc v2 baseline.

RISC-Q's readout trace is raw ADC samples (2 GS/s) over the program's readout window; QICK's
acquire_decimated() returns the dynamic readout's downconverted, decimated I/Q. To compare the two on
one axis, the RISC-Q trace is digitally downconverted here the way QICK's readout does it: mixed with
exp(-j 2pi f t) at the readout frequency, low-pass filtered (boxcar over one output sample) and
resampled onto the QICK time grid.

    python3 plot_compare.py riscq.csv [--qick qick_baseline.csv] [--freq 500] [--out compare]

qick_baseline.csv: columns t_us,I,Q (save it in the QICK notebook right after acquire_decimated:
    np.savetxt("qick_baseline.csv", np.column_stack([t, iq_list[0][:, 0], iq_list[0][:, 1]]),
               delimiter=",", header="t_us,I,Q", comments="")
Writes <out>.png and <out>_iq.csv (the downconverted RISC-Q I/Q on the plotted time axis).
"""
import argparse
import csv

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def read_riscq(path):
    meta, rows = {}, []
    with open(path) as f:
        for line in f:
            if line.startswith("#"):
                k, _, v = line[1:].partition(":")
                meta[k.strip()] = v.strip()
            else:
                rows.append(line)
    r = list(csv.DictReader(rows))
    runs = np.array([[float(x[k]) for x in r] for k in r[0] if k.startswith("run")])
    return meta, np.array([float(x["t_ns"]) for x in r]), np.array([float(x["adc_mean"]) for x in r]), runs


def coherent_mean(t_ns, runs, f_mhz, fs_out):
    """Per-run DDC, each rotated to run 0's phase over its strongest pulse, then averaged. RISC-Q restarts the
    core for every run while the gen's DDS free-runs, so the carrier phase differs per run and a plain mean of
    the raw samples partly cancels. Returns (t_us, mean IQ, per-run phase offsets in degrees)."""
    bbs = [downconvert(t_ns, x, f_mhz, fs_out)[1] for x in runs]
    ref = bbs[0]
    win = np.abs(ref) > 0.7 * np.abs(ref).max()
    phases = [np.angle(np.vdot(ref[win], b[win])) for b in bbs]
    mean = np.mean([b * np.exp(-1j * p) for b, p in zip(bbs, phases)], axis=0)
    return t_ns / 1e3, mean, np.degrees(phases)


def read_qick(path):
    a = np.genfromtxt(path, delimiter=",", names=True)
    return a["t_us"], a["I"], a["Q"]


def downconvert(t_ns, x, f_mhz, fs_out_mhz, taps=129):
    """QICK-style DDC: mix to baseband, low-pass to the output Nyquist band (Hann-windowed sinc, which
    also removes the 2f mixing image), to be sampled at fs_out by the caller."""
    t_us = t_ns / 1e3
    fs_in = 1e3 / (t_ns[1] - t_ns[0])                                   # MHz
    bb = (x - x.mean()) * np.exp(-2j * np.pi * f_mhz * t_us)
    fc = 0.5 * fs_out_mhz / fs_in                                       # cutoff, cycles/sample
    n = np.arange(taps) - (taps - 1) / 2
    h = 2 * fc * np.sinc(2 * fc * n) * np.hanning(taps)
    return t_us, 2 * np.convolve(bb, h / h.sum(), mode="same")         # x2: the cos -> one sideband


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("riscq")
    ap.add_argument("--qick", help="QICK baseline CSV (t_us,I,Q)")
    ap.add_argument("--freq", type=float, default=500.0, help="readout / pulse frequency, MHz")
    ap.add_argument("--fs-out", type=float, default=307.2, help="output rate when there is no QICK grid, MHz")
    ap.add_argument("--normalize", action="store_true", help="scale each trace to its peak magnitude")
    ap.add_argument("--out", default="compare")
    ap.add_argument("--raw-mean", action="store_true",
                    help="downconvert the CSV's plain adc_mean instead of phase-aligning each run first")
    ap.add_argument("--align", action="store_true",
                    help="shift the RISC-Q trace by the lag that best matches QICK's |IQ| (the two systems have "
                         "different DAC->ADC latency relative to their trigger); the shift is printed and plotted")
    a = ap.parse_args()

    meta, t_ns, adc, runs = read_riscq(a.riscq)
    q = read_qick(a.qick) if a.qick else None
    fs_out = (1 / np.median(np.diff(q[0]))) if q is not None else a.fs_out
    if len(runs) > 1 and not a.raw_mean:
        t_us, iq, ph = coherent_mean(t_ns, runs, a.freq, fs_out)
        adc = runs[0]
        print(f"coherent mean of {len(runs)} runs; per-run carrier phase vs run 0 (deg): {np.round(ph).astype(int)}")
    else:
        t_us, iq = downconvert(t_ns, adc, a.freq, fs_out)
    shift_us = 0.0
    if q is not None:                                   # onto QICK's grid, both from their first sample
        grid = q[0] - q[0][0]
        if a.align:
            # anchor = rising edge (first crossing of 70 % of peak |IQ|) of each trace's strongest pulse — the
            # full-gain const pulse in MultiPulseProgram (flat-top flats run at half gain, so it is unique)
            def edge(t, m):
                return t[np.argmax(m > 0.7 * m.max())]
            tq, tr = edge(grid, np.abs(q[1] + 1j * q[2])), edge(t_us, np.abs(iq))
            shift_us = float(tq - tr)                   # RISC-Q time t is plotted at t + shift_us
            print(f"align: strongest-pulse edge QICK {tq:.3f} us, RISC-Q {tr:.3f} us -> RISC-Q shifted "
                  f"{shift_us:+.3f} us (QICK's DAC->ADC latency minus RISC-Q's, relative to each trigger)")
        iq = np.interp(grid - shift_us, t_us, iq.real, 0, 0) + 1j * np.interp(grid - shift_us, t_us, iq.imag, 0, 0)
        t_us = grid
    else:
        step = max(1, int(round(len(t_us) / (t_us[-1] * fs_out))))
        t_us, iq = t_us[::step], iq[::step]

    def norm(z):
        return z / np.abs(z).max() if a.normalize and np.abs(z).max() else z

    r = norm(iq)
    fig, ax = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    ax[0].plot(t_ns / 1e3 + shift_us, adc, lw=0.6, color="0.3")
    ax[0].set_ylabel("ADC (raw, run 0)")
    ax[0].set_title(f"RISC-Q loopback: {meta.get('program', a.riscq)}  ({meta.get('runs', '?')} runs averaged)")
    ax[1].plot(t_us, r.real, label="RISC-Q I")
    ax[1].plot(t_us, r.imag, label="RISC-Q Q")
    ax[2].plot(t_us, np.abs(r), label="RISC-Q |IQ|")
    if q is not None:
        qz = norm(q[1] + 1j * q[2])
        ax[1].plot(q[0] - q[0][0], qz.real, "--", label="QICK I")
        ax[1].plot(q[0] - q[0][0], qz.imag, "--", label="QICK Q")
        ax[2].plot(q[0] - q[0][0], np.abs(qz), "--", label="QICK |IQ|")
    ax[1].set_ylabel("I / Q" + (" (norm.)" if a.normalize else ""))
    ax[2].set_ylabel("magnitude")
    ax[2].set_xlabel("time from readout window start (us)"
                     + (f"; RISC-Q shifted {shift_us:+.3f} us to align" if shift_us else ""))
    for x in ax[1:]:
        x.legend(loc="upper right", fontsize=8)
        x.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(f"{a.out}.png", dpi=130)
    np.savetxt(f"{a.out}_iq.csv", np.column_stack([t_us, iq.real, iq.imag]), delimiter=",",
               header="t_us,I,Q", comments="")
    print(f"wrote {a.out}.png and {a.out}_iq.csv")


if __name__ == "__main__":
    main()
