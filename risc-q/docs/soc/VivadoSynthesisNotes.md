# Vivado synthesis notes — `comm-module-xcom`, first real Vivado run

**Date:** 2026-10-11 · **Tool:** Vivado 2024.1 · **Part:** `xczu49dr-ffvf1760-2-e` (ZCU216)
**Build:** `RISCQ_QICK=1` (QICK gen_v6 variant, `software/configs/zcu216-qick-1q.json`) with XCOM on,
in-fabric loopback, AXI base `0x9000_0000` — this branch's default.

**Sources:** `vivado-scripts/riscvsoc-bd/` · `firmware/ip/xcom/` · `src/riscq/soc/comm/` ·
[`XcomBringup`](XcomBringup.md)

## Summary

- The XCOM flow had previously been checked for Tcl parse-completeness only. This was its first
  real Vivado run.
- The full SoC with XCOM now goes through block-design validation and synthesis with **0 errors**
  (all 10 synthesis runs).
- Getting there took three fixes, all outside the XCOM code (see below).
- XCOM's own block-design wiring validated on the first attempt: resets, loopback, tie-offs, the
  address map and the shared SmartConnect port counter.
- The XCOM IP, `XcomMemMap` and the accelerator socket each meet **500 MHz** after standalone
  place-and-route.
- **Not done yet:** full-SoC implementation and bitstream, and the on-board `xcom_probe` run.

## Results

### Standalone, post-route (out-of-context, 500 MHz core clock)

| Block | LUTs | FFs | BRAM / DSP | WNS (setup) | WHS (hold) | Est. Fmax |
|---|---|---|---|---|---|---|
| XCOM IP (`NCH=1 SYNC=1 DEBUG=1`), `dspClk` 500 MHz | 566 | 1,495 | 0 / 0 | +0.341 ns | +0.048 ns | ~600 MHz |
| XCOM IP, `hostClk` 100 MHz (AXI side) | — | — | — | +7.214 ns | +0.045 ns | — |
| `XcomMemMap` (delta over control block) | +29 | +72 | 0 / 0 | +0.487 ns | +0.056 ns | ~660 MHz |
| `AccelResultSink` (delta over control block) | +4 | +33 | 0 / 0 | +0.592 ns | +0.054 ns | ~710 MHz |

- **Comm module total (XCOM + `XcomMemMap`):** 595 LUT / 1,567 FF, about 0.14% / 0.18% of the
  device.
- **XCOM by submodule:**

  | Submodule | LUTs | FFs |
  |---|---|---|
  | `xcom_txrx` | 252 | 761 |
  | `xcom_axil_slv` | 174 | 215 |
  | `xcom_cmd` | 97 | 46 |
  | `xcom_cdc` | 44 | 473 |

  About a third of the FFs are CDC synchronizers, because the IP runs on three clock domains.
- **XCOM worst path:** `xcom_link_rx/s_header_shreg` → reset of `xcom_txrx/mem_data_reg`. It has 2
  logic levels and 78% of its delay is routing, so it is a fanout/placement issue rather than deep
  logic.
- **How the delta rows were measured:** they are the core control block (`MemMapFiber` +
  `TimeMemMap`) with the block, minus the same control block without it. The wrappers come from
  `riscq.soc.comm.GenCommStats`.
- **What OOC timing covers:** register-to-register paths inside the block only; boundary ports were
  not constrained.

### Full SoC, post-synthesis

| | LUTs | FFs | BRAM | URAM | DSP |
|---|---|---|---|---|---|
| Whole design | 40,539 (9.53%) | 51,130 (6.01%) | 197 (18.24%) | 1 (1.25%) | 209 (4.89%) |
| `top` (PulseTableSoc + QICK gen) | 21,955 | 32,919 | 197 | — | 209 |
| `smartconnect` | 7,272 | 9,898 | 0 | — | 0 |
| `xcom` | 574 | 1,495 | 0 | — | 0 |

- **XCOM's share:** about 1.4% of the design's LUTs, the same cost in place as standalone.
- **Synthesis timing:** every clock meets except `dspClk`, which misses by **−0.344 ns** on 81
  endpoints.
- **None of the failing paths are in XCOM.** They are `gen_rst` reset fan-out into the QICK gen's
  DSP `RSTB` pins (`signal_gen … prod_y_full_real…`). XCOM's paths in the report meet with about
  +9.8 ns of slack.
- Post-synthesis timing is an estimate; implementation may or may not recover these paths.

## Fixes made to get here

1. **`inc/package-ip.tcl`: IP packaging failed (IP_Flow 19-262).**
   - **Symptom:** with the QICK gen's VHDL sources in the project, `ipx::merge_project_changes
     ports` chose `synchronizer_n.vhd` as the top file and failed to parse `PulseTableSoc` from it.
   - **Fix:** the call is skipped when `QICK=1`. `ipx::package_project` has already inferred the
     ports from the same RTL, so there is nothing to merge.
2. **`inc/rfdc-config.tcl`: block-design validation failed (BD 41-758, `dac0/1/3_clk` unclocked).**
   - **Cause:** distributing the 9.58 GHz *sample* clock from DAC tile 2 (`Clock_Dist 2`, PLLs off
     elsewhere) does not validate.
   - **First change:** switched to QICK's own `qick_tprocv2_216_standard` layout. Tile 2
     distributes the 245.76 MHz *reference* (`Clock_Dist 1`) and every tile runs its own PLL.
   - **Second change:** changing PLL/refclk resets each tile's `Clock_Source` to its own pin, so
     `DAC{0,1,3}_Clock_Source` is set back to 6 in a separate `set_property`.
3. **Environment: license.**
   - **Symptom:** synthesis failed with Common 17-345 ("no valid license … xczu49dr").
   - **Cause:** the Enterprise license in `/tools/Xilinx/licenses` is valid for this part and
     machine, but Vivado only finds it when `XILINXD_LICENSE_FILE` is set:
     ```bash
     export XILINXD_LICENSE_FILE=/tools/Xilinx/licenses
     ```
4. **Environment: build machine setup.**
   - `ext/SpinalHDL` (v1.14.2) and `ext/rvls` (`riscq-machine-only-csr-stubs`) are empty in a fresh
     clone, because the subtree import does not bring submodules. Clone them before running mill.
   - Mill 1.1.0 and JDK 17 are required.

## Open issues

1. **`$readmem` init files are dropped (critical, Synth 8-4445).**
   - **What is lost:** the three `.bin` files `PulseTableSoc.v` loads (register file, GShare
     counters, QICK gate parameter table) are not found during IP synthesis, so those memories
     start at **zero** in hardware.
   - **Cause:** the IP packager ignores `.bin` sources (IP_Flow 19-5226). This is likely not
     QICK-specific.
   - **Fix before trusting a bitstream:** add the files to the packaged IP's file group, or emit
     absolute `$readmem` paths.
2. **`signal_gen_v6.xdc` not applied (critical, Designutils 20-1281).**
   - The gen's own constraints (CDC false paths) are scoped to `axis_signal_gen_v6`, which no
     longer exists under that name once everything is packaged into `PulseTableSoc`.
   - **Possibly related to** the `dspClk` synthesis miss; not confirmed.
3. **`dspClk` −0.344 ns at synthesis**, in QICK gen reset paths (see above). Re-check after
   implementation.
4. **XCOM CDC report:** 3 critical CDC-10 warnings (combinational logic before a synchronizer).
   All are on the PS `status`/`debug` readback, not the data path. This is upstream QICK RTL.
5. **XCOM interface definitions (BD 41-51/41-49):** xcom's `component.xml` references
   `Fermi:user:qick_*` bus types, while `firmware/ip/qick_interfaces` defines `QICK:QICK:*`. These
   warnings are harmless because the individual pins are wired.
6. **Intentional tie-offs:** `QICKGEN*_S0_AXIS` `valid` is tied to 0 (no envelope DMA yet), and
   XCOM's core command port and `i_sync` are tied off (PS-driven bring-up).
7. **Build speed:** `inc/run.tcl` launches with `-jobs 1`, so the OOC IP runs are serialized.

## Reproducing

**Full SoC, synthesis only.** `build-riscvsoc-bd.sh` always enables implementation, so call the flow
directly:

```bash
cd risc-q && mill runMain riscq.soc.GenPulseTableSocJson software/configs/zcu216-qick-1q.json \
  build/riscvsoc-bd-qick vivado qick
cd vivado-scripts/riscvsoc-bd
XILINXD_LICENSE_FILE=/tools/Xilinx/licenses RISCQ_PROJ_NAME=riscvsoc-bd-qick \
  RISCQ_BUILD_DIR=$PWD/../../build/riscvsoc-bd-qick RISCQ_QICK=1 RISCQ_IP_RETIMING=1 \
  RISCQ_RUN_SYNTH=1 RISCQ_RUN_IMPL=0 RISCQ_RUN_BITSTREAM=0 \
  vivado -mode batch -nojournal -log ../../build/riscvsoc-bd-qick/vivado.log -source flow-bd.tcl
```

**Full flow (impl + bitstream + XSA):**

```bash
RISCQ_QICK=1 ./build-riscvsoc-bd.sh
```

**Standalone block stats:**

1. Generate the wrappers with `mill runMain riscq.soc.comm.GenCommStats build/comm-stats/rtl`. This
   writes `CtrlBase.v`, `CtrlAccel.v` and `CtrlXcom.v`.
2. Synthesize each out-of-context with a 2.000 ns clock on `clk`, then
   `opt/place/phys_opt/route_design`.
3. For XCOM itself, read `firmware/ip/xcom/src/*.sv` (`qick_pkg.sv` and `fxp_pkg.sv` first) and
   run `synth_design -top xcom -mode out_of_context -generic NCH=1 -generic SYNC=1 -generic
   DEBUG=1`. Use `i_ps_clk` at 10 ns and `i_core_clk`/`i_time_clk` at 2 ns, as asynchronous
   groups, with a false path from `i_xcom_*`.

## Next steps

1. Fix the `.bin` packaging and the `signal_gen_v6.xdc` scoping, then re-synthesize.
2. Run full implementation and check post-route `dspClk` timing.
3. Generate the bitstream and run `sudo python3 -m riscq.board.xcom_probe` on the ZCU216 (PYNQ,
   over Ethernet).
4. Wire `XcomMemMap` and `AccelResultSink` (`withAccel`) into `PulseTableSoc`, then measure them
   in-SoC.
