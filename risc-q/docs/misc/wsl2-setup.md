# WSL2 setup — getting RISC-Q's simulator running on a Windows laptop

Native Windows has no good story for Verilator, a RISC-V cross-compiler, or Mill's Scala toolchain.
The supported path on a Windows laptop is **WSL2 Ubuntu**: everything below runs inside it. This is
a one-time setup per laptop; see [`docs/TESTING.md`](../TESTING.md) for day-to-day running/editing
of tests once this is done.

## 1. Install WSL2 Ubuntu

If you don't already have it, from a Windows terminal (PowerShell or `cmd`):
```
wsl --install -d Ubuntu
```
This needs a reboot the first time. Once it's installed, `wsl -d Ubuntu -- <command>` runs a command
inside it from any Windows shell without opening a separate WSL terminal window; `wsl -d Ubuntu`
alone drops you into an interactive shell.

**Check your Windows drive has room before doing anything else** (`Get-PSDrive C` in PowerShell, or
just look at `C:\`'s free space in Explorer). Building here is disk-hungry (Ivy/Maven caches,
Verilator object files). If `C:\` is tight, do all the steps below inside the WSL Linux filesystem
(e.g. `~/HRL_clinic`), **not** under `/mnt/c/...` — WSL2's own virtual disk is usually on a different
underlying volume with more room, and builds are noticeably faster there too since `/mnt/c` goes
through a slower filesystem translation layer.

## 2. Install the toolchain (apt)

```bash
wsl -d Ubuntu -u root -- apt-get update
wsl -d Ubuntu -u root -- apt-get install -y \
  openjdk-21-jdk-headless \
  verilator \
  zlib1g-dev \
  build-essential \
  git curl \
  gtkwave
```
- `openjdk-21-jdk-headless` — Java, needed by Mill/Scala.
- `verilator` — the Verilog simulator SpinalHDL's `SimConfig.compile{...}` drives under the hood.
- `zlib1g-dev` — easy to miss: only needed if you enable waveform dumping
  (`SimConfig.withFstWave`). Without it, Verilator's FST tracing fails to compile with
  `fatal error: zlib.h: No such file or directory`.
- `gtkwave` — the waveform viewer (optional if you're not looking at waveforms).
- (`-u root` is used above instead of `sudo` because `sudo` wants an interactive password prompt
  that isn't available when driving `wsl.exe` non-interactively from a script; either works fine
  from your own interactive WSL shell.)

## 3. Install Mill

Mill ships as a tiny launcher script that reads the version pinned in the repo's
`risc-q/.mill-version` (currently `1.1.0`) and downloads/caches that exact version on first use —
you don't separately manage the Mill version yourself.
```bash
wsl -d Ubuntu -u root -- bash -c \
  'curl -L https://raw.githubusercontent.com/com-lihaoyi/mill/main/mill -o /usr/local/bin/mill && chmod +x /usr/local/bin/mill'
```
Verify it (from inside `risc-q/`, first run downloads the pinned release — be patient):
```bash
cd ~/HRL_clinic/risc-q   # wherever you cloned it, see step 4
mill version
```

## 4. Clone the repo

```bash
git clone https://github.com/juliacygong/HRL_clinic.git ~/HRL_clinic
```
This is the monorepo; RISC-Q lives under `risc-q/`, brought in via `git subtree` (so a plain clone
gets everything — no `--recursive` needed for *this* clone. Step 5 is the exception).

## 5. Manually clone the two missing git submodules

`risc-q/ext/SpinalHDL` and `risc-q/ext/rvls` are git submodules, but `git submodule update --init`
won't find them: the `git subtree` merge that brought RISC-Q into this monorepo dropped the root
`.gitmodules` file (only `risc-q/.gitmodules` survived, and git only looks at one at the repo root).
Without them, `risc-q/ext/SpinalHDL` and `risc-q/ext/rvls` are just empty directories and the Mill
build fails immediately.

Get the exact pinned commits (from the monorepo root, not `risc-q/`):
```bash
git ls-tree HEAD risc-q/ext/SpinalHDL risc-q/ext/rvls
```
Then clone each at that commit (URLs/branches are in `risc-q/.gitmodules` if you need to
double-check them):
```bash
cd ~/HRL_clinic/risc-q/ext
rmdir SpinalHDL rvls   # remove the empty placeholder directories first
git clone https://github.com/SpinalHDL/SpinalHDL SpinalHDL
(cd SpinalHDL && git checkout <commit from git ls-tree above>)
git clone https://github.com/JunyiLiu1994/rvls.git rvls
(cd rvls && git checkout <commit from git ls-tree above>)
```
You do **not** need to `make` rvls — that only builds the optional Spike lock-step `.so`, not needed
for the sims in `docs/TESTING.md`. Just having the source checked out is enough for Mill to compile
the JNI/Spinal binding sources it references.

## 6. Verify: run the end-to-end pulse test

```bash
cd ~/HRL_clinic/risc-q
mill runMain riscq.soc.sim.PulseTableSocCpuSim
```
This needs no RISC-V compiler — the firmware it boots (`src/riscq/soc/sim/sw/pulse_sched.elf`) is
already checked into the repo as a prebuilt binary. First run is slow (Ivy dependency resolution +
Scala compile + Verilator build of the generated SoC Verilog, a minute or two); a healthy run ends
with something like:
```
[PulseTableSocCpuSim] PASS: the RISC-V program scheduled a gate pulse that drove DAC 8 ...
381/381, SUCCESS] mill runMain riscq.soc.sim.PulseTableSocCpuSim
```
If you see that, the environment is fully set up. For what to do next — running other tests,
editing them, rebuilding firmware, viewing waveforms — see [`docs/TESTING.md`](../TESTING.md).

## Optional: a RISC-V cross-compiler

Only needed if you want to change the firmware itself (`pulse_sched.S`) rather than just the
testbench/Scala side:
```bash
wsl -d Ubuntu -u root -- apt-get install -y gcc-riscv64-unknown-elf
```
See `docs/TESTING.md`'s "Editing a test" section for the exact rebuild command and options.

## Gotcha: two copies of the repo

If you also edit files from the Windows side (e.g. an editor/IDE running natively on Windows against
`C:\...\HRL_clinic`), remember that's a **different checkout** from the one you cloned into WSL in
step 4 — edits don't appear on the other side automatically. Either edit only inside WSL (simplest —
point a WSL-aware editor, e.g. VS Code's "Remote - WSL" extension, at `~/HRL_clinic`), or copy
changed files across manually before running `mill`. See `docs/TESTING.md` for more on this.
