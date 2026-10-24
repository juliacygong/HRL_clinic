#!/usr/bin/env python3
"""Standalone ZCU216 bring-up for the RISC-Q QICK (WaveWordBridge -> axis_signal_gen_v6) build.

Runs ON THE BOARD (PYNQ 2.7 image, pynq-venv python, as root) with only what that image ships: pynq,
xrfclk, xrfdc, numpy. No riscq install. It does, in the order riscq's PynqDriver does:

  1. clocks   CLK104 LMK04828 <- LMK04828_500.0.txt: DAC_REFCLK / ADC_REFCLK / PL_CLK = 500 MHz,
              SYSREF 7.8125 MHz (the board's own 245.76 MHz TICS file with 8 registers changed, see
              gen_lmk500.py). The LMX2594s are not used: RFDC tile 2's PLL makes the sample clocks.
  2. overlay  pynq.Overlay(PulseTableSoc.bit) — needs PulseTableSoc.hwh next to it (PYNQ 2.7 can't
              take an .xsa).
  3. RFDC     two-pass MTS, DAC/ADC Nyquist zones (PynqDriver.mts / *_nyquist_zone, verbatim).
  4. core     hold reset, park the core (`j .` at its reset vector), load an ELF or flat binary at
              0x80000000, release reset, optionally poll __rq_status for DONE.

Host map (riscq.map.SocMap for software/configs/zcu216-qick-1q.json; AXI window 0x8000_0000):
  core 0 RAM 0x00000 (16 KB)    host_ctrl 0x50000 (+0x0 reset: 1 = held, 0 = run)

    sudo -E /usr/local/share/pynq-venv/bin/python3 bringup.py                # clocks + overlay + RFDC
    sudo -E ... bringup.py --elf prog.elf --wait                             # + run a program
    sudo -E ... bringup.py --skip-clocks --no-download --elf prog.elf        # rerun on a live overlay
"""
import argparse
import os
import struct
import sys
import time
from pathlib import Path

os.environ.setdefault("BOARD", "ZCU216")        # xrfclk reads it at import; sudo drops the profile's

import pynq
import xrfclk
import xrfdc  # noqa: F401 — registers the RFdc driver so overlay.rf_data_converter binds
# PYNQ 2.7's xrfdc driver is registered for RFDC IP 2.3/2.4; this build (Vivado 2024.1) has 2.6, as QICK's
# ZCU216 firmware does, so the overlay is opened with ignore_version=True to bind it anyway

HERE = Path(__file__).resolve().parent
AXI_BASE = 0x8000_0000
AXI_SIZE = 0x0006_0000          # everything the 1-core map uses (host_ctrl ends at 0x50048)
MEM_BASE = 0x8000_0000          # CPU address of the unified I+D RAM
CORE_RAM, CORE_RAM_BYTES = 0x00000, 0x4000
HOST_CTRL, HOST_RESET = 0x50000, 0x0
HOST_TIME_OFF_LO, HOST_TIME_OFF_HI = 0x40, 0x44
STATUS_DONE_MASK, STATUS_DONE = 0xFFFF0000, 0xD04E0000


def log(*a):
    print("[bringup]", *a, flush=True)


# ── 1. clocks ──────────────────────────────────────────────────────────────────────────────────

def read_tics(path):
    """TICS Pro register export (`R<n>\\t0x......` per line, in write order) -> list of 24-bit words."""
    return [int(line.split("\t")[1], 16) for line in Path(path).read_text().splitlines() if line.strip()]


def set_clocks(lmk_file):
    regs = read_tics(lmk_file)
    xrfclk.xrfclk._find_devices()               # binds /dev/spidev1.{1,2,3} (needs root)
    lmks = xrfclk.xrfclk.lmk_devices
    if len(lmks) != 1 or lmks[0]["compatible"] != "lmk04828":
        raise RuntimeError(f"expected one lmk04828 on the device tree, found {lmks}")
    xrfclk.xrfclk._write_LMK_regs(regs, lmks[0])
    log(f"LMK04828 programmed from {lmk_file} ({len(regs)} registers) -> 500 MHz refclks + PL_CLK")
    time.sleep(0.1)                             # let PLL1/PLL2 lock before the RFDC tiles start


# ── 2/3. overlay + RFDC (PynqDriver, verbatim) ─────────────────────────────────────────────────

def config_mts(rfdc, daclatency=-1, adclatency=-1):
    for cfg in (rfdc.mts_dac_config, rfdc.mts_adc_config):
        cfg.RefTile = 2
        cfg.Tiles = 0xF
        cfg.SysRef_Enable = 1
    rfdc.mts_dac_config.Target_Latency = daclatency
    rfdc.mts_adc_config.Target_Latency = adclatency


def mts_latencies(rfdc):
    return ([rfdc.mts_dac_config.Latency[i] for i in range(4)],
            [rfdc.mts_adc_config.Latency[i] for i in range(4)])


def mts(rfdc, daclatency=260, adclatency=60):
    """Two-pass MTS (QubiC): free sync to measure, then re-sync pinned to the targets when the
    tiles agree. 0 iff every latency == target."""
    config_mts(rfdc)
    rfdc.mts_dac()
    rfdc.mts_adc()
    dac, adc = mts_latencies(rfdc)
    log(f"MTS free: dac {dac} adc {adc}")
    if (len(set(dac)) == 1 and dac[0] <= daclatency and len(set(adc)) == 1 and adc[0] <= adclatency):
        config_mts(rfdc, daclatency, adclatency)
        rfdc.mts_dac()
        rfdc.mts_adc()
        dac, adc = mts_latencies(rfdc)
        log(f"MTS pinned: dac {dac} adc {adc}")
    return 0 if all(l == daclatency for l in dac) and all(l == adclatency for l in adc) else 1


def tile_status(rfdc):
    for kind, tiles in (("DAC", rfdc.dac_tiles), ("ADC", rfdc.adc_tiles)):
        for t in range(4):
            try:
                st = tiles[t].CurrentState if hasattr(tiles[t], "CurrentState") else None
                pll = tiles[t].PLLLockStatus if hasattr(tiles[t], "PLLLockStatus") else None
            except Exception as e:                  # noqa: BLE001 — diagnostics only
                st, pll = f"err {e}", None
            log(f"  {kind} tile {t}: state {st}  pll lock {pll}")


# ── 4. core ────────────────────────────────────────────────────────────────────────────────────

class Window:
    """32-bit single-beat access to the SoC's AXI window (the PL only takes 32-bit beats: a wide
    numpy slice read DECERRs -> SIGBUS, see PynqDriver.read_block)."""

    def __init__(self):
        self.mmio = pynq.MMIO(AXI_BASE, AXI_SIZE)

    def read32(self, off):
        return self.mmio.read(off) & 0xFFFFFFFF

    def write32(self, off, v):
        self.mmio.write(off, int(v) & 0xFFFFFFFF)

    def write_block(self, off, data):
        data = bytes(data) + b"\0" * (-len(data) % 4)
        for i in range(0, len(data), 4):
            self.write32(off + i, int.from_bytes(data[i:i + 4], "little"))

    def read_block(self, off, n):
        return b"".join(self.read32(off + 4 * i).to_bytes(4, "little") for i in range(-(-n // 4)))[:n]


def load_elf(path):
    """Minimal ELF32-LE loader: flat image of the PT_LOAD segments from MEM_BASE + the symbol table."""
    b = Path(path).read_bytes()
    if b[:4] != b"\x7fELF" or b[4] != 1 or b[5] != 1:
        raise ValueError(f"{path}: not a 32-bit little-endian ELF")
    e_entry, e_phoff, e_shoff = struct.unpack_from("<III", b, 24)
    e_phentsize, e_phnum, e_shentsize, e_shnum = struct.unpack_from("<HHHH", b, 42)
    image = bytearray()
    for i in range(e_phnum):
        p_type, p_off, _, p_paddr, p_filesz, p_memsz = struct.unpack_from("<IIIIII", b, e_phoff + i * e_phentsize)
        if p_type != 1 or p_memsz == 0:
            continue
        if p_paddr < MEM_BASE:                      # page-aligned first segment carrying the ELF headers
            skip = MEM_BASE - p_paddr
            p_paddr, p_off, p_memsz, p_filesz = MEM_BASE, p_off + skip, p_memsz - skip, max(0, p_filesz - skip)
        lo = p_paddr - MEM_BASE
        if lo < 0 or lo + p_memsz > CORE_RAM_BYTES:
            raise ValueError(f"segment [{p_paddr:#x}, +{p_memsz:#x}) outside core RAM")
        image.extend(b"\0" * max(0, lo + p_memsz - len(image)))
        image[lo:lo + p_filesz] = b[p_off:p_off + p_filesz]
    syms = {}
    shdrs = [struct.unpack_from("<IIIIIIIIII", b, e_shoff + i * e_shentsize) for i in range(e_shnum)]
    for sh in shdrs:
        if sh[1] != 2:                              # SHT_SYMTAB
            continue
        strtab = shdrs[sh[6]]
        for off in range(sh[4], sh[4] + sh[5], 16):
            st_name, st_value, st_size = struct.unpack_from("<III", b, off)
            name = b[strtab[4] + st_name:b.index(b"\0", strtab[4] + st_name)].decode()
            if name:
                syms[name] = (st_value, st_size)
    return e_entry, bytes(image), syms


def hwh_ranges(bit):
    """{slave bus interface or instance: (base, size)} from the .hwh next to the bitstream — the top IP
    has several AXI slaves (S_AXIS, QICKGEN*_S_AXI), which pynq's ip_dict folds into one entry."""
    import xml.etree.ElementTree as ET
    out = {}
    for mr in ET.parse(Path(bit).with_suffix(".hwh")).iter("MEMRANGE"):   # any type: the FIFOs' are Mem0
        lo, hi = int(mr.get("BASEVALUE"), 16), int(mr.get("HIGHVALUE"), 16)
        out[mr.get("SLAVEBUSINTERFACE") if mr.get("INSTANCE") == "top" else mr.get("INSTANCE")] = (lo, hi - lo + 1)
    return out


# axi_fifo_mm_s (PG080) TX registers; gen_v6 s_axi registers (QICK AxisSignalGenV6.REGISTERS)
FIFO_ISR, FIFO_TDFR, FIFO_TDFV, FIFO_TDFD, FIFO_TLR = 0x00, 0x08, 0x0C, 0x10, 0x14
GEN_START_ADDR, GEN_WE = 0x00, 0x04


def load_envelope(ranges, gen, env_file, chunk=2048):
    """QICK's AxisSignalGenV6.load(): START_ADDR = 0, WE = 1, stream the (I | Q << 16) words into the
    gen's s0_axis (here through its AXI4-Stream FIFO), WE = 0. `env_file` = the compiler's
    <prog>_gen<N>.env (int16 I, Q pairs from table address 0)."""
    words = Path(env_file).read_bytes()
    if len(words) % 4:
        raise ValueError(f"{env_file}: {len(words)} B is not whole (I, Q) int16 pairs")
    n = len(words) // 4
    g_base, g_size = ranges[f"QICKGEN0_{gen.upper()}_S_AXI"]
    f_base, f_size = ranges[f"envfifo_qickgen0_{gen}"]
    g, f = pynq.MMIO(g_base, g_size), pynq.MMIO(f_base, f_size)
    f.write(FIFO_ISR, 0xFFFFFFFF)
    f.write(FIFO_TDFR, 0xA5)                        # TX reset
    depth = f.read(FIFO_TDFV)
    g.write(GEN_START_ADDR, 0)
    g.write(GEN_WE, 1)
    for i in range(0, n, chunk):
        part = words[4 * i:4 * min(n, i + chunk)]
        while f.read(FIFO_TDFV) < len(part) // 4:
            time.sleep(1e-4)
        for j in range(0, len(part), 4):
            f.write(FIFO_TDFD, int.from_bytes(part[j:j + 4], "little"))
        f.write(FIFO_TLR, len(part))                # byte count -> launch the packet
    t0 = time.time()
    while f.read(FIFO_TDFV) != depth:               # drained into the gen's table
        if time.time() - t0 > 1:
            raise TimeoutError(f"envelope FIFO for gen {gen} did not drain (vacancy {f.read(FIFO_TDFV)}/{depth})")
        time.sleep(1e-4)
    g.write(GEN_WE, 0)
    log(f"loaded {n} envelope samples from {env_file} into the {gen} gen")


ROBS, ROB_DEPTH, ADC_BATCH = 0x40000, 1024, 4   # SocMap.robs(); robDepth entries x adcBatch int32 lanes
ADC_FS_HZ = 2.0e9                                # ADCs at 2 GS/s (rfdc-config.tcl): 4 lanes per 500 MHz cycle


def read_robs(win):
    """The readout trace: raw (mapped-ADC-summed) samples over the last readout window, lane 0 first
    within each dsp cycle, so a flat int32 array in time order. Entries past the window keep old data."""
    import numpy as np
    raw = win.read_block(ROBS, ROB_DEPTH * ADC_BATCH * 4)
    return np.frombuffer(raw, dtype="<i4").astype(np.int64)


def write_capture(path, traces, meta):
    import numpy as np
    traces = np.asarray(traces)
    mean = traces.mean(axis=0)
    t_ns = np.arange(mean.size) / ADC_FS_HZ * 1e9
    with open(path, "w") as f:
        for k, v in meta.items():
            f.write(f"# {k}: {v}\n")
        f.write("sample,t_ns,adc_mean" + "".join(f",run{i}" for i in range(len(traces))) + "\n")
        for i in range(mean.size):
            f.write(f"{i},{t_ns[i]:.3f},{mean[i]:.3f}" + "".join(f",{tr[i]}" for tr in traces) + "\n")
    log(f"wrote {len(traces)} capture(s) x {mean.size} samples -> {path}")


def run_core(win, image, syms, wait, timeout_s):
    win.write32(HOST_CTRL + HOST_RESET, 1)
    win.write32(CORE_RAM, 0x6F)                     # park (`j .`) until the image is in
    if image is None:
        log("core held in reset, parked (no program given)")
        return
    win.write_block(CORE_RAM, image)
    back = win.read_block(CORE_RAM, min(len(image), 256))
    if back != image[:len(back)]:
        raise RuntimeError("core RAM readback mismatch after load")
    log(f"loaded {len(image)} B into core 0 RAM (readback of first {len(back)} B OK)")
    win.write32(HOST_CTRL + HOST_RESET, 0)
    log("core 0 released from reset")
    if not wait:
        return
    if "__rq_status" not in syms:
        log("no __rq_status symbol: not polling")
        return
    addr = CORE_RAM + syms["__rq_status"][0] - MEM_BASE
    t0, status = time.time(), win.read32(addr)
    while (status & STATUS_DONE_MASK) != STATUS_DONE:
        if time.time() - t0 > timeout_s:
            raise TimeoutError(f"core not DONE after {timeout_s} s (__rq_status = {status:#010x})")
        time.sleep(0.001)
        status = win.read32(addr)
    log(f"core DONE (__rq_status = {status:#010x}) after {time.time() - t0:.3f} s")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bit", default=str(HERE / "PulseTableSoc.bit"))
    ap.add_argument("--lmk", default=str(HERE / "LMK04828_500.0.txt"))
    ap.add_argument("--skip-clocks", action="store_true", help="clocks already programmed this power cycle")
    ap.add_argument("--no-download", action="store_true", help="attach to the loaded overlay, don't reprogram the PL")
    ap.add_argument("--no-mts", action="store_true")
    ap.add_argument("--dac-nyquist", type=int, default=2, help="all DAC blocks (riscq board default 2)")
    ap.add_argument("--adc-nyquist", type=int, default=1)
    ap.add_argument("--elf", help="RISC-V ELF to run on core 0")
    ap.add_argument("--bin", help="flat binary to run on core 0 (loaded at 0x80000000)")
    ap.add_argument("--wait", action="store_true", help="poll __rq_status until DONE (ELF only)")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--env", action="append", default=[], metavar="GEN=FILE",
                    help="load an envelope table before the run: gate=prog_gen0.env (GEN_CH 0 -> gate gen "
                         "-> DAC 0) or ro=prog_gen1.env (GEN_CH 1 -> readout gen -> DAC 1); repeatable")
    ap.add_argument("--repeat", type=int, default=1, help="rerun the program N times (0 = until Ctrl-C), "
                    "--period seconds apart — for a scope")
    ap.add_argument("--period", type=float, default=0.01)
    ap.add_argument("--capture", metavar="CSV",
                    help="after each run read the readout trace (robs: 4096 raw ADC samples at 2 GS/s over the "
                         "program's readout window) and write all runs + their mean to CSV (needs a loopback cable)")
    ap.add_argument("--settle", type=float, default=0.002,
                    help="seconds to wait after DONE before reading the trace (scheduled pulses still playing)")
    a = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit("run as root: sudo -E /usr/local/share/pynq-venv/bin/python3 bringup.py ...")

    if not a.skip_clocks:
        set_clocks(a.lmk)

    log(f"{'attaching to' if a.no_download else 'downloading'} overlay {a.bit}")
    ol = pynq.Overlay(a.bit, download=not a.no_download, ignore_version=True)
    rfdc = ol.rf_data_converter
    qick = {k: hex(v["phys_addr"]) for k, v in ol.ip_dict.items() if "phys_addr" in v}
    log(f"AXI map: {qick}")

    if not a.no_mts and not hasattr(rfdc, "mts_dac_config"):
        log("MTS skipped: this PYNQ's xrfdc has no multi-tile-sync API (PYNQ >= 3.0); single DAC->ADC "
            "paths work without it, only cross-tile latency alignment is missing")
    elif not a.no_mts:
        try:
            log(f"MTS result: {mts(rfdc)} (0 = all tiles at target latency)")
        except RuntimeError as e:
            log(f"MTS failed, continuing: {e}")
    for t in range(4):
        for blk in range(4):
            rfdc.dac_tiles[t].blocks[blk].NyquistZone = a.dac_nyquist
            rfdc.adc_tiles[t].blocks[blk].NyquistZone = a.adc_nyquist
    log(f"Nyquist zones: DAC {a.dac_nyquist}, ADC {a.adc_nyquist}")
    tile_status(rfdc)

    ranges = hwh_ranges(a.bit)
    for spec in a.env:
        gen, _, path = spec.partition("=")
        if gen not in ("gate", "ro") or not path:
            sys.exit(f"--env takes gate=FILE or ro=FILE, got {spec!r}")
        if f"envfifo_qickgen0_{gen}" not in ranges:
            sys.exit("this bitstream has no envelope FIFOs (built before the bd-build.tcl envfifo change)")
        load_envelope(ranges, gen, path)

    win = Window()
    image, syms = None, {}
    if a.elf:
        entry, image, syms = load_elf(a.elf)
        if entry != MEM_BASE:
            log(f"warning: ELF entry {entry:#x} != {MEM_BASE:#x} (the core boots at {MEM_BASE:#x})")
    elif a.bin:
        image = Path(a.bin).read_bytes()
    i, traces = 0, []
    try:
        while True:
            run_core(win, image, syms, a.wait or a.repeat != 1 or bool(a.capture), a.timeout)
            i += 1
            if a.capture and image is not None:
                time.sleep(a.settle)                # DONE = last command issued; the queued pulses play later
                traces.append(read_robs(win))
            if image is None or (a.repeat and i >= a.repeat):
                break
            time.sleep(a.period)
    except KeyboardInterrupt:
        pass
    if a.repeat != 1:
        log(f"ran the program {i} times")
    if traces:
        write_capture(a.capture, traces, {
            "program": a.elf or a.bin, "bitstream": a.bit, "envelopes": " ".join(a.env) or "none",
            "runs": len(traces), "adc_fs_hz": ADC_FS_HZ, "dac_nyquist": a.dac_nyquist,
            "time": time.strftime("%Y-%m-%d %H:%M:%S")})


if __name__ == "__main__":
    main()
