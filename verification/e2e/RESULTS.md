# Compiler verification results

## MultiPulseProgram (00_intro), 2026-10-11

Inputs: ELF from the compiler team (`build/00_intro/MultiPulseProgram.elf`, built 2026-10-11 with an
unpushed compiler; the pushed `compiler` branch c95e7450 has no conf-register code); program source
= their notebook `programs/modified_by_compilerteam/00_intro.ipynb` (cell 6, `GEN_CH = 1`).

Runs:
- QICK reference: `qick_ref.py 00_intro MultiPulseProgram` → QICK v2 compiler + QICKEmu, 500 MHz
  signal generators (`runs/MultiPulseProgram/qick/`). 9 commands reach generator 1 (each flat-top is 3
  commands: ramp up, flat, ramp down), plus one readout config.
- RISC-Q: ELF on `TimingSocCpuSim` (`runs/MultiPulseProgram/riscq/ev_rfcmd.csv`, 77 register writes).
- Comparison: `compare.py MultiPulseProgram` (fields as the RTL reads them) and `--lsb` (fields as the
  compiler writes them). Output in `runs/MultiPulseProgram/compare*.txt`.

| Field | Result | Cause |
|---|---|---|
| number and order of commands | ✓ 9 = 9 | |
| play start times | ✓ all 9 within one tProc tick | QICK queues flat-top segments at one time, RISC-Q schedules them back to back; same start at the generator |
| phase, conf | ✓ | |
| **gain, nsamp, env as the hardware reads them** | ✗ all 0 | compiler writes amp/env/dur in `data[15:0]`; the QICK channel's `PulseParamBuffer` reads them from `data[31:16]` (`bitOffset = 16`, `PulseParamBuffer.scala:41`, same on `claude-newdesign`). On hardware: gain 0, nsamp 0 → SGv6 plays ~65536 cycles |
| gain, nsamp as the compiler meant them (`--lsb`) | ✓ | |
| **freq** | ✗ `0x0d5acdac` vs `0x0fffffc0` | compiled for 9584.64 MS/s (599.04 MHz generators, Julia's 48e9fd5e design); generators now run at 8000 MS/s (Gabe's e77f1a69). On 500 MHz hardware a 500 MHz pulse would play at 417 MHz |
| **envelope address of ramp-down segments** | ✗ 60 vs 50 | same cause: the 0.2 µs ramp is 120 cycles at 599.04 MHz (envelope file = 1920 samples) vs 100 cycles at 500 MHz (1600 samples) |

Conclusion: the program structure, timing and pulse parameters are translated correctly. Two issues
block it from working on the current hardware:
1. **Field position** (compiler ↔ hardware contract): amp/env/dur must go in `data[31:16]`, or the
   hardware must read the low half. Needs a decision between the compiler team and Julia.
2. **Generator rate**: compile for 8000 MS/s (500 MHz generators) to match `e77f1a69`.
Also: the compiler version used is not pushed; push it so results are reproducible.

Not compared yet: the readout path (readout config written to the demod channel, trigger).

## Rerun with the fixed compiler (`compiler` 00d1501a), 2026-10-16

Compiler commit `00d1501a` ("changed compiler to match 500Hz siggen and demo notebook sweep"):
`seat16()` stores gain/env/length in data[31:16]; `GEN_FREQ_MHZ = 500.0` with fs_mult/fdds_div = 3125/96;
demo `01` sweep reduced from 100001 to 2797 points (1 MHz at the 357.6 Hz gen/readout matched step; QICK
itself rejects the 100001-point version at 500 MHz: "requested sweep step is smaller than the available resolution").

ELFs: as received from the compiler team (`build/`). Reproducibility check: recompiling demo 01 from
`00d1501a` with their `run_notebooks.py` gives identical `.s` and envelope files; the `.elf` differ only in
data-section addresses (+8 bytes, a different runtime/toolchain build), not in program code.

Timing is compared as the gap between consecutive commands (one tProc tick tolerance): each side rounds a
requested time to its own clock (tProc 2.325 ns, RISC-Q 2 ns), so absolute times drift apart over long runs
(reported as "time-grid drift", informational; RISC-Q is the side that hits the requested time exactly).

| Program | Commands compared | Fields | Timing | Drift at last command | Result |
|---|---|---|---|---|---|
| `MultiPulseProgram` (00) | 9 / 9 | ✓ | ✓ | +0.30 ns | **PASS** |
| `SimpleSweepProgram2` (01, 5-point phase+gain sweep) | 15 / 15 | ✓ | ✓ | +0.89 ns | **PASS** |
| `FreqSweepProgram` (01, 5-point freq sweep) | 15 / 15 | ✓ | ✓ | +0.89 ns | **PASS** |
| `FreqSweepProgram_2` (01, 2797 points × 10 reps) | first 627 (209 sweep points, ~355 µs) | ✓ (freq word identical at every step) | ✓ | +65.8 ns | **PASS (prefix)** |
| `FreqSweepProgram_3` (01, 100→8000 MHz, 10001 points × 100 reps) | first 627 | ✓ | ✓ | +65.8 ns | **PASS (prefix)** |

Hardware capture for MultiPulseProgram (`runs/MultiPulseProgram/riscq/ev_queue_push.csv`): amp 32766,
dur 50 (was 0 before the fix); `ev_e5_out.csv` shows the pulses playing.

Not covered: the readout side (readout configuration written to the demod channel, triggers, readout
frequency sweeps) is not compared; long sweeps are compared on their first ~209 points only. The
time-grid drift (0.32 ns per 1.7 µs loop iteration, from tProc's 2.325 ns tick) is a property of the QICK
reference clock, not of the compiler.
