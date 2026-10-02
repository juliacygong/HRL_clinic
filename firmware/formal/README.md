# Formal verification: axis_signal_gen_v6 and tProc v2

SymbiYosys (formal) testbenches that characterize the **command timing** of the QICK
signal generator `axis_signal_gen_v6`, first on its own and then driven by tProc v2:

- **Acceptance**: when a command is accepted on `s1_axis`, and how many can be queued.
- **Start time**: cycles from acceptance (or from the tProc timestamp) to the first `m_axis_tvalid`.
- **Ordering**: pulses play in the order they were issued, each exactly once, unchanged,
  with no gaps or overlaps.

All checks run on the real RTL from `firmware/ip` and `firmware/hdl`, plus the real Xilinx XPM
FIFO source. No IP or project source was modified. Vivado xsim simulations of the complete design
cross-check the key numbers.

```
formal/
├── axis_signal_gen_v6/      phase 1: generator alone
│   ├── sg_v6.sby            all phase-1 tasks
│   ├── sg_v6_formal.sv      harness + reference timing model
│   ├── models/formal_stubs.sv
│   ├── par_*.sby            extra single-task cover configs
│   ├── run_long.ps1         unattended runner for the long BMC tasks
│   ├── vcd_table.py         print a trace as a per-cycle table
│   ├── waves/               GTKWave view + waveform screenshot
│   └── xpm_char/            xsim cross-checks (testbenches + their output logs)
└── tproc_sg_v6/             phase 2: tProc v2 -> generator
    ├── tp_sg.sby            all phase-2 tasks
    ├── tp_sg_formal.sv      harness
    ├── models/qproc_dispatcher_formal.sv
    └── par_tp_*.sby         one-task copies of tp_sg.sby, for running in parallel
```

Result folders (`par_*`, `fin_*`, `sg_v6_*`) hold each run's `logfile.txt`, the verdict file
(`PASS`/`FAIL`) and the traces in `engine_0/`.

---

## How formal checking works here

A formal tool doesn't run a list of test vectors. The harness makes the inputs **free**, so the
solver may pick any value on any cycle. `assume` limits them to legal behaviour (for example
AXI-stream rules), and `assert` states what must always hold. Two modes are used:

| Mode | Question it answers | Verdict |
|---|---|---|
| `bmc` (bounded model check) | Can **any** legal input sequence break an `assert` within *depth* cycles? | PASS = no failure up to that depth. FAIL = counterexample trace |
| `cover` | Can each `cover` scenario actually happen? | PASS = every cover was reached, with a trace for each |

The `cover` tasks show that the `bmc` checks aren't vacuous, meaning the scenarios really occur.
They also make good waveforms.

---

## Setup and running

Requirements: OSS CAD Suite (with the yosys-slang plugin) in `~/Downloads/oss-cad-suite`, and
Vivado 2026.1. The XPM sources are read from `C:/AMDDesignTools/2026.1/data/ip/xpm/...`. That path
is hard-coded in every `.sby` file, so change it there if your install differs.

```bat
C:\Users\HRLLab\Downloads\oss-cad-suite\environment.bat
cd firmware\formal\axis_signal_gen_v6
sby -f sg_v6.sby accept          :: one task (creates sg_v6_accept\)
sby -f sg_v6.sby                 :: every task, one after another
sby -f par_order_cov.sby         :: a single-task config (creates par_order_cov\)

cd ..\tproc_sg_v6
sby -f par_tp_cov.sby            :: phase-2 tasks are run from their par_ files
```

Use `sby -f` with a `par_*.sby` file to run tasks in parallel: each one gets its own folder and
status database. Regenerate a `par_tp_*.sby` file after editing `tp_sg.sby`:
`sby --dumpcfg tp_sg.sby <task> > par_<task>.sby`.

The long BMC tasks run for hours or days. `axis_signal_gen_v6/run_long.ps1` runs `timing`,
`timing_dds` and `order` unattended. It keeps the PC awake and writes `run_long.log`. It was
launched as the Windows Scheduled Task `sg_v6_formal_long`.

Viewing traces:

```bat
gtkwave par_timing_cov\engine_0\trace3.vcd
gtkwave -a waves\three_pulses.gtkw                 :: preset view of the 3-pulse trace
python vcd_table.py fin_reset_drop\engine_0\trace.vcd cyc s1_tvalid s1_tready m_tvalid exp_valid
```

---

## Phase 1: `axis_signal_gen_v6` alone

### What's in the model

| Block | In the formal model |
|---|---|
| `signal_gen_top`, `signal_gen`, `ctrl_sg_v6`, `latency_reg` | real RTL |
| `fifo_xpm` → `xpm_fifo_sync` (command queue) | **real Xilinx XPM source**, read with yosys-slang |
| `data_writer`, `bram_dp_xpm` (envelope load / memory), `dds_compiler_0` (encrypted IP) | stubs (`models/formal_stubs.sv`) with free outputs. They only affect sample *values*, never timing |
| AXI-lite register block | not included (configuration only) |

### Harness (`sg_v6_formal.sv`)

```
             free inputs                                    checked every cycle
  s1_tdata, s1_tvalid ──►┌─────────────────────┐── m_tvalid ──► == reference model?
  (AXIS rules assumed)   │   signal_gen_top    │── m_tdata ───► == expected sample? (order)
                ◄────────│  (real RTL + XPM)   │
               s1_tready └─────────────────────┘
  cyc counter, aresetn low for cycles 0-3, no commands before cycle 8
```

The reference model, for the k-th accepted command:

```
start[k] = max(accept[k] + 32, end[k-1] + 1)
end[k]   = start[k] + nsamp[k] - 1
m_axis_tvalid must be 1 exactly on [start[k], end[k]] for some k
```

Default limits: up to 3 tracked commands (K=3), `nsamp` 2–6, one-shot mode (`mode=0`).

The `order` task (`-D CHECK_DATA`) also checks every output sample. It uses `outsel=1`, where the
output is the constant DDS value times gain, and power-of-two gains, so each command has a
recognisable sample value (`gain - 1`). That proves each sample comes from the right command.
Using arbitrary gains would force the solver to prove two multipliers equal, and it stalls.

### Tests

| Task | Mode / depth | What it checks | Result | Result folder |
|---|---|---|---|---|
| `timing` | bmc 80 | `m_tvalid` matches the reference model on every cycle (16 lanes, `GEN_DDS=FALSE`) | **PASS** (~7 h) | `sg_v6_timing` |
| `timing_dds` | bmc 80 | same, built with `GEN_DDS=TRUE` (DDS stubbed) | **PASS** (~7 h) | `sg_v6_timing_dds` |
| `order` | bmc 80 | same, plus every sample on 2 lanes equals the playing command's tag | **PASS** (7 h) | `sg_v6_order` |
| `timing_cov` | cover 80 | idle start, back-to-back, gap, 3 queued pulses all reachable | **PASS** | `par_timing_cov` |
| `par_timing_dds_cov.sby` | cover 80 | the same covers with `GEN_DDS=TRUE` | **PASS** | `par_timing_dds_cov` |
| `par_order_cov.sby` | cover 50 | the same covers with the sample checks on (traces show the samples) | **PASS** | `par_order_cov` |
| `accept` | bmc 60 | `s1_tready` never drops before 19 commands are waiting (any `nsamp`) | **PASS** | `par_accept` |
| `accept_cov` | cover 40 | queue fills at exactly 19 commands, and `tready` comes back | **PASS** | `sg_v6_accept_cov` |
| `reset_drop` | bmc 50 | commands allowed right after reset | **FAIL, expected** (finding 1) | `fin_reset_drop` |
| `short_nsamp` | bmc 50 | `nsamp` = 0..3 allowed | **FAIL, expected** (finding 2) | `fin_short_nsamp` |

### Measured timing

| Quantity | Value (aclk cycles) |
|---|---|
| Accept → first `m_axis_tvalid`, idle generator | **32** = 3 (FIFO write→not-empty) + 1 (pop) + 8 (`en_reg` pipe) + 19 (`latency_reg`) + 1 |
| Pulse length | exactly `nsamp` cycles (each cycle carries N_DDS samples) |
| Queued pulses | play back to back with **no gap**, in acceptance order |
| Queue capacity | **19** commands (18 in the XPM FIFO + 1 playing), then `s1_tready` drops |
| `tready` recovery | 1 cycle after the generator takes the next command |

Example, from the `timing_cov` 3-pulse trace (`waves/three_pulses.gtkw`):

```
cycle      8  9 10 11  ...  40 41 42 43 44 45 46
s1 hs      1  0  1  1       0  0  0  0  0  0  0     3 commands accepted, nsamp = 2 each
m_tvalid   0  0  0  0       1  1  1  1  1  1  0
                            └p0─┘ └p1─┘ └p2─┘       p0 starts at 8 + 32 = 40, p1/p2 follow with no gap
```

### Findings

1. **Commands sent right after reset are silently dropped.** For 4 `aclk` cycles after `aresetn`
   rises, `s1_axis_tready` is already high, but the XPM FIFO is still reset-busy and ignores the
   write. The sender sees a handshake, and the command is lost.
2. **`nsamp` = 0 or 1 plays about 65536 cycles.** `ctrl_sg_v6` counts `cnt_nsamp_r` down and
   stops at 2. With `nsamp` < 2 the counter wraps, so `nsamp=0` plays 65536 cycles and `nsamp=1`
   plays 65537. The smallest safe `nsamp` is 2.

### xsim cross-check (`xpm_char/`)

These simulations use the complete real design: real XPM FIFO, real XPM BRAM and the real VHDL
`data_writer`, with nothing stubbed.

| Testbench | Output | Confirms |
|---|---|---|
| `tb_fifo_char.sv` | `fifo_char.log` | first accepted write is 4 cycles after reset; write → not-empty 3 cycles; capacity 18; read → not-full 1 cycle; order kept |
| `tb_sg_char.sv` | `sg_char.log` | accept at cyc 8 → pulse at 40 (32 cycles); back-to-back pulses with no gap; nsamp=1 → 65537 and nsamp=0 → 65536 cycles; reset offsets 0–3 dropped, 4+ played; capacity 19 |

To rerun (from a shell where `C:\AMDDesignTools\2026.1\Vivado\settings64.bat` has been run):

```bat
cd xpm_char
set XPM=C:/AMDDesignTools/2026.1/data/ip/xpm
set FW=../../..
xvlog -sv %XPM%/xpm_cdc/hdl/xpm_cdc.sv %XPM%/xpm_memory/hdl/xpm_memory.sv %XPM%/xpm_fifo/hdl/xpm_fifo.sv ^
      %FW%/hdl/fifo_xpm.sv %FW%/hdl/bram_dp_xpm.sv ^
      %FW%/ip/axis_signal_gen_v6/src/latency_reg.v %FW%/ip/axis_signal_gen_v6/src/ctrl_sg_v6.sv ^
      %FW%/ip/axis_signal_gen_v6/src/signal_gen.v %FW%/ip/axis_signal_gen_v6/src/signal_gen_top.v ^
      tb_fifo_char.sv tb_sg_char.sv
xvhdl %FW%/ip/axis_signal_gen_v6/src/synchronizer_n.vhd %FW%/ip/axis_signal_gen_v6/src/data_writer.vhd
xelab tb_fifo_char -s fifo_char && xsim fifo_char -R
xelab tb_sg_char  -s sg_char   && xsim sg_char -R
```

### Limits

- Bounded: results hold for every input sequence up to the task depth (40–80 cycles), with at most
  3 tracked commands and `nsamp` 2–6 in the timing tasks.
- Periodic mode (`mode=1`) isn't covered.
- The design ignores `m_axis_tready` (no output backpressure), so it's left free.

---

## Phase 2: tProc v2 → `axis_signal_gen_v6`

### What's in the model

The same generator, now fed through the real tProc v2 output path used in `projects/qick_tprocv2_*`:

```
 tProc core (abstracted:          qproc_dispatcher           axis_cdcsync_v1         sg_translator       axis_signal_gen_v6
 free port writes c_we,  ───────► timed wave FIFOs   ──────► shared CDC FIFO  ──┬──► 168b → 160b ───► signal_gen_top ──► DAC
 c_time, c_addr, c_data)          (XPM async FIFOs),         (2 channels)       │    (OUT_TYPE 0)      (phase-1 model)
                                  releases each cmd                             │
                                  when time_abs > T                             └──► channel 0: "another generator",
                                                                                     free or always-ready tready
```

Real RTL: `qproc_dispatcher` (formal copy, see below), `_qproc_ips.sv`, XPM FIFOs,
`fifo_dc_axi_xpm.sv`, `cdcsync.sv`, `sg_translator.v`, and the phase-1 generator sources and stubs.

`models/qproc_dispatcher_formal.sv` is a copy of `ip/qick_processor/src/qproc_dispatcher.sv`
(its sha256 is in the header). The only change: in the three output `always_ff` blocks, the async
reset is tested before the `for` loop instead of inside it. Behaviour is the same, but yosys-slang
can't read the original form. The rest is kept verbatim, including the original's comments, so the
two files stay easy to compare. Copy it again if the original changes.

Abstractions (things not modelled exactly):

- **tProc CPU** is replaced by free port-write inputs: any sequence of wave-port writes the CPU could
  issue. Its run control is copied from `qproc_ctrl.sv`: at start it flushes the dispatcher FIFOs,
  waits for them to leave reset, and pauses while any dispatcher FIFO is full.
- **tProc time** (`time_abs`) is a plain counter from 0 at reset release. The real one uses a DSP macro.
- **One clock** for everything. In hardware the core clock, the timing clock and the generator
  clock are separate.
- Dispatcher FIFO depth is 16 (`FIFO_DEPTH=4`). Hardware uses 512.
- The AXIS register slices between the translator and the generator are omitted.
- Flip-flops without an init value power up at 0 (`setundef -init -zero`), as FPGA registers do.

Default limits: one-shot pulses, `nsamp` 2–6, port-1 timestamps in order, at least 3 cycles apart
and at most 120, written more than `LEAD` cycles before the timestamp (`LEAD`=2 unless stated),
and at most 3 tracked commands. Nothing reaches the generator before about cycle 50, because the
tProc core waits about 31 cycles for its FIFOs to leave reset. So most tasks use `skip 45` to save
solver time.

### Tests

| Task | Mode / depth | What it checks | Result |
|---|---|---|---|
| `tp_cov` | cover 100 | a tProc command reaches the DAC output; 3 commands reach the generator; 2 play back to back | **PASS** (13 h). DAC starts 32 cycles after generator accept, as in phase 1 |
| `tp_disp_cov` | cover 75 | non-vacuity for `tp_disp`: 3 commands handed over, one after back-pressure | covers **reached**. sby says FAIL only because the DAC covers can't be reached at depth 75 |
| `tp_disp` | bmc 75 | dispatcher port-1 output with any consumer: exactly once, in order, `tvalid`/`tdata` held until accepted | **FAIL** (finding 2) |
| `tp_order` | bmc 80 | generator input, other channel always ready: every command exactly once, in order, unchanged | **running**, no failure through step 69 |
| `tp_xchan` | bmc 60 | same, but the other channel may hold `tready` low | **FAIL** (finding 1) |
| `tp_timing` | bmc 80 | each command is accepted by the generator **exactly 12 cycles** after tProc time reaches its timestamp T, never early or late (core writes 17+ cycles ahead) | **running**, no failure through step 76 |
| `tp_lead4` | bmc 70 | `tp_timing` with only 5+ cycles of lead | **FAIL** (finding 4) |
| `tp_lead8` | bmc 70 | `tp_timing` with 9+ cycles of lead | **PASS** (finished 2026-10-01) |
| `tp_lead12` | bmc 75 | `tp_timing` with 13+ cycles of lead | **running**, no failure through step 73 |
| `tp_len` | bmc 70 | any 32-bit tProc length: the generator gets the length asked for | **FAIL** (finding 3) |

Status as of 2026-10-02. The three running tasks started 2026-09-27; each remaining step takes
hours to more than a day. When a run ends, its folder gets a `PASS` or `FAIL` file, and
`run_par_<task>.out` holds its full log.

### Measured timing (end to end)

| Quantity | Value (cycles) |
|---|---|
| tProc time = T → generator accepts the command | **12** (8 of them inside cdcsync) |
| tProc time = T → first DAC sample, idle generator | **44** = 12 + 32 |
| General start time | `start[k] = max(T[k] + 44, end[k-1] + 1)` |
| Lead time the program needs | 5 cycles is too little (arrives 2 cycles late); 9 cycles is always on time (`tp_lead8` PASS) |

### Findings

1. **cdcsync duplicates commands (`tp_xchan`).** cdcsync pops its shared FIFO only when *every*
   channel is ready (`fifo_rd_en = &m_tready`), but shows each channel's `tvalid` regardless. While
   one generator stalls (in hardware, its 19-command queue is full), every other generator on that
   cdcsync accepts the same command again on every cycle.
   Trace: `par_tp_xchan/engine_0/trace.vcd` (same command accepted at cycles 54, 55, 56).
   Caveat: the stalling channel is the abstract consumer, not a second real generator.
2. **Dispatcher changes `tdata` under back-pressure (`tp_disp`).** `m_axis_tdata_r` reloads from the
   FIFO head on every cycle, regardless of `tvalid`/`tready`. If `tready` is low for 2+ cycles right
   after a pop and another command for that port is queued, `tdata` changes while `tvalid` is high.
   The consumer then receives the next command's data at this command's time. That violates AXI-stream.
   Trace: `par_tp_disp/engine_0/trace.vcd` (cycles 45–48).
3. **Pulse length wraps (`tp_len`).** `sg_translator` passes only `nsamp[15:0]`, so lengths ≥ 65536
   wrap with no error. For example, `0x80000001` becomes `nsamp=1`, which then plays 65537 samples
   (phase-1 finding 2).
4. **Minimum lead time (`tp_lead4`).** A command written 5 cycles before its timestamp reaches the
   generator 2 cycles late, because it needs time to cross the dispatcher's async FIFO. This is a
   limit of the design, not a bug.

### How phase 2 maps to phase 1

| Phase 1 (generator alone) | Phase 2 counterpart | Difference |
|---|---|---|
| `timing` | `tp_timing`, `tp_lead4/8/12` | time is measured from the tProc timestamp; the generator part reuses phase 1's proven 32 cycles |
| `timing_cov` | `tp_cov` | the command starts as a tProc write |
| `timing_dds` | not repeated | `GEN_DDS` only affects generator internals |
| `order` | `tp_order`, `tp_xchan`, `tp_disp` | checks the whole command word is delivered exactly once, in order, unchanged |
| `accept` / `accept_cov` | `tp_xchan`, `tp_disp` | back-pressure through the tProc path; queue capacity is unchanged |
| `reset_drop` | covered by `tp_order` | with one shared reset, the core can't start until after the 4-cycle drop window. Separate resets aren't modelled |
| `short_nsamp` | `tp_len` | shows how large tProc lengths become short `nsamp` values |
