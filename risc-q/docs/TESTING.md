# Running & editing RISC-Q simulations

A practical guide to the SpinalHDL/Verilator testbenches under `src/riscq/**/sim/` — how to run
one, how to edit it, where the firmware it boots lives, and how to look at waveforms. For what each
module *is*, see the per-area docs linked from [docs/README.md](README.md); this page is about the
mechanics of running and changing tests, not the design.

## Two copies of the repo (read this first)

Native Windows has none of the toolchain this project needs (mill, Verilator, a RISC-V compiler),
so simulations are built and run inside **WSL2 Ubuntu**. In practice that means there can be two
checkouts:

- **The Windows checkout** (e.g. `C:\Users\<you>\Documents\clinic\HRL_clinic`) — this is where you
  edit files, and the one `git status`/`git log` refers to.
- **A WSL-side clone** (e.g. `~/HRL_clinic` inside the WSL filesystem) — this is where `mill`
  actually runs and compiles/simulates, because the toolchain lives there and Verilator/mill builds
  are much faster on a native Linux filesystem than over `/mnt/c`.

If you edit a file on the Windows side, **copy it into the WSL clone before running `mill`**, e.g.:
```bash
wsl -d Ubuntu -- cp "/mnt/c/Users/<you>/Documents/clinic/HRL_clinic/risc-q/src/riscq/soc/sim/PulseTableSocCpuSim.scala" \
  ~/HRL_clinic/risc-q/src/riscq/soc/sim/PulseTableSocCpuSim.scala
```
(Longer term, it's simpler to just `git clone`/`git pull` inside WSL and edit there directly with a
WSL-aware editor, so there's only one copy to keep in sync.)

## Prerequisites (already set up once per laptop)

Inside WSL2 Ubuntu:
- `openjdk-21-jdk-headless`, `verilator`, `zlib1g-dev` (needed for waveform tracing), `build-essential`, `git`, `curl` — via `apt-get install`.
- `mill` — a small launcher script installed to `/usr/local/bin/mill` that auto-bootstraps the
  version pinned in `risc-q/.mill-version` (currently `1.1.0`).
- Two git submodules that **don't auto-init**: `risc-q/ext/SpinalHDL` and `risc-q/ext/rvls`. The
  RISC-Q subtree was merged into this monorepo with `git subtree`, which drops the root
  `.gitmodules` file, so `git submodule update --init` finds nothing. Clone them manually at the
  commits pinned in `risc-q/.gitmodules` (get the exact commit hashes with
  `git ls-tree HEAD risc-q/ext/SpinalHDL risc-q/ext/rvls` from the repo root):
  ```bash
  cd risc-q/ext
  git clone https://github.com/SpinalHDL/SpinalHDL SpinalHDL && (cd SpinalHDL && git checkout <pinned commit>)
  git clone https://github.com/JunyiLiu1994/rvls.git rvls && (cd rvls && git checkout <pinned commit>)
  ```
  You do not need to `make` rvls — only its checked-out source is needed to compile.
- `gtkwave` — the waveform viewer (`apt-get install gtkwave`). Not needed to run tests, only to look
  at waveform dumps.

## Running a test

All commands run from `risc-q/` (where `build.mill` lives — **not** the monorepo root):
```bash
cd ~/HRL_clinic/risc-q
mill runMain riscq.<package>.sim.<TestObject>
```
First run of the session is slow (Ivy/Maven dependency resolution + Scala compile); after that,
Mill's daemon keeps things warm and reruns are fast (seconds).

Some concrete examples used so far, cheapest/most isolated first:

| Command | What it tests |
|---|---|
| `mill runMain riscq.riscv.sim.FetchSim` | Just the fetch stage |
| `mill runMain riscq.riscv.sim.RvTestSim` | The RISC-V core against the `rv32ui-p-*` official ISA test ELFs (add a name to run just one) |
| `mill runMain riscq.dsp.pulse.sim.PulseGeneratorSim` | The pulse generator DSP block alone (bit-exact golden model), no CPU involved |
| `mill runMain riscq.soc.sim.RamOnFabricSim` | Core + memory fabric wired up, re-running the ISA tests through the real bus |
| `mill runMain riscq.soc.sim.PulseTableSocSim` | The full SoC, bus-driven by a test-master harness (no CPU program) |
| `mill runMain riscq.soc.sim.PulseTableSocCpuSim` | **The end-to-end one**: the RISC-V core boots real firmware, programs a pulse, and the sim asserts it reaches DAC 8 |

Every one of these is a plain Scala `App` — run it, watch stdout, look for `PASS`/`assert` lines and
a final `SUCCESS` from Mill (`381/381, SUCCESS] mill runMain ...`). A thrown `AssertionError` or
`FAILED` in that last line means the test failed; scroll up for the assertion message.

## Editing a test

### The testbench itself (Scala) — no extra toolchain needed

Each test lives in `src/riscq/<package>/sim/<TestObject>.scala` (see the table above for where the
main ones are). Edit it like any Scala file, then just rerun `mill runMain ...` — no separate build
step. Things you can change here without touching firmware or installing anything new:

- **Routing / mapping** — e.g. in `PulseTableSocCpuSim.scala`, `dacMap` (line ~31) controls which
  physical DAC a core's channel lands on; whichever DAC you watch in the observation loop
  (`dut.io.dac(N)`) must match.
- **Test data** — e.g. the synthetic envelope content generator functions (`reK`/`imK` in the same
  file).
- **Assertions / observation window** — how long the sim watches for the pulse, and the pass
  threshold (`progDur`, `stopTime`, etc.).
- **Waveform dumping** — add `SimConfig.withFstWave` (or `.withWave` for plain VCD) before
  `.compile { ... }`. See [Waveforms](#waveforms-viewing-a-test-run) below. This is now already
  enabled in `PulseTableSocCpuSim.scala`.

### The firmware the CPU boots (needs a RISC-V toolchain)

`PulseTableSocCpuSim` boots real machine code from a checked-in ELF:
- Source: `src/riscq/soc/sim/sw/pulse_sched.S` — hand-written RV32I assembly. Comments at the top
  of the file explain the register-level protocol (posted RF writes, `value << 16` field packing,
  fixed-point units) and show the exact build command.
- Prebuilt binary: `src/riscq/soc/sim/sw/pulse_sched.elf` — already checked into the repo, which is
  why `PulseTableSocCpuSim` runs out of the box with no RISC-V compiler installed.

To change what the firmware actually does (amplitude, frequency, phase, duration, envelope address,
timing), edit `pulse_sched.S` and rebuild the ELF. This needs a RISC-V cross-compiler, which is
**not** part of the base setup above — install one first, e.g.:
```bash
sudo apt-get install gcc-riscv64-unknown-elf
riscv64-unknown-elf-gcc -march=rv32i -mabi=ilp32 -mno-relax -nostdlib -static \
  -Wl,-Ttext=0x80000000 -Wl,-e,_start \
  src/riscq/soc/sim/sw/pulse_sched.S -o src/riscq/soc/sim/sw/pulse_sched.elf
```
Then either overwrite the checked-in `.elf`, or point the sim at a new one without touching any
Scala (`RISCQ_ELF` env var, read at `PulseTableSocCpuSim.scala:54`):
```bash
RISCQ_ELF=/path/to/your_pulse_sched.elf mill runMain riscq.soc.sim.PulseTableSocCpuSim
```
If you change `dur` in the firmware, also bump `progDur` in `PulseTableSocCpuSim.scala` to match,
or the assertion will fail even though the pulse itself is correct.

### The Python driver / co-sim test suite (not yet set up on this laptop)

`software/tests/` is a separate pytest suite (host-pure tests always; `--cosim` tier additionally
needs cocotb + a RISC-V compiler). See `software/README.md` for the tier breakdown and commands
(`PYTHONPATH=. pytest tests/ -q`, `--cosim`, `--cosim --slow`). We haven't installed cocotb yet —
everything above runs through Mill/SpinalSim directly instead, which needs a smaller toolchain.

## Waveforms: viewing a test run

`PulseTableSocCpuSim.scala` has `SimConfig.withFstWave` enabled, so every run writes a waveform to:
```
risc-q/simWorkspace/PulseTableSoc/pulseTableSocCpu/wave.fst
```
(Path pattern in general: `simWorkspace/<toplevel-component>/<sim-test-name>/wave.fst`.)

Open it with GTKWave:
```bash
wsl -d Ubuntu -- gtkwave ~/HRL_clinic/risc-q/simWorkspace/PulseTableSoc/pulseTableSocCpu/wave.fst
```
To open with a specific set of signals pre-loaded, use a `.gtkw` save file and pass **only** that
file (passing the `.fst` and a `.gtkw` together opens two tabs, one empty):
```bash
wsl -d Ubuntu -- gtkwave ~/HRL_clinic/risc-q/pulse.gtkw
```
`risc-q/pulse.gtkw` (in the repo root, alongside this doc's other referenced files) pre-loads the batch-time counter, the CPU-written
`startTime`, the pulse-valid window, and the DAC 8 output. Gotchas learned the hard way:
- **Vector (multi-bit) signal lines need an explicit bit-range suffix**, e.g.
  `TOP.PulseTableSoc.riscqArea_time[31:0]`. Without it, GTKWave silently drops the line — no error,
  it just doesn't appear. 1-bit signals (like a `_valid` wire) don't need a suffix.
- **Signal names in the waveform don't always match the Scala field names you'd guess.** SpinalHDL
  flattens `Area`s (not real module boundaries) into underscore-joined names on the parent, but
  real `Component`s get their own nested scope — so some "signals" are one flat name directly in a
  scope, and others require descending into several nested scopes to find a plain-named register.
  If you can't find a signal by guessing, get the ground truth from the waveform file itself rather
  than guessing again:
  ```bash
  wsl -d Ubuntu -- fst2vcd path/to/wave.fst -o /tmp/header.vcd
  grep -n '<partial signal name>' /tmp/header.vcd   # shows the $scope/$var declarations
  ```
  (`$scope`/`$upscope` lines give the nesting; the `$var` line gives the leaf name.) There can also
  be several similarly-named signals (e.g. `startTime` exists once per pulse-generator channel per
  core — gate/readout/demod × however many cores) — make sure you're looking at the one under the
  right channel.
- **A DAC output signal (e.g. `io_dac_8_payload`) is a wide packed bus**, not a single sample: it's
  `batchSize × dataWidth` bits (256 bits for the current defaults: 16 samples × 16 bits), carrying
  one whole batch per cycle. In GTKWave it shows as a hex/decimal value that snaps from `0` to some
  large number for the duration of the pulse window, not a smoothly-shaped analog curve — that's
  expected, not a bug. For an actual plotted pulse *shape*, use the Python driver's
  `dac_capture_arm`/`dac_capture_get` (see `software/README.md`) instead of GTKWave.
- The interesting activity is usually near the **end** of the trace (most of the simulated time is
  the host loading firmware over AXI before anything happens) — use GTKWave's "Zoom Full" if traces
  look blank, then zoom back in around where `startTime` changes.

## Key file paths (recap)

| Path | What |
|---|---|
| `risc-q/build.mill` | Mill build definition — run `mill` commands from `risc-q/`, not the monorepo root |
| `risc-q/.mill-version` | Pinned Mill version, auto-read by the `mill` launcher |
| `risc-q/src/riscq/**/sim/*.scala` | The SpinalSim testbenches (one `App` object per file) |
| `risc-q/src/riscq/soc/sim/PulseTableSocCpuSim.scala` | The CPU-in-the-loop "pulse out of the RISC-V core" test |
| `risc-q/src/riscq/soc/sim/sw/pulse_sched.S` / `.elf` | The firmware that test boots |
| `risc-q/src/riscq/soc/PulseTableSoc.scala` | The SoC toplevel (channel maps, parameters) |
| `risc-q/pulse.gtkw` | Saved GTKWave signal layout for `PulseTableSocCpuSim`'s waveform |
| `risc-q/simWorkspace/<Top>/<test>/wave.fst` | Where waveform dumps land after a run |
| `risc-q/software/tests/` | The separate Python/pytest/cocotb test suite (not yet set up here) |
| `risc-q/docs/README.md` | Index of per-module design docs |
