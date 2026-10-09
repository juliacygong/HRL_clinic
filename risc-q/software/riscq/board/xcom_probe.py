"""On-board bring-up probe for QICK's XCOM board link (milestone H1).

Runs on the ZCU216 against a bitstream built with RISCQ_WITH_XCOM=1. Talks to the IP's AXI-Lite
slave over raw `pynq.MMIO`, deliberately NOT through `qick.drivers.xcom.QICK_Xcom`: that driver's
`bindto` lists `fnal:qick:xcom:1.0` while `firmware/ip/xcom/component.xml` declares
`QICK:QICK:xcom:1.0`, so it will not auto-bind to this overlay. The register map and the status /
debug bit decode below are copied from that driver so results stay comparable with QICK's tooling.

What this proves, and what it does not: with RISCQ_XCOM_LOOPBACK=1 the link's transmit pair is tied
back to its own receive pair inside the fabric, on one clock, with no pins and no cable. That is the
closest hardware analogue of the passing `XcomSim` (which also ran both ends off a single clock), so
a failure here is a synthesis, clocking or constraints problem and nothing else. It says nothing
about signal integrity, nothing about two independent clock domains, and nothing about the local
`o_core_data1/2` patch in xcom.sv - the AXI dt1/dt2 read path goes through a separate CDC
(`s_core_data1_ps`), so the patch is not exercised until the RISC-V command port is wired up.

    sudo python3 -m riscq.board.xcom_probe              # full H1 sequence
    sudo python3 -m riscq.board.xcom_probe --sweep      # + bit-rate sweep and BER
"""

from __future__ import annotations

import argparse
import time

XCOM_BASE = 0x9000_0000      # inc/config.tcl XCOM_BASEADDR; outside the SoC's 0x8000_0000 window
XCOM_SIZE = 0x1000

# register index -> byte offset is index * 4 (the slave has a 6-bit address)
REG = {
    "ctrl": 0, "cfg": 1, "axi_dt1": 2, "axi_dt2": 3, "axi_addr": 4,
    "board_id": 6, "flag": 7, "dt1": 8, "dt2": 9, "mem": 10,
    "rx_dt": 12, "tx_dt": 13, "status": 14, "debug": 15,
}

OP = {
    "CLEAR_FLAG": 0, "SET_FLAG": 1, "SEND_8BIT_1": 2, "SEND_8BIT_2": 3,
    "SEND_16BIT_1": 4, "SEND_16BIT_2": 5, "SEND_32BIT_1": 6, "SEND_32BIT_2": 7,
    "QRST_SYNC": 8, "AUTO_ID": 9, "UPDATE_DT8": 10, "QCTRL": 11,
    "UPDATE_DT16": 12, "UPDATE_DT32": 14,
    "SET_ID": 16, "WRITE_FLAG": 17, "WRITE_REG": 18, "WRITE_MEM": 19, "RST": 31,
}

TX_ST = {0: "IDLE", 1: "WVLD", 2: "WSYNC", 3: "WRDY"}
RX_ST = {0: "IDLE", 1: "HEADER", 2: "DATA", 3: "REQ", 4: "ACK"}


class Xcom:
    """Raw-MMIO view of one xcom instance."""

    def __init__(self, base: int = XCOM_BASE, size: int = XCOM_SIZE):
        import pynq
        self.mmio = pynq.MMIO(base, size)

    def rd(self, name: str) -> int:
        return self.mmio.read(REG[name] * 4)

    def wr(self, name: str, value: int) -> None:
        self.mmio.write(REG[name] * 4, value & 0xFFFF_FFFF)

    def cmd(self, op: str, dt1: int = 0, dt2: int = 0) -> None:
        """Issue one command. `ctrl = (op << 1) | 1`; bit 0 is a one-shot that the slave
        self-clears (xcom_axil_slv.sv:339), so this is a single write, never a hold."""
        self.wr("axi_dt1", dt1)
        self.wr("axi_dt2", dt2)
        self.wr("ctrl", (OP[op] << 1) | 1)

    # ── decoded views; the bit positions mirror QICK_Xcom.print_status / print_debug ──
    def status(self) -> dict:
        s = self.rd("status")
        return {
            "raw": s,
            "tx_st": TX_ST.get(s & 0x3, f"UNKNOWN({s & 0x3})"),
            "rx_st": RX_ST.get((s >> 6) & 0x7, f"UNKNOWN({(s >> 6) & 0x7})"),
            "tx_ready": (s >> 16) & 0x1,
            "board_id": (s >> 17) & 0xF,
            "rx_cntr": (s >> 21) & 0xF,
        }

    def idle(self) -> bool:
        st = self.status()
        return st["tx_st"] == "IDLE" and st["rx_st"] == "IDLE"


def _check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def probe(x: Xcom, cfg: int = 15, settle: float = 0.01) -> bool:
    """The H1 sequence. Returns True only if every check passed."""
    results = []
    print(f"\nxcom @ 0x{XCOM_BASE:08x}  (cfg_tick={cfg})")

    # (1) the slave decodes at all. A bus that is not there reads 0xffffffff or hangs; board_id
    #     reading back as a plausible small value is the first evidence the address is right.
    bid = x.rd("board_id")
    results.append(_check("AXI-Lite slave decodes", bid != 0xFFFF_FFFF, f"board_id=0x{bid:x}"))

    # (2) reset state. XCOM's registers come up zeroed; a nonzero id here means the active-low
    #     resets are miswired (the classic error is driving them from proc_sys_reset's
    #     active-HIGH peripheral_reset instead of peripheral_aresetn).
    results.append(_check("board_id is 0 after reset", bid == 0,
                          "nonzero id => check i_*_rstn polarity" if bid else ""))

    # (3) a LOCAL command takes effect — the command path works before the link is involved.
    x.cmd("SET_ID", dt1=1)
    time.sleep(settle)
    bid = x.rd("board_id") & 0xF
    results.append(_check("SET_ID assigns board id 1", bid == 1, f"board_id={bid}"))

    # (4) the bit-rate tick. xcom_cfg resets to 0, which STOPS the serializer: nothing transmits
    #     until this is written, and a silent link with everything else correct is usually this.
    x.wr("cfg", cfg)
    time.sleep(settle)
    results.append(_check("cfg_tick written and reads back", x.rd("cfg") == cfg, f"cfg={x.rd('cfg')}"))

    # (5) both FSMs sitting in IDLE before we transmit, so step 6 starts from a known state.
    st = x.status()
    results.append(_check("tx/rx FSMs idle before send", x.idle(),
                          f"tx={st['tx_st']} rx={st['rx_st']}"))

    # (6) the headline: a 32-bit word out of the transmitter, around the loopback, and back into
    #     dt1. dst=1 is this board's own id, which the receiver accepts (it also accepts dst=0 as
    #     a broadcast, xcom_link_rx.sv:182).
    payload = 0x1234_BEEF
    x.cmd("SEND_32BIT_1", dt1=1, dt2=payload)
    got, waited = None, 0.0
    while waited < 0.5:
        time.sleep(0.005)
        waited += 0.005
        if x.rd("dt1") == payload:
            got = payload
            break
    got = x.rd("dt1") if got is None else got
    results.append(_check(f"32-bit word 0x{payload:08X} crosses the link", got == payload,
                          f"dt1=0x{got:08x} after {waited * 1e3:.0f} ms"))
    if got != payload:
        st = x.status()
        print(f"         triage: tx_st={st['tx_st']} rx_st={st['rx_st']} rx_cntr={st['rx_cntr']} "
              f"tx_ready={st['tx_ready']}")
        print(f"         tx_dt=0x{x.rd('tx_dt'):08x} rx_dt=0x{x.rd('rx_dt'):08x}")
        print("         tx IDLE + rx IDLE with tx_dt set => never transmitted (check cfg_tick).")
        print("         rx stuck in HEADER/DATA => edges arrive but the packet never completes.")
        print("         rx_dt shifted by a bit or two => sampling margin; slow the link down.")

    # (7) and it returns to idle, i.e. the transfer completed rather than merely starting.
    results.append(_check("tx/rx FSMs return to idle", x.idle(), f"status=0x{x.rd('status'):08x}"))

    return all(results)


def ber(x: Xcom, cfg: int, count: int = 2000) -> tuple[int, int]:
    """Push `count` pseudorandom words through the link at this cfg_tick. Returns (errors, sent)."""
    import random
    rng = random.Random(0xC0FFEE)       # fixed seed: a failing run is reproducible
    x.wr("cfg", cfg)
    time.sleep(0.01)
    errors = 0
    for _ in range(count):
        word = rng.getrandbits(32)
        if word == x.rd("dt1"):         # would be indistinguishable from a stale read
            word ^= 1
        x.cmd("SEND_32BIT_1", dt1=1, dt2=word)
        deadline = time.time() + 0.05
        while time.time() < deadline and x.rd("dt1") != word:
            pass
        if x.rd("dt1") != word:
            errors += 1
    return errors, count


def sweep(x: Xcom, count: int = 2000) -> None:
    """Walk cfg_tick from slowest to fastest and record where reception breaks.

    The bit period is cfg_tick time-clock cycles (xcom_link_tx.sv: tick_dt fires at
    tick_cnt == i_cfg_tick). The field is 4 bits, and xcom_link_rx.sv abandons a packet after 32
    local clocks with no edge, so the usable range is bounded at both ends: you cannot slow this
    link below ~32 cycles per bit for cable margin without lowering the time clock itself.
    """
    print(f"\nbit-rate sweep ({count} words per step, 500 MHz time clock assumed)")
    print("  cfg  bit period   rate        errors")
    for cfg in range(15, 3, -1):
        errors, sent = ber(x, cfg, count)
        ns = cfg * 2.0
        print(f"  {cfg:>3}  {ns:>6.0f} ns   {1e3 / ns:>6.1f} Mb/s  {errors:>5}/{sent}"
              + ("" if errors == 0 else "   <-- breaks here"))
        if errors:
            print(f"\n  slowest reliable setting is cfg_tick={cfg + 1}; keep a step of margin.")
            return
    print("\n  no errors down to cfg_tick=4 — the fabric loopback has no signal-integrity limit,")
    print("  which is expected. Re-run this over a real cable (RISCQ_XCOM_LOOPBACK=0).")


def main() -> int:
    ap = argparse.ArgumentParser(description="XCOM hardware bring-up probe (H1)")
    ap.add_argument("--base", type=lambda v: int(v, 0), default=XCOM_BASE,
                    help="AXI base of the xcom slave (default 0x90000000)")
    ap.add_argument("--cfg", type=int, default=15, help="cfg_tick bit period, 4-15 (default 15)")
    ap.add_argument("--sweep", action="store_true", help="also sweep the bit rate and count errors")
    ap.add_argument("--count", type=int, default=2000, help="words per sweep step (default 2000)")
    args = ap.parse_args()

    x = Xcom(args.base)
    ok = probe(x, cfg=args.cfg)
    if args.sweep:
        sweep(x, args.count)

    print("\n" + ("H1 PASS — xcom is alive on silicon and the link carries data."
                  if ok else "H1 FAIL — see the triage lines above."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
