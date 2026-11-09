# Slot tables: 1 µs head start, and faster than tProc v2

Programs with less than about 2 µs of head start used to fail (`PulseUpdateProgram` needed 6 µs). The CPU could
not rewrite pulse parameters fast enough, so pulses fired late or were cut short, and nothing reported it. This
work fixes that in the RTL and the compiler, and makes RISC-Q issue pulses faster than tProc v2, measured on the
same ZCU216 board.

The compiler half lives on the `compiler` branch line (`qick_lib/qick/asm_v2_riscv.py`, `asm_riscv.py`), pushed
as `compiler-slot-tables`. This branch has the hardware, tools, programs, data and figures.

## Hardware (risc-q RTL)

Pulse tables (`rf/PulseParamBuffer.scala`, `qick/QickGen.scala`):
- 32 pulse slots per generator (`gate_pulse_num`, was 8): `software/configs/zcu216-qick-1q-2loop-s32.json`.
- Per-slot frequency and config tables at `0x4300` and `0x4200`, so each slot keeps its own settings. Writes
  to the old shared addresses still work and set the default for every slot.
- One store fires a pulse. `fireAt` (`0x4400 + 4i`) takes the start time and fires slot i; `fireSlot`
  (`0x4480 + 4i`) fires slot i with an automatically advanced start time.
- Late / overflow / dropped-pulse flags (`rf/WaveWordBridge.scala`). The late check also catches pulses that
  were pushed too late. The host reads the flags at `0x48` and clears them at `0x4C` (`PulseTableSoc.scala`).
- Bridge queue depth 32, lead time 32 cycles.

CPU to pulse table write path (`fabric/PostedStoreShim.scala`, `fabric/RiscqFiber.scala`, `RiscvSoc.scala`,
`link/RfLinkBridge.scala`):
- Direct port: pulse-table writes skip the bus and take one cycle each, with no round trip. A pulse costs
  about 4 CPU cycles.
- A registered store stage in the shim, for timing. A counter makes a read wait for writes that are still
  buffered (read-after-write fix).
- A direct RAM port (`ramDirect`) is built and works in simulation, but is off: it saved only about 4 ns per
  sweep iteration and made timing harder.

Simulation and board tools:
- `qick/sim/QickCpuSim.scala`: slot count from `RISCQ_GATE_PULSE_NUM`, `RISCQ_WORDS` dumps every pulse
  command as CSV, prints the flags.
- `bringup.py --qick-status`: clears the flags before each run, reads them after, saves them in the CSV.
- `software/riscq/map.py`: address constants for all of the above.

## Compiler (on `compiler-slot-tables`)

- Each waveform gets its own slot, written once at program start; a pulse is then one store.
- Slot cache for more than 32 waveforms on one generator (they rotate through a few slots).
- Computed sweeps: a swept value is `start + i·step` with the multiplier, not a memory load.
- `read_wmem` / `write_wmem`: writes go straight through to the slot; reads nothing uses are dropped.
- Clean-up passes after code generation: inline small calls, promote waveform words to registers, hoist loop
  constants, remove redundant loads, copies and dead definitions, schedule time waits. They use a rewritten
  liveness analysis that follows branches and calls.

## Results

Bitstream `riscvsoc-bd-qick-2loop-s32st-spread` (place directive AltSpreadLogic_high): WNS +0.015 ns,
WHS +0.010 ns.

| | Before | RISC-Q now (board) | tProc v2 (board) |
|---|---|---|---|
| Head start needed | about 6 µs | 1 µs works | n/a |
| Back-to-back pulses | n/a | 8.0 ns per pulse | 11.5 ns |
| Sweep loop | 188 ns (sim) | 31.9 ns per iteration | 76.6 ns |
| `virt_z` loop | n/a | about 61 ns per iteration | 73.7 ns |
| Run-to-run timing variation | n/a | about 0.6 ns | about 2 ns |

- PulseUpdate at 1 µs: no flags in 20 runs, spacing 200.5 / 200.0 / 199.5 ns, phases 0 / 90 / 90 / 180°.
  The old code generation is flagged late in all 20 runs.
- Two-generator stress test (45 pulses in 1.5 µs, phase steps and frequency hops): no flags in 20 runs.
- Board and simulation agree within about 1%.
- The `virt_z` train is longer than the 2,048 ns capture window; its figure is the spacing of the 30 pulses
  that fit.

Figures: `../results/s32/` (board) and `../results/sim_*.png` (simulation).

## Still open

- More than 32 waveforms on one generator is slower than tProc (about 20 ns per pulse against 11.5 ns).
- The compiler does not write the readout window length; board programs need `../programs/patch_readout_len.py`
  (`patch_wrap.py` runs it with the right toolchain flags).
- Timing margin is very small.
- Feedback and readout latency not measured.
- Shortest pulse is 6 ns (500 MHz generator clock) against 5 ns on QICK (599 MHz).

## Files here

- Program generators: `board_progs.py` (PulseUpdate old/new, stress), `board_s32.py`, `rate_progs.py`,
  `bench32.py`, `board_rate.py`, `virtz2.py`. tProc v2 counterparts: `qick_rate.py`, `qick_virtz.py` (run on
  the board with stock QICK firmware).
- `programs/`: the six compiled board programs (readout length patched).
- `run_s32.sh`: deploys a build and the programs to the board and captures (`BUILD=<build dir> BOARD_PW=...`;
  the password is only read from the environment).
- Plots and analysis: `plot_board.py`, `plot_sim.py`, `plot_vs.py`, `analyze.py`, `spans.py`, `period.py`,
  `stress_check.py`.
- `data/riscq_board/` (board captures), `data/tproc_board/` (tProc v2 captures), `data/riscq_sim/`
  (QickCpuSim DAC output).
