# XCOM hardware bring-up — getting a flashable bitstream with the board link in it

**Sources:** `src/riscq/soc/comm/{Xcom,XcomMemMap}.scala` · `firmware/ip/xcom/` ·
`vivado-scripts/riscvsoc-bd/{inc/config.tcl,inc/bd-build.tcl,constraints-xcom*.xdc}` ·
`software/riscq/board/xcom_probe.py`

## State of the module

Everything proven so far is proven **in simulation**, on a single simulation clock:

```
$ mill runMain riscq.soc.sim.XcomSim
[XcomSim] board ids assigned: A=1  B=2
[XcomSim] A -> B 32-bit : 0xc0ffee01 received intact in 91 core clocks (40 strobe edges)
[XcomSim] QRST_SYNC    : A proc_start at cycle 494, B at 494  -> SKEW 0
[XcomSim] QCTRL/011    : B time_update fired at cycle 43 with 0x0000abcd
[XcomSim] PASS

$ mill runMain riscq.soc.sim.XcomMemMapSim
[XcomMemMapSim] CPU A -> CPU B : 0x1234beef crossed the link and was read over MMIO
[XcomMemMapSim] PASS
```

Two things about those results are worth stating plainly, because they are easy to over-read:

- **Both "boards" share one clock.** `XcomSim`'s mesh drives all three of each instance's clock
  domains — `i_ps_clk`, `i_core_clk`, `i_time_clk` — from the same simulation clock, and wires the
  two instances together inside that one domain. The zero-skew `QRST_SYNC` result is real but it is
  a zero-skew measurement between two things on the same clock. Nothing about independent clock
  domains, pins, cables or signal integrity has been tested.
- **The time-counter commit is verified at XCOM's output pin, not inside RISC-Q.** `XcomSim` checks
  that `o_time_update` pulses with the right data. That signal is *not connected* to
  `PulseTableSoc`'s `timeOffset` — the sim's own log line calls it "the timeOffset hook" for that
  reason. Wiring it is milestone H3, and it is a subtract, not an assign (see below).

## What is in the bitstream

XCOM is **off by default**, so the default build is unaffected by its presence in the flow:

```bash
./build-riscvsoc-bd.sh                                      # no xcom — unchanged from before
RISCQ_WITH_XCOM=1 ./build-riscvsoc-bd.sh                    # + xcom, in-fabric loopback (no pins)
RISCQ_WITH_XCOM=1 RISCQ_XCOM_LOOPBACK=0 ./build-riscvsoc-bd.sh   # + xcom, link out to PMOD pins
```

With `RISCQ_WITH_XCOM=1` the packaged QICK IP is instantiated **beside** `PulseTableSoc`, not inside
it, with its AXI-Lite slave on the SmartConnect at `0x9000_0000` (`RISCQ_XCOM_BASEADDR`). That
address is deliberately **outside** the SoC's `0x8000_0000 + 0x1000_0000` window, so
`PynqDriver`'s existing `pynq.MMIO(AXI_BASE, AXI_SIZE)` mapping is untouched.

### Composing with the QICK gen_v6 variant

This branch sits on `waveword-bridge`, whose `RISCQ_QICK=1` variant drives QICK `axis_signal_gen_v6`
gens from the core and selects `software/configs/zcu216-qick-1q.json`. The two flags compose, and the
combination is the one worth building:

```bash
RISCQ_QICK=1 ./build-riscvsoc-bd.sh                    # what gets flashed today, no link
RISCQ_QICK=1 RISCQ_WITH_XCOM=1 ./build-riscvsoc-bd.sh  # ... plus the board link
```

**Both features add SmartConnect manager ports**, so the port index comes from a single shared
`$_mi` counter rather than a hardcoded `M02`: the gens take one each from `M02` up, then XCOM takes
the next. Giving XCOM a fixed `M02` works with `RISCQ_QICK=0` and silently collides with the first
gen when both are on — it would connect two masters to one port, which Vivado reports as a BD
validation error far from the cause. Verified by sourcing the flow with every Vivado command stubbed
across all six flag combinations; with `RISCQ_QICK=1 RISCQ_WITH_XCOM=1` and two gens the allocation
comes out `M02`/`M03` = gens, `M04` = xcom.

Three reasons for beside-rather-than-inside:

1. **Observability.** The AXI-Lite slave is the only route to `xcom_cfg`, `board_id`, `status`,
   `debug`, `rx_dt` and `tx_dt`. On silicon there is no VCD; those registers are the instrument, and
   `status`/`debug` alone separate "never transmitted" from "transmitted, never received" from
   "received, stuck mid-packet".
2. **No SoC change is needed at this stage**, so this milestone does not queue behind anything in
   `PulseTableSoc`.
3. **Link config has to come from the PS anyway.** `xcom_cfg` resets to 0, which stops the
   serializer — until something writes it, the link is silent with everything else correct.

The RISC-V command port (`i_core_*`) is **tied off**: this build exercises the link entirely from the
PS. `XcomMemMap` is not in the design yet.

| Knob | Default | Meaning |
|---|---|---|
| `RISCQ_WITH_XCOM` | `0` | instantiate the IP at all |
| `RISCQ_XCOM_LOOPBACK` | `1` | `1` = tx tied back to rx in fabric; `0` = out to PMOD0/PMOD1 |
| `RISCQ_XCOM_NCH` | `1` | receive channels; 1 = point-to-point or loopback |
| `RISCQ_XCOM_BASEADDR` | `0x90000000` | AXI-Lite base of the slave |

## Testing it on the board

```bash
sudo python3 -m riscq.board.xcom_probe            # the H1 sequence
sudo python3 -m riscq.board.xcom_probe --sweep    # + bit-rate sweep and error count
```

The probe talks raw `pynq.MMIO`, deliberately not through `qick.drivers.xcom.QICK_Xcom`: that
driver's `bindto` lists `fnal:qick:xcom:1.0` while `firmware/ip/xcom/component.xml` declares
`QICK:QICK:xcom:1.0`, so it will not auto-bind to this overlay. The register map and the
`status`/`debug` bit decode are copied from it so results stay comparable with QICK's tooling.

It checks, in order: the slave decodes; `board_id` is 0 after reset (a nonzero value here means the
**active-low** resets are miswired — the classic error is driving `i_*_rstn` from
`proc_sys_reset`'s active-HIGH `peripheral_reset` instead of `peripheral_aresetn`); `SET_ID` takes
effect; `cfg_tick` reads back; both FSMs are idle; a 32-bit word crosses the link and reads back
bit-exact; both FSMs return to idle. On failure it dumps the decoded `status`, `tx_dt` and `rx_dt`
with the triage tree.

**What in-fabric loopback proves.** Tx tied back to rx, one clock, no pins, no cable — the closest
hardware analogue of the passing sim. So a failure is a synthesis, clocking or constraints problem
and nothing else. That isolation is the point of doing it before the cable. It proves nothing about
signal integrity, nothing about two independent clock domains, and **it does not exercise the local
`o_core_data1/2` patch** in `xcom.sv:344` — the AXI `dt1`/`dt2` read path goes through a separate
CDC (`s_core_data1_ps`), so the patch stays untested until the core port is wired.

## Constraints

- `constraints-xcom.xdc` (added whenever the IP is in the design) sets `ASYNC_REG` on the rx
  synchronizer flops. `xcom_txrx.sv:324-337` does put proper equal-depth 2-FF `synchronizer` chains
  on the incoming link clock and data, and `xcom_link_rx.sv` samples the *delayed* data against the
  clock edge, so a cycle of clk/data skew is tolerated — the RTL is right. But `synchronizer.sv`
  sets no `ASYNC_REG`, so without this the tool may retime or relocate those flops and the MTBF the
  chain exists to provide is not actually delivered.
- `constraints-xcom-pins-zcu216.xdc` (pin mode only) carries the pinout and the false paths. Pin
  numbers are taken from QICK's own ZCU216 project
  (`firmware/projects/qick_tprocv2_216_standard/ios.xdc`) rather than re-derived: PMOD0 transmits
  (`G15` clk, `G16` data), PMOD1 listens (`L17` clk, `M17` data), all `LVCMOS18` — both headers are
  1.8 V banks on this board.

## Things known to bite, before they do

**The link cannot be slowed below ~32 cycles per bit.** The bit period is `cfg_tick` time-clock
cycles (`xcom_link_tx.sv`: `tick_dt` fires at `tick_cnt == i_cfg_tick`), the field is 4 bits, and
`xcom_link_rx.sv` abandons a packet after 32 local clocks with no edge. At a 500 MHz time clock
that is 8–30 ns per bit, i.e. 33–125 Mb/s, and a 40-bit packet (8-bit header + 32-bit payload)
takes ~1.2 µs at the slow end. You cannot back the rate off further for cable margin without
lowering the time clock itself.

**Loading the time counter is a subtract, not an assign.** RISC-Q computes
`time = refTime + timeOffset` with a free-running, never-reset `refTime`
(`PulseTableSoc.scala:145`), while `o_time_update_data` is an *absolute* time to load. The correct
hookup is `timeOffset := o_time_update_data - refTime`. Assigning the data straight into
`timeOffset` leaves each board offset by its own arbitrary `refTime` — a failure that presents as
"sync doesn't work" with no obvious cause.

**`QRST_SYNC` and `QCTRL` are different mechanisms.** Op `0x08` asserts only `o_proc_start` (the
aligned "everyone go"); op `0x0b` with payload `3'b011` is what reaches the time counter, and it
commits whatever a *prior* `SEND_32BIT_1` left in the peer's `reg1`. Always two steps.

**`i_sync` is tied low.** It is the external reference tick `QRST_SYNC` aligns to. Nothing in this
build uses it, and it is the one signal with no fallback once two boards are involved, so it is left
as an explicit open item rather than an accident. `user_sysref` is already an LVDS input on this top
level and is the obvious candidate.

**Two boards will need a common clock reference.** Each board's `refTime` ticks on its own CLK104
LMK. Without locking both to a shared external reference, any alignment decays immediately — drift
that imitates a sync bug.

## Status of these changes

The flow changes are **written but not yet run**: there is no Vivado on the development machine, so
they have been checked for tcl parse-completeness only. The first `RISCQ_WITH_XCOM=1` build is the
real test of them. The base (`RISCQ_WITH_XCOM` unset) path is untouched and its RTL generation is
verified.

## Related

- [`RiscvSoc`](RiscvSoc.md), [`PulseTableSoc`](PulseTableSoc.md) — where `XcomMemMap` and the
  `timeOffset` hookup land next.
- [`ControlMemMaps`](ControlMemMaps.md) — the CPU-side register-block convention `XcomMemMap`
  follows.
