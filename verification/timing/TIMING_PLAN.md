# QICK timing characterization plan (tProc → SGv6 channel 0)

Scope: characterize **command acceptance time, start time, and ordering** on the
existing QICK reference, as a timing reference and verification model for the
controller team's RISC-Q adapter. The RISC-Q characterization comes after the QICK
reference is frozen.

Based on the 2026-09-25 12:33 session plan (session `7e23be69`). Changes merged in
from session `f265f2e7` are tagged:
- **[NEW]**: added
- **[CHANGED]**: modified from the old plan
- **[CORRECTION]**: fixes an earlier claim

Everything else is the old plan unchanged.

Status: **plan only. Nothing implemented yet.** The `verification/timing/` directory
is local only (not committed or pushed).

Decisions (confirmed):
- Monitors are **always on**.
- Dispatcher internals are **logged with E2**.
- New directories stay **local only**.

---

## Step 0: Define the events

**Event numbering (2026-09-27):** events are numbered in the order a command passes them. E1 = on timeline and E2 = release were swapped from the 12:33-session numbering, where they were E2 and E1.

"Timing" becomes measurable once you fix a list of events that every command passes
through. Log each event for every command:

| Event | What it means | Signal (full hierarchical path from `QICKEmu_harness`) | Clock | Log when |
|---|---|---|---|---|
| **[NEW] E0i issue** | The core emits the wave-port write (the program-order baseline) | `qick_dut.AXIS_QPROC.QPROC.port_we`, `...QPROC.out_port_data` (`p_type`, `p_addr`, `p_time`), `...QPROC.c_time_ref_dt[47:0]` (source: `qcore_cpu.sv:719-722`, stage X2) | `c_clk` | `port_we` is high and `p_type==0` (wave port) |
| **E0 schedule** | The core puts the command in the wave FIFO; **due time** is recorded | `qick_dut.AXIS_QPROC.QPROC.DISPATCHER.c_fifo_wave_push_s[0]`, time = `...DISPATCHER.c_fifo_time_in_r[47:0]` | `c_clk` | `push_s[0]` is high |
| **[NEW] E1 on timeline** | The command becomes visible on the `t_clk` side of the dispatcher FIFO (happens before the release) | `...DISPATCHER.t_fifo_wave_empty[0]` falls, plus `t_time_abs_o` | `t_clk` | falling edge |
| **E2 tProc acceptance** | tProc releases the command and the CDC accepts it | `qick_dut.tproc_sg0cdc_axis_{tvalid,tready,tdata[167:0]}` plus `t_time_abs_o[47:0]` (harness wire) | `t_clk` | `tvalid && tready` |
| **E3 SGv6 acceptance** | The command enters SGv6's FIFO. This is **the boundary the adapter must reproduce** | `qick_dut.sgt0_sg0_axis_{tvalid,tready,tdata[159:0]}` | `sg_clk` | `tvalid && tready` |
| **E4 SGv6 start** | SGv6 takes the command out of its FIFO and starts playing it | `qick_dut.u_axis_signal_gen_v6_0.signal_gen_top_i.signal_gen_i.ctrl_i.load_int`, plus `...ctrl_i.fifo_dout_i[143:128]` (`nsamp`). **[NEW]** Verified: `load_int = rd_en_int & ~fifo_empty_i` (`ctrl_sg_v6.sv:534`) | `sg_clk` | `load_int` is high |
| **E5 output start/stop** | The generator's output enable goes on or off | `...ctrl_i.en_o`: log the rising and falling edges | `sg_clk` | edge |
| **E6 DAC** | First non-zero DAC sample. **[CHANGED]** Optional for now: the physical DAC is out of the current scope | Already logged: `<EMU_DIR>/dac_out_ch0.csv` | `sg_clk` | first non-zero row |

With these events you get three kinds of result:
- **Acceptance time:** E2 and E3. **[NEW]** Also E0 − E0i (core-to-dispatcher acceptance, including stalls when `some_fifo_full`, `qproc_ctrl.sv:236`) and E1 (lead margin = due − `t_time_abs` at E1).
- **Start time:** E4 and E5. E6 is the physical confirmation, but it depends on the envelope; a Gaussian starts near zero, for example.
- **Ordering:** whether the k-th command at E0 is also the k-th at E2, E3 and E4. **[NEW]** E0i is the program-order baseline.

You can skip the CDC output (`sg0cdc_sgt0_axis_*`). The translator is combinational, so it's the same cycle as E3.

**[NEW] What each layer shows that reading the code can't:**

| Layer | Pipeline / latency it isolates | Clock relationship | Measurement reveals |
|---|---|---|---|
| E0i→E0 | 1 `c_clk` register + core stall (`core_en=0`) | `c_clk` | Real acceptance delay; whether the core stalled |
| E0→E1 | `BRAM_FIFO_DC_2` c→t CDC (`_qproc_ips.sv`, the `ifdef VERILATOR` variant at ~line 816) | `c_clk` 200 MHz, async to `t_clk` 430 MHz | CDC latency spread; minimum lead needed for an on-time release |
| E1→E2 | `time_abs_r` → `wave_t_gr_r` (strict `>`) → `wave_pop` → `m_axis_tvalid_r` (`qproc_dispatcher.sv:202, 284-293, 384-400`) | `t_clk` only, so it should be deterministic | Exact release offset vs. due; spacing ≥ 3 `t_clk`; late-command behavior |
| E2→E3 | `cdcsync` (one FIFO shared by SG0–2) + translator (0 cycles) | `t_clk`, async to `sg_clk` 599.04 MHz | Transport latency and jitter; coupling between ports |
| E3→E4 | SGv6 FIFO + `READ_ST`/`CNT_ST` FSM | `sg_clk` | Queue wait; start = max(arrival, previous end) |
| E4→E5 | `en_reg` 8-stage alignment pipeline | `sg_clk` | Fixed output latency (~8–9 `sg_clk` expected) |

## Step 1: Learn how the reference runs

- **Where programs come from:** a notebook builds an `AveragerProgramV2`. Then `soc.prepare_emu(memdir=OUT, …)` and `prog.acquire_decimated(soc, …)` write the artifacts (`pmem.mem`, `wmem.mem`, `axi_replay.txt`, …) and run Verilator. See `emulator/notebooks/00_intro_emu.ipynb` and `emulator/software/qick_emu.py:817, :1019, :1303`.
- **Running by hand:** from `emulator/testbench`, run `make sim SIM_EMU_DIR=<dir> TRACE=1 SIM_ARGS="+TEST_RUN_NS=… +PRE_RUN_DELAY_NS=…"`. Rebuild with `make verilate` whenever you change the harness.
- **When time starts:** the replayed AXI write `PROC_START` (`TPROC_CTRL` bit 2, the last line of `artifacts/test_sim/axi_replay.txt`) starts `time_abs` from 0.
- **Output file locations:**
  - The VCD goes to `<EMU_DIR>/waveform.vcd` (`QICKEmu_harness.sv:759`). The Makefile comment saying `obj_dir` is out of date.
  - `tproc_ctrl.csv` is opened with a **relative path** (`:1403`), so it lands in `emulator/testbench/` and **every run overwrites it**. Copy it into the run folder after each run.
- **Time units:** `%0t` prints in **ps**. The DAC CSV header is `time_ps`, and consecutive rows are 1669.344 ps apart, which is one `sg_clk` period. Use `%0t` in new loggers too, so all files share the same unit.

## Step 2: Build a set of test programs

Make each program a **separate run folder** so the results stay traceable. Use `style='const'` pulses so the output is non-zero from the first sample. Give **each pulse a unique `gain`** (for example 0.1, 0.2, 0.3…). That value is a fingerprint you can find at every probe, which makes checking the order unambiguous.

| # | Program | What it tells you |
|---|---|---|
| T1 | One const pulse at t = 0.5 µs | The basic E0→E6 latency chain |
| T2 | Two pulses, with SGv6 idle in between (e.g. 0.1 µs long, Δ = 0.5 µs) | Whether spacing is preserved at E2, E3 and E4 |
| T3 | Same as T2 for several Δ values (e.g. 0.3, 0.5, 0.7 µs) | Whether latency stays constant as Δ changes |
| T4 | Back-to-back: pulse 2 at t = pulse 1's length | SGv6 queuing; E4[2] − E4[1] should equal `nsamp[1]` |
| T5 | Pulse 2 due *before* pulse 1 finishes (overlap) | What "late" looks like: E3 arrives on time but E4 waits |
| T6 | Write the later-time pulse first in `_body` | Whether release follows write order or time order (from the code, the FIFO releases only its head, in write order) |
| T7 | T2 repeated with `+PRE_RUN_DELAY_NS` = 0, 13, 37, 71 | How much the CDC delay varies with clock phase |
| **[NEW] T8** | Late command: due time already passed when the core issues it (e.g. a long compute before the pulse, or a small `t`) | Late behavior at E2: expect immediate release with no flag (strict `>` is already true) |
| **[NEW] T9** | Fill the dispatcher: many pulses issued far ahead, more than the SGv6 and CDC FIFOs hold | Acceptance stall: E0 − E0i grows when `some_fifo_full`; E2 held off by `tready` |
| **[NEW] T10** | Equal due time on SG0 and SG1 | Cross-port alignment through the shared CDC FIFO. **Needs the E2/E3/E4 monitors duplicated for SG1** (`tproc_sg1cdc_axis_*`, `sgt1_sg1_axis_*`, `u_axis_signal_gen_v6_1...`) |

Run `print(prog)` for each program and save the output. The listing shows the times the tProc will use, which you compare against E0. I haven't checked exactly how the listing prints times, so match it against the `c_fifo_time_in_r` values you log.

## Step 3: Get a feel for the timing on one waveform (T1 only)

Keep the run short (`+TEST_RUN_NS` just past the pulse), because VCDs get very large. In GTKWave, add the following in this order:
1. `t_clk`, `t_time_abs_o`, and `...DISPATCHER.wave_t_gr_r`, `wave_pop`, `wave_pop_r`
2. `tproc_sg0cdc_axis_tvalid/tready/tdata`
3. `sg_clk`, `sgt0_sg0_axis_tvalid/tready`
4. `...ctrl_i.state`, `load_int`, `cnt_nsamp_r`, `en_reg`, `en_o`
5. `axis_sg0_dac0_tdata`

Then trace one pulse. Mark each crossing and write down the count of `t_clk` or `sg_clk` edges between markers:
1. Find where `t_time_abs_o` passes the due time.
2. Follow it to `wave_t_gr_r`, then `wave_pop`, then `tvalid`. This is the tProc release delay.
3. Continue from the E2 handshake, across the CDC, to the E3 handshake.
4. From E3 to `load_int` (E4): SGv6 is idle, so this is just its FIFO latency.
5. From `load_int` to `en_o` rising: from the code, this should be about 8–9 `sg_clk`.
6. Check that `en_o` stays high for about `nsamp` `sg_clk` cycles, and that the DAC data changes in the same window.

## Step 4: Replace eyeballing with CSV loggers

A waveform is good for building intuition, but CSVs give repeatable numbers. They also become the reusable monitor for the controller team's prototype later. Copy the pattern of the existing logger (`QICKEmu_harness.sv:1397-1431`), with one file per event. (See "Planned changes A" below for the full file list.)

Rules for all the loggers:
- Put every file in `EMU_DIR`, not the working directory.
- Timestamp every row with `%0t`.
- Include the fingerprint fields (`gain` at minimum) so rows can be matched across files.

## Step 5: Compute the results

For each command k, matched across files by fingerprint:

| Quantity | Formula | Unit | What to expect (hypotheses from the code) |
|---|---|---|---|
| **[NEW]** Core acceptance | `E0 − E0i` | `c_clk` | 1 cycle; larger only when the core stalled (T9) |
| **[NEW]** Lead margin | `due(E0) − t_time_abs(E1)` | `t_clk` ticks | Positive for an on-time release; ≤ ~3 means it will be late |
| Dispatch slack | `t_time_abs(E2) − due(E0)` | `t_clk` ticks | Small and **constant**. **[CHANGED]** RTL count predicts about **4** ticks on `t_time_abs_o`: time passes due at n, `time_abs_r` at n+1, `wave_t_gr_r` and pop at n+2, `tvalid` at n+3 |
| **[NEW]** Release spacing | `E2[k+1] − E2[k]` on one port | `t_clk` | ≥ 3 (the two-cycle blank after each pop) |
| CDC transport | `E3 − E2` | ps | Constant ± 1 `sg_clk` (T7 shows the spread). **[CHANGED]** Absolute value will be large in the emulator (see caveats) |
| SGv6 queue wait | `E4 − E3` | `sg_clk` | Constant when idle; grows in T4/T5 |
| Output pipeline | `E5↑ − E4` | `sg_clk` | Constant, about 8–9 |
| Duration | `E5↓ − E5↑` | `sg_clk` | = `nsamp` |
| Spacing | `E4[k+1] − E4[k]` vs. programmed Δ | ns | Equal when idle; = previous `nsamp` when back-to-back |
| Ordering | Sequence of fingerprints at E0i, E0, E2, E3, E4 | — | Identical sequences (T6 tests this) |

Treat every "expect" value as a hypothesis to confirm or refute, not a known result.

Caveats: these are **emulated** latencies. With `EMULATOR=1`, behavioral FIFO and DDS models replace the Xilinx IP. Keep the results labeled as "QICKEmu reference" and not "hardware".

**[NEW] Emulator swaps on the timing path, and what they affect:**

| Block | Verilator/emulator | Real build | Affects |
|---|---|---|---|
| Time adder (`qproc_time_ctrl.sv`) | custom, ignores `time_c_in` (+dt) | `ADDSUB_MACRO` (+dt+1 on update) | Absolute time after a time update (possible off-by-one) |
| Dispatcher FIFO `BRAM_FIFO_DC_2` (`_qproc_ips.sv`) | `ifdef VERILATOR` variant with an output register | XPM (`USE_XPM_MACROS`) | E0→E1 |
| SG CDC (`cdcsync.sv`) | `fifo_dc_sv`, **16-stage** write-pointer sync (depth parameter reused) | `fifo_dc_axi_xpm` | E2→E3 |
| SGv6 FIFO (`signal_gen_top.v`) | `fifo_behav` | `fifo_xpm` | E3→E4 |
| DDS | `emulator/models/dds_model` | Xilinx DDS compiler | E5→E6 |

Architectural results (ordering, strict compare, release spacing, `nsamp` duration, back-to-back chaining) come from shared RTL and should hold on hardware. The **absolute** E0→E1, E2→E3 and E3→E4 latencies are emulator-model numbers.

**[CORRECTION]** The `time_abs` crossing into `c_clk` uses a `sync_ab_en` handshake (`qproc_ctrl.sv:356`), which takes a snapshot and then copies it, so the value can't be read torn. The 12:33 session had this right. Session `f265f2e7` wrongly called it a plain 2-register crossing.

## Step 6: What to hand the controller team

Condense the results into a **timing contract at E3**, the SGv6 `s1` port:
1. For a pulse intended to start at time T, the command must be accepted at E3 at **T − (E4−E3 when idle) − (E5−E4)**, within the tolerance you measured in T7.
2. Commands must arrive at E3 in the same order as the reference sequence.
3. The adapter must never assert `tvalid` while `tready` is low. SGv6 writes its FIFO on `tvalid` alone (`signal_gen_top.v`, `fifo_wr_en = s1_axis_tvalid_i`), so a `tready` violation silently drops or overflows.
4. For back-to-back pulses, arriving early is fine: SGv6 chains them by `nsamp`. For idle gaps, arriving early starts the pulse early.
5. **[NEW]** The CDC is shared across SG0–2 (`fifo_rd_en = &dout_ready_v`). If the adapter keeps `axis_cdcsync_v1`, one stalled SG delays the other channels.

Their prototype then gets checked with the same E3, E4, E5 and E6 loggers. Only E0 and E2 get replaced by RISC-Q events (the `RfCmd` log, filtered to after reset release, plus the adapter's own release point).

---

# Planned changes

## A. QICK harness monitors (new file plus one include line)

- **New file** `emulator/testbench/timing_monitors.svh`, pulled into `QICKEmu_harness.sv` with one `` `include `` near the existing loggers.
  - Keeping it separate keeps the harness diff small, and the same file can be reused later for the RISC-Q-plus-adapter harness.
  - If Verilator can't find the file, I'll add `-I$(EMU_DIR)/testbench` to the Makefile.
- **Always on, writing into `EMU_DIR`** (confirmed). The files are small, and the notebook flow doesn't need any new arguments.
- **I won't touch** the existing `tproc_ctrl.csv` and `tproc_ro_ctrl.csv` loggers, so `ctrl_sg_cmp.py` keeps working.
- **Cycle counters:** a free-running counter for `c_clk`, `t_clk` and `sg_clk`, started at reset release. Every event gets a timestamp **plus** an integer cycle number, so latencies come out as exact cycle counts instead of floating-point ps differences.

The files written to `EMU_DIR`, one row per event:

| File | Trigger (verified path) | Clock | Columns |
|---|---|---|---|
| **[NEW]** `ev_e0i_issue.csv` | `qick_dut.AXIS_QPROC.QPROC.port_we` with `out_port_data.p_type==0` | `c_clk` | seq, time_ps, c_cyc, `p_addr`, `p_time`, `c_time_ref_dt`, `c_time_usr`, fields from `p_data` |
| `ev_e0_sched.csv` | `qick_dut.AXIS_QPROC.QPROC.DISPATCHER.c_fifo_wave_push_s[0]` | `c_clk` | seq, time_ps, c_cyc, due=`c_fifo_time_in_r[47:0]`, raw 168-bit `c_fifo_data_in_r` + fields |
| **[NEW]** `ev_e1_timeline.csv` | `DISPATCHER.t_fifo_wave_empty[0]` falling edge | `t_clk` | seq, time_ps, t_cyc, `t_time_abs_o`, head `t_fifo_wave_time[0]` |
| `ev_e2_tproc_out.csv` | `qick_dut.tproc_sg0cdc_axis_tvalid && tready` | `t_clk` | seq, time_ps, t_cyc, `t_time_abs_o`, fields. **[CHANGED]** Plus dispatcher internals (confirmed): `DISPATCHER.t_fifo_wave_time[0]` (head due at release), and the cycle numbers at which `wave_t_gr_r[0]` rose and `wave_pop[0]` fired for this command, so a late release can be attributed to `tready` or to compare timing |
| **[NEW]** `ev_e2_dispatch_trace.csv` | every `t_clk` where any of `wave_t_gr_r[0]`, `wave_pop[0]`, `wave_pop_r[0]`, `~t_fifo_wave_empty_r[0]`, `m_axis_tready[0]` changes | `t_clk` | time_ps, t_cyc, `t_time_abs_o`, the five bits. Compact change-only trace for debugging |
| `ev_e3_sg_in.csv` | `qick_dut.sgt0_sg0_axis_tvalid && tready` | `sg_clk` | seq, time_ps, sg_cyc, `nsamp`/`gain`/`addr`/`phase`/`freq`/`conf` bits |
| `ev_e4_sg_load.csv` | `qick_dut.u_axis_signal_gen_v6_0.signal_gen_top_i.signal_gen_i.ctrl_i.load_int` | `sg_clk` | seq, time_ps, sg_cyc, same fields from `ctrl_i.fifo_dout_i` |
| `ev_e5_sg_en.csv` | edges of `...ctrl_i.en_o` | `sg_clk` | seq, time_ps, sg_cyc, edge (rise/fall) |
| `ev_flags.csv` | SGv6 `s1` `tvalid && !tready` (**violation**); tProc `m0` `tvalid && !tready` (**stall**, legal but it delays pulses). **[NEW]** Also `some_fifo_full` / `core_en=0` intervals (acceptance stall) | per port | time_ps, cyc, kind |
| `ev_meta.csv` | once at start, and once when `t_time_abs_o` leaves 0 | — | the PROC_START moment, the four clock periods, `PRE_RUN_DELAY_NS`, `TEST_RUN_NS` |

For E6 (the DAC), I'll reuse the existing `dac_out_ch0.csv`. I won't add a logger for it.

**[NEW]** Queue-order note: the E1 falling edge only marks the first entry arriving in an empty FIFO. When several commands are queued, E1 is recorded only for commands that land in an empty FIFO. The analysis marks the others "queued behind head", with lead margin measured from the release of the previous entry instead.

**[NEW]** SG1 copies of E2/E3/E4/E5 (for T10) come in a second pass, after the SG0 set is validated.

## B. Verify the monitors on existing data (I run this)

1. `make verilate`, then `make sim SIM_EMU_DIR=../artifacts/test_sim`.
2. Check that the E2 rows match the `tproc_ctrl.csv` rows from the same run (same count, same data). That proves the new monitor and the existing one agree. **[NEW]** Also check that `tproc_ctrl.csv` is byte-identical to the pre-change file (the committed `emulator/testbench/tproc_ctrl.csv`, 9 commands).
3. Check that the counts are consistent: #E0i = #E0 = #E2 = #E3 = #E4 = #E5 rising edges, with no violations.
4. **[NEW]** Sanity-check against the RTL predictions: dispatch slack ≈ 4 `t_clk`, E2 spacing ≥ 3 `t_clk`, E5↓ − E5↑ = `nsamp`. If any fail, fix the monitor before interpreting results.

## C. Analysis script (standard library only, so no numpy needed)

`verification/timing/timing_analyze.py <run_dir>`:
- Matches each command across the E-files by position and checks that the fingerprint (`gain`, `nsamp`, `freq`) agrees. A mismatch is reported as an **ordering error**.
- Calculates, for each command:
  - **[NEW]** core acceptance `E0 − E0i` (`c_clk`) and lead margin `due − t_time_abs(E1)` (`t_clk`)
  - dispatch slack: `t_time_abs(E2) − due(E0)`, in `t_clk`
  - **[NEW]** release attribution from the dispatcher internals: compare wait vs. `tready` wait
  - E3 − E2, in ps
  - E4 − E3, in `sg_clk`
  - E5↑ − E4, in `sg_clk`
  - E5↓ − E5↑ compared with `nsamp`
  - spacing E4[k+1] − E4[k] compared with programmed spacing
  - E6 first non-zero sample (optional)
- Writes `timing_report.csv` plus a text summary with min/max/variation per stage.
- A second mode, `--sweep`, compares the same test across `PRE_RUN_DELAY_NS` runs to show how much the CDC delay varies.
- Runs with `/usr/bin/python3` (3.14, stdlib only), like `verification/control_signals/*.py`.

## D. Suite runner

`verification/timing/run_timing_suite.sh`, run by me:
- For each test folder (T1–T10) and each delay in {0, 13, 37, 71}: run `make sim` with that folder and delay.
- After each run, copy `ev_*.csv`, `dac_out_ch0.csv` and the console log into `verification/timing/runs/<test>/d<delay>/`. This is needed because every run in the same `EMU_DIR` overwrites the previous one's files. **[NEW]** Also copy `emulator/testbench/tproc_ctrl.csv`, since it's written relative to the working directory.
- Then run the analysis.

## E. Program generator (I write it; see F for who runs it)

`verification/timing/gen_timing_programs.py`, written in the same style as `00_intro_emu.ipynb`.
- It defines T1–T10 (const pulses, a unique `gain` per pulse, the timings from Step 2).
- For each test it calls `soc.prepare_emu(memdir=…)` and exports artifacts to `emulator/artifacts/timing/T<n>/`. `QickEmu.prepare()` (`qick_emu.py:1019`) is documented as export-only, so it doesn't run a simulation.
- It also saves `print(prog)` as `prog.txt` in each folder, as the record of programmed times.

I still need to confirm how `prepare_emu` plus `prepare` produce `axi_replay.txt`. The notebook gets there through `acquire_decimated`, and I'll trace that path while writing the script.

## F. Environments and who runs what [CHANGED]

Four separate environments; don't mix them:

| Env | Used for | Status on this machine |
|---|---|---|
| QICKEmu Python | E: generating T1–T10 artifacts (`numpy`, `qick` via `sys.path` → `qick_lib/`, `qick_emu` via `sys.path` → `emulator/software/`) | **Missing.** No `.venv`. `/usr/bin/python3` 3.14 has no numpy, and no `ensurepip`. Notebook metadata says `venv (3.9.25)`, which doesn't exist here |
| QICK RTL replay | A, B, D | ✅ `make` + Verilator 5.032 (the `emulator/submodules/verilator/bin` wrapper is on PATH but the submodule isn't built, so it falls through to `/usr/bin/verilator_bin`), g++ 15.2, gtkwave |
| Verification Python | C | ✅ `/usr/bin/python3`, stdlib only |
| RISC-Q (deferred) | later | ✅ `~/projects/RISC-Q/mill` 1.1.0 with the coursier-managed Zulu JDK 21 (no `java` on PATH needed). `riscv64-unknown-elf-gcc -march=rv32i -mabi=ilp32` builds RV32 ELFs (tested) |

**Hand-run (you), to create the QICKEmu Python env with `emulator/setup_emulator.sh`:**
1. `! sudo apt install -y python3-venv python3-pip python3.14-venv`. The script exits early without `ensurepip`.
2. `! ./emulator/setup_emulator.sh`, and answer **N** to the Verilator 5.042 build, so the toolchain stays fixed at 5.032 during characterization. GTKWave is already installed and is skipped.
3. What it creates:
   - `<repo>/.venv` (Python 3.14, from `python3` on PATH), with `requirements.txt` (numpy, scipy, matplotlib, ipykernel, jupyter, tqdm) plus `pip install -e .` (qick from `qick_lib/`)
   - `qick_lib/qick.egg-info/` (gitignored)
   - a Jupyter kernel `qick-venv` in `~/.local/share/jupyter/kernels/`
   - No QICK/QICKEmu source is modified. `.venv/` is **not** gitignored, so it will show as untracked.
4. If pip starts compiling numpy or scipy from source (no 3.14 wheels), stop and tell me. We'd pick another interpreter.

Once `.venv` exists, I can run E myself with `<repo>/.venv/bin/python`. Until then, A–D proceed on `artifacts/test_sim`.

| Step | Environment | Who |
|---|---|---|
| A. Add the timing monitors and `make verilate` | QICK RTL replay | me |
| B. Validate the monitors on the existing `artifacts/test_sim` | QICK RTL replay | me |
| C. Analysis script | Verification Python | me |
| D. Suite runner | bash + QICK RTL replay | me |
| E. Generate the T1–T10 programs | QICKEmu Python | you create the env (F), then me |
| Later: RISC-Q | RISC-Q | me, after the QICK reference is frozen |

## G. RISC-Q (deferred until the QICK reference is frozen) [CHANGED]

- **Prerequisite finding:** the RISC-Q CPU runs before the testbench releases reset. 55 of 62 `RfCmd`s in `riscq_run.log` come before release (likely cause: `factory.drive(riscqResetHostCd, 0)` without an init value at `PulseTableSoc.scala:287`, under `--x-initial 0`). Any RISC-Q timing log must start from reset release.
- Extend the `RfCmd` logger in `PulseTableSocCpuSim.scala` to:
  - log only after reset release, printing the reset-release time and cycle
  - log `gatePulse.valid` rising and falling edges and `startTime`, to get the native equivalent of E4/E5
- **[CORRECTION]** Invocation (not `./.metals/mill`):
  ```bash
  cd ~/projects/HRL_clinic/risc-q
  RISCQ_ELF=<elf> ~/projects/RISC-Q/mill runMain riscq.soc.sim.PulseTableSocCpuSim \
    | tee ../verification/control_signals/riscq_run.log
  ```
- The readout ELF run currently fails because the sim polls the **gate** `startTime` (`RiscqRfWithPulseTableFiber.scala:196`) while `readout_sched.S` writes the demod `startTime` (`0x24100`).

## Implementation order (when approved)

A → B (validate on `test_sim`) → C → report first numbers → you run F → E → D (T1–T10 sweep) → Step 6 contract → G.
