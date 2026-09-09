# HRL Clinic — RISC-V Signal Processor for QICK

Clinic team repository. **Goal:** replace the custom QICK `tprocv2` timed processor
with a RISC-V–compatible processor (the **RISC-Q** core), while retaining the rest
of QICK's digital logic — signal generators, readouts, and DSP.

## Repository layout

This repo is a monorepo assembled from two upstreams (full history preserved):

| Path        | Source                                                                 | Role |
|-------------|------------------------------------------------------------------------|------|
| repo root   | [QICK](https://github.com/openquantumhardware/qick) `main`             | Base system: signal generators, readouts, DSP, firmware, `qick` Python lib. We modify this. |
| `risc-q/`   | [RISC-Q](https://github.com/Wu-Quantum-Application-System-Group/RISC-Q) `refactor` (git subtree) | RISC-V core to integrate in place of `tprocv2`. |

- QICK's original README is preserved as [`README_QICK.md`](README_QICK.md).
- `risc-q/` was added with `git subtree`, so it is a normal part of the tree —
  clone once and you have everything, no `--recursive` needed.

## Working with the code

```bash
git clone https://github.com/juliacygong/HRL_clinic.git
cd HRL_clinic
```

The QICK `tprocv2` processor lives under `firmware/` (Verilog/HLS) and its Python
driver under `qick_lib/`. RISC-Q's HDL and toolchain live under `risc-q/src` and
`risc-q/software`. Integration work replaces the `tprocv2` compute core with the
RISC-Q core and adapts the surrounding signal-generator / readout / DSP interfaces.

## Pulling upstream updates

```bash
# QICK (root)
git pull https://github.com/openquantumhardware/qick.git main

# RISC-Q (subtree)
git subtree pull --prefix=risc-q \
  https://github.com/Wu-Quantum-Application-System-Group/RISC-Q.git refactor
```
