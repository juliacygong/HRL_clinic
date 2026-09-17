# Importing the standalone core into Vivado

**Source:** [`src/riscq/riscv/Riscq.scala`](../../src/riscq/riscv/Riscq.scala) ·
**Package:** `riscq.riscv` · **Type:** generator entry point (`RiscqGen`)

For browsing the RTL of just the [RISC-V core](RISCV.md) — schematic, hierarchy, resource
estimate — without pulling in the full multi-qubit [`PulseTableSoc`](../soc/PulseTableSoc.md).
This is the minimal SpinalHDL→Verilog step; everything after is plain Vivado.

## Generate the Verilog

```bash
mill runMain riscq.riscv.RiscqGen
```

This elaborates `Riscq(RiscqParam().plugins())` — the default core config (see
[RiscqParam](RiscqParam.md)) — and emits three files into the current directory:

- `Riscq.v` — the core RTL
- `Riscq.v_toplevel_RegFilePlugin_logic_regs.bin` — register-file init contents
- `Riscq.v_toplevel_GSharePlugin_logic_memCounters.bin` — GShare predictor counter init contents

The two `.bin` files are loaded by `$readmemb` calls inside `Riscq.v` with paths relative to the
`.v` file itself, so all three must stay together in the same directory — Vivado won't need them
added as sources, just present alongside `Riscq.v` when it elaborates.

`build/` is a convenient (git-ignored) place to keep generator output, e.g.:

```bash
mkdir -p build/rtl-riscq && mv Riscq.v Riscq.v_toplevel_*.bin build/rtl-riscq/
```

## Open it in Vivado

1. Create a new RTL project (or an empty non-project run).
2. Add `Riscq.v` as a design source — no need to add the `.bin` files, just leave them
   in the same folder.
3. Set `Riscq` as the top module.
4. **Open Elaborated Design** to browse the RTL schematic and hierarchy without running a full
   synthesis pass, or run **Synthesis** for a resource/timing estimate of the core in isolation.

This generates the core with plain `clk`/`reset` ports and no SoC-level floorplan attributes —
it's meant for inspection, not for reproducing the project's floorplanned timing numbers. For the
Vivado flows that actually synthesize/place/route the full SoC (multi-core, DSP datapath,
`KEEP_HIERARCHY`, per-core pblocks), see
[`vivado-scripts/README.md`](../../vivado-scripts/README.md) and the
`riscq.soc.GenPulseTableSocOoc` / `GenPulseTableSocVivado` generators in
[`PulseTableSoc.scala`](../../src/riscq/soc/PulseTableSoc.scala).

## Related

- [RISCV.md overview](RISCV.md) · [RiscqParam](RiscqParam.md) · [SoC architecture](../soc/ARCH.md)
