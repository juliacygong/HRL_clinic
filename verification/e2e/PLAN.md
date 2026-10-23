# Compiler verification plan: QICK v2 Python API → RISC-Q

Goal: show that a QICK v2 program (`AveragerProgramV2`) compiled by the RISC-V backend
(branch `compiler`, `qick_lib/qick/asm_riscv.py` / `asm_v2_riscv.py`) makes **the same pulses** on
RISC-Q as the same program makes on QICK (tProc v2), on the QICK build of RISC-Q
(`risc-q/software/configs/zcu216-qick-1q.json`: dsp 500 MHz; QICK generators at 500 MHz since
`claude-newdesign` e77f1a69).

Method: differential testing (run both, compare), not formal verification: the compiler is software.
SymbiYosys is used only for the hardware path the compiled code drives (step 6).

## Inputs

| What | Where |
|---|---|
| Compiled programs (`.elf`, `.s`, `.bin`, `*_gen<N>.env`) from the compiler team | `build/00_intro/`, `build/01_gens-and-readouts/` (17 programs, git-ignored) |
| Program source: tProc v2 demo notebooks | `programs/00_intro.ipynb`, `programs/01_gens-and-readouts.ipynb` from `meeg/qick_demos_sho` `tprocv2/`, commit in `programs/SOURCE_COMMIT.txt` |
| Edits the compiler team applied before compiling (import, channel remap) | **missing for the v2 notebooks**; `qick_riscv_demos/build_notebooks.py` on `compiler` only covers the v1 demos (e.g. `GEN_CH = 6 → 1`) |
| QICK reference | QICKEmu at 500 MHz SG clock (`emulator/config/qick_emu_config.json`, harness default) |

Facts checked on the received files: 32-bit RISC-V ELF, load/entry `0x80000000` (same as our
`TimingSocCpuSim`), v2 backend (waveform table in `__qick_wmem`), native PulseParamBuffer map with the
QICK channel's conf register at `0x4104`, 500-cycle initial delay = 1 µs at 500 MHz. Pulses go to
RISC-Q channel 1 (`RF_CH1`), consistent with the team's channel remap.

## Steps

| Step | What | Tool | Output |
|---|---|---|---|
| 0 | Get the v2 notebook edits (channel map, cell order behind `_2`/`_3` variants) | compiler team | edit list or edited notebooks in `programs/` |
| 1 | QICK reference: run each (edited) program through QICK's v2 compiler and QICKEmu (500 MHz SG) | QICKEmu | reference pulse list per program (fields + times from E3/E5 logs) |
| 2 | Run each ELF on the RISC-Q SoC simulation, logging every CPU→RF register write with its cycle | `TimingSocCpuSim` (Verilator) | register-write trace |
| 3 | L1 compare: decode the trace with PulseParamBuffer semantics (table slots, fire by index, startTime auto-advance, freq, conf @0x4104) into pulses; compare with step 1 | Python | per-pulse table: freq/phase/gain/env/nsamp/conf exact, start time in ns (± one tProc tick, 2.3 ns) |
| 4 | Rule check on the trace against the bridge contract (fire ≥ lead+3 ahead, ≤ 9 pending, ≥ 2 cycles apart, in order, 3 ≤ nsamp < 2^16) | Python | warnings where hardware would make pulses late or drop them |
| 5 | L2: replay the trace into QICKEmu (PulseParamBuffer + WaveWordBridge → axis_cdcsync_v1 → SGv6 #1, next to tProc → SGv6 #0) | QICKEmu | SGv6 commands bit-exact, start times compared |
| 6 | Formal: extend `verification/bridge_formal` to the `PulseParamBuffer → io.params` input path the QICK channels use | SymbiYosys | the bridge contract proven for that path |

Deliverable for the compiler team: `verify_compiler.py <program>` running steps 1–4 and printing the
per-pulse comparison and rule warnings, with the assembly lines behind each pulse.

## Order

1. `MultiPulseProgram` (constant pulses, no sweep) through steps 1–4.
2. The rest of `00_intro` that the team compiled (sweeps, PulseUpdate, Periodic, Big/Long, WaitTest).
3. `01_gens-and-readouts` (`FreqSweepProgram`, `SimpleSweepProgram2`).
4. Step 5, then step 6.

Not compiled by the team (no ELF): `DelayProgram`, `ReadProgram`, `FeedbackProgram` from `00_intro`,
and the mux/int4 programs in `01` (hardware RISC-Q's QICK build does not have).

## Open items

- v2 notebook edits from the compiler team (step 0).
- `*_gen<N>.env` envelope files are separate from the ELF; envelope pulses need them loaded into the
  envelope memory in steps 2 and 5.
- `RvProgram` in `build/00_intro/` has no matching class in the notebook; ask what it is.

## Decisions

- 2026-10-16: compiler and QICK reference both target **500 MHz generators** (8000 MS/s; QICKEmu default
  config) until the controller team decides the sample rate (option: back to 599.04 MHz if the ADC must stay
  at 2457.6 MS/s; at 500 MHz the gen/readout matched-frequency step is 358 Hz vs QICK's 22 Hz). The compiler
  team adapts demo parameters (e.g. `01_gens-and-readouts`) for 500 MHz; the QICK reference must use the same
  edited notebook (`programs/modified_by_compilerteam/`). Readout in both models = 2457.6 MS/s; the RISC-Q build
  itself configures the ADC at 2000 MS/s (open hardware question, outside this comparison).
