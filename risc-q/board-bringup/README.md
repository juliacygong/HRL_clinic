# RISC-Q + WaveWordBridge on the ZCU216: build, flash, loopback measurement

This folder is everything needed to take the QICK variant of the RISC-Q SoC (RISC-V core → PulseParamBuffer →
WaveWordBridge → `axis_cdcsync_v1` → `sg_translator` → `axis_signal_gen_v6`) from source to pulses measured on a
ZCU216, and to compare them against QICK tProc v2 running the same demo program on the same cable.

Status (2026-10-23): built, flashed, and `MultiPulseProgram` (tprocv2 `00_intro` demo, compiled to RISC-V) measured
in DAC→ADC loopback. Every pulse inside the capture window matches the QICK baseline in time, width, shape,
relative amplitude and relative phase. See [Results](#7-results) and [Known issues](#8-known-issues--findings).

---

## Contents

1. [Hardware setup](#1-hardware-setup)
2. [One-time host setup](#2-one-time-host-setup)
3. [Building the bitstream](#3-building-the-bitstream)
4. [Flashing / board bring-up](#4-flashing--board-bring-up-bringuppy)
5. [Programs: compiling a tprocv2 demo for RISC-Q](#5-programs-compiling-a-tprocv2-demo-for-risc-q)
6. [Measuring: loopback capture, QICK baseline, plotting](#6-measuring-loopback-capture-qick-baseline-plotting)
7. [Results](#7-results)
8. [Known issues / findings](#8-known-issues--findings)
9. [What changed in the design (and why)](#9-what-changed-in-the-design-and-why)
10. [File map](#10-file-map)
11. [Quick reference: full rerun from scratch](#11-quick-reference-full-rerun-from-scratch)

---

## 1. Hardware setup

| Item | Value |
|---|---|
| Board | ZCU216 (ZynqMP ZCU216 RevA, XCZU49DR), CLK104 clock card, balun breakout |
| Board OS | PYNQ 2.7 (PynqLinux "Austin") on SD; `qick` 0.2.406 installed in the PYNQ venv |
| Board hostname / IP | `pynq` / **192.168.2.99** (PYNQ's static default on eth0) |
| Login | `xilinx` / `xilinx` (also the `sudo` password and the Jupyter password) |
| Jupyter | http://192.168.2.99:9090 (runs as root on the board) |
| Host link | Direct Ethernet, desktop USB-Ethernet adapter `enp0s20f0u10` |
| Loopback cable | **DAC `2_231` (tile 3, block 2) on JHC3 → ADC `0_226` (tile 2, block 0) on JHC7**, in the 10 MHz–1 GHz balun section |

### Host network (done once)

The desktop needed an address on the board's subnet. A NetworkManager profile `zcu216` gives the USB-Ethernet
adapter `192.168.2.1/24`:

```bash
nmcli con add type ethernet ifname enp0s20f0u10 con-name zcu216 \
      ipv4.method manual ipv4.addresses 192.168.2.1/24 ipv6.method link-local
nmcli con up zcu216            # remove later with: nmcli con delete zcu216
ping 192.168.2.99
```

If the adapter enumerates under another name, check `ip -br link` for the interface that is `UP` with no address
after plugging the board in.

### Channel numbering

RISC-Q numbers converters flat 0–15: `DAC i = tile·4 + block` (same for ADCs), see
`vivado-scripts/riscvsoc-bd/inc/rfdc-connect.tcl`. QICK's `print(soccfg)` names the same channels by tile/block and
connector. The cable above is therefore **DAC 14 → ADC 8** in RISC-Q terms, and QICK GEN 14 → RO 0 with QICK's
default ZCU216 firmware (found by the team's channel scan in `~/jupyter_notebooks/Untitled.ipynb` on the board).

---

## 2. One-time host setup

| Tool | Where | Notes |
|---|---|---|
| Vivado 2024.1 | `/tools/Xilinx/Vivado/2024.1` | licenses: `XILINXD_LICENSE_FILE=/tools/Xilinx/licenses/Xilinx_29B3.lic:/tools/Xilinx/licenses/Xilinx_5A91.lic` |
| JDK + mill (SpinalHDL RTL generation) | `~/.local/opt/jdk`, `~/.local/bin/mill` | `export JAVA_HOME=$HOME/.local/opt/jdk PATH=$JAVA_HOME/bin:$HOME/.local/bin:$PATH` |
| RISC-V LLVM toolchain | `~/.local/opt/riscv-llvm/riscv/bin` | riscv-collab `riscv64-elf-ubuntu-24.04-llvm` release 2026.10.21 (clang 22.1.8); gives `riscv64-unknown-elf-{clang,objcopy,nm}` |
| Python venv for the compiler / plots | `~/.local/opt/qickrv-venv` | `numpy scipy matplotlib nbformat nbclient ipykernel serpent Pyro5 tqdm` (the system Python has no numpy) |
| `compiler` branch checkout | `~/HRL_clinic_compiler` (git worktree, detached at `origin/compiler`) | the RISC-V backend for QICK's Python API (`qick_lib/qick/asm_riscv.py`) |

Toolchain install (no root needed):

```bash
D=~/.local/opt/riscv-llvm-dl; mkdir -p $D && cd $D
curl -sSLO https://github.com/riscv-collab/riscv-gnu-toolchain/releases/download/2026.10.21/riscv64-elf-ubuntu-24.04-llvm.tar.xz
mkdir -p ~/.local/opt/riscv-llvm && tar -xJf riscv64-elf-ubuntu-24.04-llvm.tar.xz -C ~/.local/opt/riscv-llvm
rm -rf $D
python3 -m venv ~/.local/opt/qickrv-venv
~/.local/opt/qickrv-venv/bin/pip install numpy scipy matplotlib nbformat nbclient ipykernel serpent Pyro5 tqdm
git -C ~/HRL_clinic worktree add --detach ../HRL_clinic_compiler origin/compiler
```

Nothing needs installing on the board: everything there runs in the PYNQ image's own venv (`pynq`, `xrfclk`,
`xrfdc`, numpy). The RISC-Q `riscq` Python package is **not** used on the board.

---

## 3. Building the bitstream

The flow is `vivado-scripts/riscvsoc-bd/build-riscvsoc-bd.sh` (RTL generation with mill → block design → synth →
place & route → bitstream → XSA), run in batch mode. Two builds were made:

| Build | Config | Output dir | Purpose |
|---|---|---|---|
| `riscvsoc-bd-qick` | `software/configs/zcu216-qick-1q.json` (gate gen → DAC 0, readout ADC 0) | `build/riscvsoc-bd-qick/` | smoke test: clocks, flash, core boots and runs |
| **`riscvsoc-bd-qick-lb`** | **`software/configs/zcu216-qick-1q-loopback.json`** (gate gen → **DAC 14**, readout → **ADC 8**) | `build/riscvsoc-bd-qick-lb/` | **the measurement build**: matches the bench cable, has the envelope FIFOs and the readout-window capture |

Command (loopback build):

```bash
export JAVA_HOME=$HOME/.local/opt/jdk PATH=$JAVA_HOME/bin:$HOME/.local/bin:$PATH
export XILINXD_LICENSE_FILE=/tools/Xilinx/licenses/Xilinx_29B3.lic:/tools/Xilinx/licenses/Xilinx_5A91.lic
source /tools/Xilinx/Vivado/2024.1/settings64.sh
cd ~/HRL_clinic/risc-q/vivado-scripts/riscvsoc-bd
RISCQ_QICK=1 RISCQ_RUN_BITSTREAM=1 RISCQ_PROJ_NAME=riscvsoc-bd-qick-lb \
  RISCQ_CONFIG=$HOME/HRL_clinic/risc-q/software/configs/zcu216-qick-1q-loopback.json \
  ./build-riscvsoc-bd.sh > ../../build/logs/bitstream-lb.log 2>&1
```

Outputs: `build/<proj>/PulseTableSoc.bit`, `PulseTableSoc.xsa`, `timing_impl.rpt`, `util_impl.rpt`, `vivado.log`;
the block-design handoff is `build/<proj>/bd/riscq_bd/hw_handoff/riscq_bd.hwh` (needed on the board, see §4).
The bitstream also exists as `build/<proj>/<proj_underscored>.runs/impl_1/riscq_bd_wrapper.bit` as soon as
`write_bitstream` finishes, a couple of minutes before the flow copies it.

### Timing and duration (2026-10-23)

| Build | Synth | Impl → bitstream | Final WNS / TNS | Final WHS / THS | Failing endpoints |
|---|---|---|---|---|---|
| `riscvsoc-bd-qick` | 19 min | 39 min (router needed a 2nd pass) | +0.020 / 0 ns | +0.007 / 0 ns | 0 |
| `riscvsoc-bd-qick-lb` | 20 min | 33 min | +0.012 / 0 ns | +0.010 / 0 ns | 0 |

Loopback build utilization: 37.2k LUTs (8.8 %), 49.4k registers (5.8 %), 207 BRAM tiles (19.2 %), 207 DSPs (4.9 %).
Post-place WNS is negative (≈ −0.2 to −0.34 ns) in both runs; `phys_opt_design -directive AggressiveExplore` and
the router close it. Margins are thin (10–20 ps) at the 500 MHz dsp clock.

### Watching a build in the GUI

Opening the live project normally while a batch build runs broke a build before (`build/logs/iter1-guiconflict.log`).
Open it read-only instead:

```bash
echo 'open_project -read_only /home/jgong/HRL_clinic/risc-q/build/riscvsoc-bd-qick-lb/riscvsoc_bd_qick_lb.xpr' > /tmp/ro.tcl
vivado -mode gui -source /tmp/ro.tcl
```

Do not press Run Synthesis/Implementation/Generate Bitstream in that GUI while a batch build is running.

### Branch note

The plain `waveword-bridge` tip of 2026-10-23 morning did not build on Vivado 2024.1. The working flow needs the
three commits from `claude-newdesign` / `claude-newdesign-timing` that are now merged into `waveword-bridge`:
`b0a6348d` (QICK riscvsoc-bd flow on 2024.1), `e77f1a69` (QICK gens at the 500 MHz dsp rate, `nsamp = dur`) and
`5d3464d1` (max-delay clock-crossing constraints). The controller RTL (core, `WaveWordBridge.scala`,
`PulseParamBuffer.scala`) is identical to the original `waveword-bridge`; the differences are the gen clock
(599.04 → 500 MHz, `RISCQ_GEN_FREQ=599040000` restores it) and the `dur → nsamp` path. Amy's QICK IP changes
(`EMULATOR` parameter, renamed DDS `.xci`) are synthesis-neutral at the default `EMULATOR = 0`.

---

## 4. Flashing / board bring-up (`bringup.py`)

`bringup.py` runs **on the board**, as root, in the PYNQ venv. It replaces what `riscq.board.PynqDriver` would do,
without installing `riscq` (which also assumes PYNQ ≥ 3.0, see below). Steps:

1. **Clocks.** Writes `LMK04828_500.0.txt` to the CLK104's LMK04828 through `xrfclk`'s own SPI helpers
   (`xrfclk.xrfclk._find_devices` / `_write_LMK_regs`). The LMX2594s are not used.
2. **Flash.** `pynq.Overlay("PulseTableSoc.bit", ignore_version=True)` with `PulseTableSoc.hwh` beside it.
3. **RF data converter.** Nyquist zones (DAC and ADC, default 1 for 500 MHz); prints each tile's PLL lock
   (`2` = locked). MTS is attempted only if the PYNQ has the API (it does not on 2.7).
4. **Envelopes** (`--env gate=FILE` / `ro=FILE`): QICK's `AxisSignalGenV6.load()` sequence (`START_ADDR=0`,
   `WE=1`, stream the I|Q words, `WE=0`), through the gen's AXI4-Stream FIFO.
5. **Core.** Holds reset (`host_ctrl+0x0 = 1`), parks the core (`j .`), loads an ELF (minimal ELF32 loader) or
   flat binary at `0x80000000`, verifies a readback, releases reset, polls `__rq_status` for DONE
   (`0xD04E....`).
6. **Capture** (`--capture CSV`): after each run waits `--settle` s (DONE comes before the scheduled pulses
   finish playing), reads the readout trace (`robs`, 4096 samples) and writes all runs + their mean to CSV.

### The 500 MHz clock file

The board image ships only QICK's `LMK04828_245.76.txt` (VCO 2457.6 MHz, refclks 245.76 MHz, PL_CLK 122.88 MHz).
This design needs 500 MHz on the RFDC tile-2 refclks (DAC and ADC tile 2 PLLs, which distribute to the other tiles)
and on the PL `dspClk` pins (E10/E9). `gen_lmk500.py` loads the board's own 245.76 file into QICK's
`ipq_pynq_utils` LMK04828 model (CLK104: 10 MHz ref, 160 MHz VCXO) and re-plans it; the committed file keeps the
original register order and changes only 8 values:

| Register | 245.76 | 500.0 | Meaning |
|---|---|---|---|
| R280 / R288 / R304 | `0x01186A` / `0x012074` / `0x01306A` | `0x011866` / `0x012066` / `0x013066` | DAC_REFCLK / PL_CLK / ADC_REFCLK dividers → 6 |
| R312 / R315 | `0x013800` / `0x013B40` | `0x013820` / `0x013B80` | SYSREF divider 320 → 384 (7.8125 MHz) |
| R353 / R354 / R360 | `0x016119` / `0x016244` / `0x0168C0` | `0x016104` / `0x016264` / `0x016819` | PLL2 R = 4, P = 3, N = 25 → VCO 3000 MHz |

Decoded result: VCO 3000 MHz; DAC_REFCLK, ADC_REFCLK, PL_CLK = 500 MHz; SYSREF 7.8125 MHz on PL and AMS. On the
board all 4 DAC and 4 ADC tiles report PLL lock with it. `hostClk` (100 MHz) comes from the board's fixed
`clk_100` oscillator (G12/G11) and does not depend on the clock chips.

### PYNQ 2.7 quirks handled

| Problem | Fix in `bringup.py` / `deploy.sh` |
|---|---|
| `RuntimeError: No Devices Found` under `ssh … sudo` | run in a root shell that sources `/etc/profile.d/pynq_venv.sh`, `xrt_setup.sh`, `boardname.sh` (`XILINX_XRT=/usr`, venv, `BOARD`) |
| RFDC comes up as `DefaultIP` (driver registered only for IP 2.3/2.4; this build has 2.6) | `pynq.Overlay(..., ignore_version=True)` |
| No `mts_dac_config` / `mts_dac()` (multi-tile sync API is PYNQ ≥ 3.0) | MTS skipped with a message; single DAC→ADC paths do not need it |
| `.xsa` not loadable by `pynq.Overlay` on 2.7 | ship `.bit` + `.hwh` with the same basename |
| Board clock reads Oct 9 (no RTC / NTP) | harmless |

### Commands

From the desktop, `deploy.sh` stages `PulseTableSoc.{bit,hwh}`, the scripts, the LMK file and `programs/` and copies
them to the board:

```bash
cd ~/HRL_clinic/risc-q/board-bringup
B=~/HRL_clinic/risc-q/build/riscvsoc-bd-qick-lb
BUILD=$B REMOTE_DIR=riscq-bringup-lb ./deploy.sh             # BIT=… overrides the bitstream path
```

On the board (`ssh xilinx@192.168.2.99`, password `xilinx`):

```bash
cd ~/riscq-bringup-lb
sudo bash -c "source /etc/profile.d/pynq_venv.sh; source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/boardname.sh; \
  python3 bringup.py --dac-nyquist 1"                        # clocks + flash + RFDC, core parked
```

Useful flags: `--skip-clocks --no-download` (attach to the loaded design, e.g. to rerun a program), `--no-mts`,
`--elf`/`--bin`, `--wait`, `--env gate=…`, `--repeat N` (0 = until Ctrl-C), `--period`, `--capture CSV`,
`--settle`. Rerun the full bring-up (without `--skip-clocks/--no-download`) after anything else (e.g. a QICK
notebook) has loaded its own firmware or clocks.

Expected output on a good flash:

```
[bringup] LMK04828 programmed from …/LMK04828_500.0.txt (128 registers) -> 500 MHz refclks + PL_CLK
[bringup] downloading overlay …/PulseTableSoc.bit
[bringup] AXI map: {'envfifo_qickgen0_gate': '0x90000000', 'envfifo_qickgen0_ro': '0x90010000', 'top/S_AXIS': '0x80000000',
                    'top/QICKGEN0_GATE_S_AXI': '0x90020000', 'top/QICKGEN0_RO_S_AXI': '0x90020800', 'rf_data_converter': '0x90040000'}
[bringup] MTS skipped: …
[bringup]   DAC tile 0..3 / ADC tile 0..3: … pll lock 2
```

### Address map (loopback build, from the `.hwh`)

| Block | PS address | Notes |
|---|---|---|
| SoC window (`top/S_AXIS`) | `0x8000_0000` (256 MB) | core 0 RAM at +`0x00000` (16 KB, CPU `0x80000000`); readout trace `robs` at +`0x40000`; `host_ctrl` at +`0x50000` (+0 reset, +0x40/0x44 time offset) |
| Envelope FIFO, gate gen | `0x9000_0000` | `axi_fifo_mm_s` TX: ISR 0x00, TDFR 0x08, TDFV 0x0C, TDFD 0x10, TLR 0x14 |
| Envelope FIFO, readout gen | `0x9001_0000` | |
| QICK gate gen registers | `0x9002_0000` | `START_ADDR` 0x00, `WE` 0x04 |
| QICK readout gen registers | `0x9002_0800` | |
| RF data converter | `0x9004_0000` | |

The smoke-test build (`riscvsoc-bd-qick`) has no FIFOs and different addresses; `bringup.py` reads them from the
`.hwh`, so nothing is hard-coded except the SoC window layout (from `riscq.map.SocMap` for the 1-qubit config).
All PL accesses are single 32-bit beats: wide reads of the SoC window DECERR (see `PynqDriver.read_block`).

---

## 5. Programs: compiling a tprocv2 demo for RISC-Q

The compiler team's backend (`compiler` branch, commit ≥ `00d1501a`) runs QICK's own v2 Python API and emits RISC-V
assembly, an ELF, a flat `.bin`, and one `<prog>_gen<N>.env` per generator with envelopes (int16 I,Q pairs from
table address 0, exactly the words the gen's table loader takes). `programs/compile_mpp.py` runs the notebook's
setup cells and its `MultiPulseProgram` cell headlessly, with overrides:

```bash
C=~/HRL_clinic_compiler; P=~/HRL_clinic/risc-q/board-bringup/programs
export PATH=$HOME/.local/opt/riscv-llvm/riscv/bin:$PATH PYTHONPATH=$C/qick_lib:$C/risc-q/software
cd $C/qick_riscv_demos/tprocv2
~/.local/opt/qickrv-venv/bin/python $P/compile_mpp.py 00_intro.ipynb $P/MultiPulseProgram_loopback \
    --set GEN_CH=0 --set TRIG_TIME=0.40 --gain 0.1
~/.local/opt/qickrv-venv/bin/python $P/patch_readout_len.py \
    $P/MultiPulseProgram_loopback/MultiPulseProgram.s 1.9 $P/MultiPulseProgram_loopback_ro
cp $P/MultiPulseProgram_loopback/MultiPulseProgram_gen0.env $P/MultiPulseProgram_loopback_ro/
```

| Directory | Settings | Use |
|---|---|---|
| `MultiPulseProgram_gen1/` | notebook as-is (`GEN_CH = 1`, gain 1.0, trigger 0.3 µs) | reference; drives the readout gen → DAC 1 |
| `MultiPulseProgram_gen0/` | `GEN_CH = 0` | drives the gate gen; differs from gen1 only in `RF_CH1` → `RF_CH0` |
| `MultiPulseProgram_loopback/` | `GEN_CH = 0`, `TRIG_TIME = 0.40`, gain 0.1 | matches the QICK loopback baseline's settings |
| **`MultiPulseProgram_loopback_ro/`** | the above + readout window 1.9 µs (`patch_readout_len.py`) | **the program that was measured** |

Why `GEN_CH = 0`: QICK channel `GEN_CH` compiles to RISC-Q RF channel `RF_CH<GEN_CH>`; RF_CH0 is the gate channel,
whose gen drives `dac_map[0][0]` (DAC 14 on the loopback build), RF_CH1 the readout-drive channel
(`dac_map[0][1]`). Why gain 0.1 and trigger 0.4 µs: the board's QICK loopback notebook uses those (gain 1.0 straight
into the ADC is unnecessary, and a different trigger time shifts the whole trace).

The compiler targets `configs/zcu216-14q.json` by default; its per-core CPU memory map (16 KB RAM, RF windows at
`0x10000/0x20000/0x30000`, ctrl at `0x2000/0x4000/0xBFF8`) is identical to the 1-qubit QICK build's, so the ELF runs
unchanged.

---

## 6. Measuring: loopback capture, QICK baseline, plotting

### RISC-Q capture (on the board)

```bash
cd ~/riscq-bringup-lb
sudo bash -c "source /etc/profile.d/pynq_venv.sh; source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/boardname.sh; \
  python3 bringup.py --skip-clocks --no-download --no-mts --dac-nyquist 1 \
    --env gate=programs/MultiPulseProgram_loopback_ro/MultiPulseProgram_gen0.env \
    --elf programs/MultiPulseProgram_loopback_ro/MultiPulseProgram.elf \
    --repeat 10 --capture results/riscq_env.csv"
```

Capture CSV: `# key: value` metadata lines, then `sample,t_ns,adc_mean,run0..runN-1` — raw ADC samples at 2 GS/s
over the readout window (950 dsp cycles = 3800 samples; the last 296 of the 4096-entry buffer are outside the window
and read 0). Use the per-run columns, not `adc_mean` (see §8, phase coherence).

### QICK baseline (on the board)

`qick_baseline.py` executes the team's loopback notebook (`~/jupyter_notebooks/Untitled.ipynb`: setup cells +
the `MultiPulseProgram` cell — `QickSoc()` default firmware, GEN 14 → RO 0, gain 0.1, `ro_len` 1.9 µs, 10 rounds)
headlessly and saves `qick_baseline.csv` (`t_us,I,Q`, 584 decimated samples), `.png` and `_meta.json`:

```bash
cd ~/riscq-bringup-lb/results
sudo bash -c "source /etc/profile.d/pynq_venv.sh; source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/boardname.sh; \
  python3 ../qick_baseline.py --out qick_baseline"
```

This loads QICK's firmware and 245.76 MHz clocks; run the full `bringup.py` again before using RISC-Q. In a notebook,
the same CSV comes from

```python
np.savetxt("qick_baseline.csv", np.column_stack([t, iq_list[0][:, 0], iq_list[0][:, 1]]),
           delimiter=",", header="t_us,I,Q", comments="")
```

### Plotting (on the desktop)

```bash
scp 'xilinx@192.168.2.99:riscq-bringup-lb/results/*.csv' results/
cd results
~/.local/opt/qickrv-venv/bin/python ../plot_compare.py riscq_env.csv --qick qick_baseline.csv \
    --freq 500 --normalize --align --out compare_env_aligned
```

`plot_compare.py` downconverts each RISC-Q run the way QICK's readout does (mix with e^(−j2π·500 MHz·t),
129-tap Hann-windowed-sinc low-pass to the output band), rotates every run onto run 0's phase over the strongest
pulse, averages, and resamples onto QICK's time grid. `--align` shifts RISC-Q so the rising edges of the strongest
pulse (the full-gain const pulse) coincide and prints the shift; `--normalize` scales each trace to its peak;
`--raw-mean` uses the CSV's plain mean instead (shows the phase-cancellation problem). Outputs `<out>.png` (raw run 0,
I/Q, |IQ|) and `<out>_iq.csv` (`t_us,I,Q` of the processed RISC-Q trace).

---

## 7. Results

`results/compare_env_aligned.png` — full sequence (envelopes loaded), RISC-Q shifted +0.306 µs:

| Pulse (aligned time) | QICK \|IQ\| (norm.) | RISC-Q \|IQ\| (norm.) | |
|---|---|---|---|
| flat-top #1, 0.07–0.30 µs | 0.48 | — | before RISC-Q's window (latency, §8) |
| gaussian, ≈0.54 µs | 0.48 | 0.47 | same position, width, shape |
| const 0.2 µs, 0.84–1.04 µs | 0.96 | 0.93 | |
| flat-top #2 (90°), 1.29–1.50 µs | 0.48 (ramps + flat) | 0.46 | ramps and flat line up |
| gaussian, ≈1.74 µs | 0.48 | 0.47 | |
| phase step const → flat-top #2 | +90° | +90° | absolute phases differ (different DDS / LO references) |

`results/compare_noenv_aligned.png` — same program without loading envelopes: only the const pulse and the flat
section of flat-top #2 play (gaussians and ramps read an empty table), at the same times and the same 2:1 amplitude
ratio. Peak |IQ| ≈ 1740 ADC counts in every capture, with or without envelopes.

Raw data: `riscq_noenv.csv`, `riscq_env.csv`, `riscq_A_noenv_after.csv`, `riscq_B_env_again.csv` (10 runs each),
`qick_baseline.{csv,png,_meta.json}`. Smoke test on the first build: core loaded MultiPulseProgram, ran, reported
DONE `0xD04E0000` in < 1 ms.

---

## 8. Known issues / findings

1. **Compiler drops the readout length.** `trigger(ros=…)` becomes a demod-channel (RF_CH2) fire — `startTime`
   (`+0x4100`) then fire slot 0 — but `declare_readout(length=…)` is never written to slot 0's `dur`, so the demod
   carrier's window `[startTime, startTime + dur)` is empty and the trace stays all-zero (the first capture).
   Workaround: `programs/patch_readout_len.py` inserts `sw (dur<<16), 28(RF_CH2)` after the program's RF_CH2 setup
   and reassembles with the compiler's toolchain. **Proper fix: in the compiler backend.**
2. **No run-to-run phase coherence.** Each run restarts the core while the gen's DDS free-runs in its own clock
   domain, so the carrier phase of a run is arbitrary (measured: from a steady ≈12°/run drift to fully random).
   Single-run amplitude is constant (≈1600–1700 counts peak), but a plain average of raw samples cancels (10-run
   means of 155–1600 counts). `plot_compare.py` phase-aligns runs before averaging. QICK averages coherently because
   tProc and gens share one timebase; real averaged experiments on RISC-Q need a phase reset or shared time reference.
3. **Latency differs from QICK.** Relative to its trigger, RISC-Q's DAC→ADC path is ≈0.306 µs shorter than QICK's,
   so pulses scheduled before ≈0.3 µs (flat-top #1) fall before the readout window. Compile with an earlier
   `TRIG_TIME` (and/or longer `ro_len`, ≤ 2.048 µs = robs depth) to capture them.
4. **MTS not performed** (PYNQ 2.7 has no multi-tile-sync API). Fine for one DAC → one ADC; cross-tile latency
   alignment would need the `ipq_pynq_utils`-style raw cffi path (`XRFdc_MultiConverter_Sync`) or PYNQ 3.
5. **`robs` capture is raw and short.** 1024 dsp cycles × 4 lanes = 4096 samples at 2 GS/s (2.048 µs), real ADC
   samples only (no on-chip DDC), one shared buffer, overwritten by every readout window.
6. **Thin timing margins** (WNS +10–20 ps at 500 MHz). Builds close, but placement-sensitive.
7. **Envelope FIFO** is 4096 words deep; `load_envelope` streams in 2048-word packets and waits for the FIFO to drain
   before clearing `WE`. The gen's s0_axis has no `tlast`; the gen ignores packet boundaries.

---

## 9. What changed in the design (and why)

| File | Change | Why |
|---|---|---|
| `vivado-scripts/riscvsoc-bd/inc/bd-build.tcl` | one `axi_fifo_mm_s` (TX only, 4096 deep, AXI-Lite data port, hostClk, `ps_rst` reset) per `QICKGEN*_S0_AXIS`, as extra SmartConnect manager ports | the gens' envelope streams were unconnected, so only DDS-only pulses could play |
| `src/riscq/soc/RiscqRfWithPulseTableFiber.scala` | new `readoutWindow`: native = readout drive pulse valid (unchanged); qickGen = demod carrier valid | in the QICK variant `readoutPulse.valid` is a 1-cycle release strobe, so `robs` captured ~4 samples; the demod window is QICK's trigger + readout length |
| `src/riscq/soc/PulseTableSoc.scala` | `robs` write window uses `readoutWindow` | as above (test-infrastructure only: core, bridge and pulse path untouched) |
| `software/configs/zcu216-qick-1q-loopback.json` | `dac_map [[14, 1]]`, `adc_map [8]` | gate gen and readout ADC on the bench loopback cable |

---

## 10. File map

```
risc-q/board-bringup/
├── README.md                this document
├── bringup.py               on-board bring-up: clocks, flash, RFDC, envelopes, core load/run, capture
├── deploy.sh                desktop → board copy (BUILD=, BIT=, REMOTE_DIR=, BOARD_HOST=); `./deploy.sh run …`
├── LMK04828_500.0.txt       500 MHz CLK104 LMK04828 register file (TICS format, board write order)
├── gen_lmk500.py            how that file was derived (runs on the board against the stock 245.76 file)
├── qick_baseline.py         headless run of the board's QICK loopback notebook → qick_baseline.csv
├── plot_compare.py          RISC-Q capture vs QICK baseline: DDC, coherent average, alignment, plot + CSV
├── programs/
│   ├── compile_mpp.py           compile MultiPulseProgram from the compiler team's notebook (overrides)
│   ├── patch_readout_len.py     add the missing readout-window length and reassemble
│   └── MultiPulseProgram_*/     compiled programs (.s, .elf, _gen<N>.env; .bin is git-ignored)
└── results/                 2026-10-23 captures, QICK baseline and comparison plots
```

Board side: `~xilinx/riscq-bringup/` (smoke-test build) and `~xilinx/riscq-bringup-lb/` (loopback build, with
`results/`). Build products: `risc-q/build/riscvsoc-bd-qick{,-lb}/` (git-ignored).

---

## 11. Quick reference: full rerun from scratch

```bash
# 0. host env
export JAVA_HOME=$HOME/.local/opt/jdk PATH=$JAVA_HOME/bin:$HOME/.local/bin:$PATH
export XILINXD_LICENSE_FILE=/tools/Xilinx/licenses/Xilinx_29B3.lic:/tools/Xilinx/licenses/Xilinx_5A91.lic
source /tools/Xilinx/Vivado/2024.1/settings64.sh

# 1. build (~55 min)
cd ~/HRL_clinic/risc-q/vivado-scripts/riscvsoc-bd
RISCQ_QICK=1 RISCQ_RUN_BITSTREAM=1 RISCQ_PROJ_NAME=riscvsoc-bd-qick-lb \
  RISCQ_CONFIG=$HOME/HRL_clinic/risc-q/software/configs/zcu216-qick-1q-loopback.json ./build-riscvsoc-bd.sh

# 2. deploy
cd ~/HRL_clinic/risc-q/board-bringup
BUILD=~/HRL_clinic/risc-q/build/riscvsoc-bd-qick-lb REMOTE_DIR=riscq-bringup-lb ./deploy.sh

# 3. on the board: flash, then capture with envelopes
ssh xilinx@192.168.2.99
cd ~/riscq-bringup-lb
E="source /etc/profile.d/pynq_venv.sh; source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/boardname.sh"
sudo bash -c "$E; python3 bringup.py --dac-nyquist 1"
sudo bash -c "$E; python3 bringup.py --skip-clocks --no-download --no-mts --dac-nyquist 1 \
  --env gate=programs/MultiPulseProgram_loopback_ro/MultiPulseProgram_gen0.env \
  --elf programs/MultiPulseProgram_loopback_ro/MultiPulseProgram.elf --repeat 10 --capture results/riscq_env.csv"
# optional: QICK baseline (reflashes QICK; rerun the full bringup.py afterwards)
cd results && sudo bash -c "$E; python3 ../qick_baseline.py --out qick_baseline"; exit

# 4. desktop: fetch + plot
cd ~/HRL_clinic/risc-q/board-bringup/results
scp 'xilinx@192.168.2.99:riscq-bringup-lb/results/*.csv' .
~/.local/opt/qickrv-venv/bin/python ../plot_compare.py riscq_env.csv --qick qick_baseline.csv --normalize --align --out compare_env_aligned
```
