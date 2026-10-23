#!/usr/bin/env python3
"""QICK reference for a compiled RISC-Q program: build the same program with QICK's own v2 compiler
and export it for QICKEmu (500 MHz signal-generator config).

The program comes verbatim from the compiler team's notebook (programs/modified_by_compilerteam/): its
top-level definitions are replayed in cell order (constants, classes, config and later config edits), so
both sides compile the identical class, config, reps and final_delay. Only the base class differs:
here it is QICK's real AveragerProgramV2 (the team's notebook aliases RvAveragerProgram to that name).

Run with the QICKEmu venv:
    ~/projects/HRL_clinic/.venv/bin/python qick_ref.py 00_intro MultiPulseProgram [--nth N]
Output: runs/<Program>/qick/ (pmem/wmem/dmem/sgmem, axi_replay, prog.txt, program.json)
--nth N picks the N-th instantiation of the class in the notebook (1-based, default 1), matching the
compiler team's _2, _3 ... suffixes.
"""
import argparse
import ast
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path[:0] = [str(REPO / "qick_lib"), str(REPO / "emulator" / "software")]

from qick_emu import QickEmu                                     # noqa: E402
import numpy as np                                               # noqa: E402
import qick.asm_v2 as asm_v2                                     # noqa: E402

CFG_PATH = REPO / "emulator" / "config" / "qick_emu_config.json"   # 500 MHz signal generators


def code_cells(nb):
    path = HERE / "programs" / "modified_by_compilerteam" / f"{nb}.ipynb"
    return ["".join(c["source"]) for c in json.load(open(path))["cells"] if c["cell_type"] == "code"]


def build_program(cells, cls_name, nth, ns, overrides=()):
    """Replay the notebook's top-level definitions in cell order (constants, classes, `config` and its later
    edits such as config['steps'] = ...), skipping imports and anything that needs hardware (acquire, plots,
    soc). Stop at the nth instantiation of cls_name and return (program, call_source, replayed_source)."""
    n, replayed = 0, []
    for src in cells:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue                                   # notebook magics etc.
        for node in tree.body:
            seg = ast.get_source_segment(src, node)
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue                               # namespace below provides the QICK v2 names
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and getattr(node.value.func, "id", None) == cls_name):
                n += 1
                if n == nth:
                    for o in overrides:                # --set: edits the compiler team made but did not send
                        exec(o, ns)
                        replayed.append(o + "    # --set override")
                    call = ast.get_source_segment(src, node.value)
                    return eval(call, ns), call, "\n".join(replayed)
                continue
            if isinstance(node, (ast.ClassDef, ast.Assign, ast.AugAssign)):
                try:
                    exec(seg, ns)                      # constants, classes, config dicts and edits
                    replayed.append(seg)
                except Exception:
                    pass                               # needs hardware or plot objects: not part of the program
    raise SystemExit(f"{cls_name}: instantiation #{nth} not found ({n} found)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("notebook")
    ap.add_argument("program")
    ap.add_argument("--nth", type=int, default=1)
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--set", action="append", default=[], metavar="STMT",
                    help="statement run just before the program is built, e.g. \"config['steps'] = 2797\" "
                         "(to mirror an edit the compiler team made; recorded in program.json)")
    a = ap.parse_args()

    out = a.out or HERE / "runs" / (a.program + ("" if a.nth == 1 else f"_{a.nth}")) / "qick"
    out.mkdir(parents=True, exist_ok=True)

    stray = pathlib.Path.cwd() / "tb_mem"
    existed = stray.exists()
    soc = QickEmu(str(CFG_PATH))
    if not existed and stray.is_dir() and not any(stray.iterdir()):
        stray.rmdir()
    soccfg = soc.soccfg

    # QICK's own v2 classes under the names the notebook uses (it aliases the RISC-V ones to them)
    ns = {k: getattr(asm_v2, k) for k in dir(asm_v2) if not k.startswith("_")}
    ns.update(np=np, soccfg=soccfg)
    prog, call, replayed = build_program(code_cells(a.notebook), a.program, a.nth, ns, a.set)

    # same recording sequence as the HRL fork's QickEmu acquire path (see verification/timing/gen_timing_programs.py)
    soc._reset_soc_state(memdir=out)
    prog.config_all(soc, load_envelopes=True, load_mem=False)
    prog.config_bufs(soc, enable_avg=True, enable_buf=True)
    soc.start_src("internal")
    soc.start_tproc()
    soc.prepare(prog, soc=soc, memdir=out)
    soc.export_vivado_files(memdir=out)

    (out / "prog.txt").write_text(str(prog))
    (out / "program.json").write_text(json.dumps({
        "notebook": a.notebook, "program": a.program, "nth": a.nth, "call": call,
        "replayed_definitions": replayed, "overrides": a.set, "qick_config": str(CFG_PATH),
        "f_time_mhz": soccfg["tprocs"][0]["f_time"], "gen_fs_mhz": [g["fs"] for g in soccfg["gens"]],
    }, indent=2) + "\n")
    print(f"{a.program}#{a.nth} -> {out.relative_to(HERE) if out.is_relative_to(HERE) else out}")
    print(f"  {call}")


if __name__ == "__main__":
    main()
