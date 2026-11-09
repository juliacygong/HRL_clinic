import re
from numbers import Integral

import numpy as np

from .asm_v2 import (Macro, Label, WriteLabel, End, WriteReg, IncReg, ReadWmem, WriteWmem, ReadDmem, WriteDmem,
                     ReadInput, Jump, Call, CondJump, OpenLoop, CloseLoop, Delay, Wait, Resync,
                     Pulse, ConfigReadout, Trigger, QickRawParam, AsmInst)
from .riscq_config import READOUT_CH

# symbols come from the .equ block built from riscq_map.h
CTRL_BASE = "RQ_CTRL_TIME_CMP"
WAIT_ADDR = 0x0
CTRL_TIME = "RQ_CTRL_TIME"
CTRL_RES  = "RQ_CTRL_RES"

RF_DEMOD = f"RF_CH{READOUT_CH}"
RF_FIRE = 0x0
RF_FREQ = 0x4
RF_PHASE_OFFSET = 0xC
RF_SLOT_STRIDE = 0x10
RF_START_TIME = 0x4100
RF_CONF = 0x4104
# per-slot conf / freq tables (QICK channels with slot tables; absent from older builds' riscq_map.h)
RF_SLOT_CONF = "RQ_SLOT_CONF"
RF_SLOT_FREQ = "RQ_SLOT_FREQ"
# one-store fires (QICK channels with fireAt / fireSlot windows; absent from older builds' riscq_map.h)
RF_FIRE_AT = "RQ_FIRE_AT"
RF_FIRE_SLOT = "RQ_FIRE_SLOT"

EXIT_LABEL = "__qick_exit"
EXT_LABEL = "__qick_ext"
DMEM_LABEL = "__qick_dmem"
WMEM_LABEL = "__qick_wmem"
WMEM_FIELDS = ['freq', 'phase', 'env', 'gain', 'length', 'conf']
WMEM_STRIDE = 4 * len(WMEM_FIELDS)

CTRL_REG    = "t1"
REF_REG     = "s11"
T_REG       = "t0"
SCRATCH_REG = "t2"

# QICK register -> RISC-V register
DREG_RV = ['s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7', 's8', 's9', 's10',
           'a0', 'a1', 'a2', 'a3', 'a4']
WREG_RV = ['a5', 'a6', 'a7', 't3', 't4', 't5']
SREG_RV = {'s0': 'x0',
           's8': 'gp',
           's9': 'tp',
           's14': 't6'}
OUT_REG = SREG_RV['s14']


def rf_base(prog, ch: int) -> str:
    sym = f"RF_CH{ch}"
    if sym not in prog.soccfg.equs:
        raise RuntimeError(f"gen channel {ch} has no RISC-Q drive channel")
    return sym


def rv_reg(prog, name: str) -> str:
    """Translate a QICK register name or address to a RISC-V register."""
    addr = prog._get_reg(name)
    kind, idx = addr[0], int(addr[1:])
    if kind == 'r':
        if idx >= len(DREG_RV):
            raise RuntimeError(f"data register {addr} has no RISC-V mapping (max r{len(DREG_RV)-1})")
        return DREG_RV[idx]
    if kind == 'w':
        return WREG_RV[idx]
    if addr in SREG_RV:
        return SREG_RV[addr]
    raise RuntimeError(f"special register {addr} ({name}) has no RISC-V equivalent")


def ext_off(prog, name):
    """Byte offset in EXT_LABEL if name is a host-visible register (kept in memory), else None."""
    return {'s12': 0, 's13': 4}.get(prog._get_reg(name))


def fits_imm12(val: int) -> bool:
    return -2048 <= val < 2048


def to_int32(val: int) -> int:
    # constrain the value to signed 32-bit
    return int(np.int64(val).astype(np.int32))


def operand_rv(prog, src) -> tuple[list[str], str]:
    """Get a register holding src (int literal or register name) plus any setup instructions."""
    if isinstance(src, Integral):
        if src == 0:
            return [], 'x0'
        return [f'li {SCRATCH_REG}, {to_int32(src)}'], SCRATCH_REG
    if isinstance(src, str):
        return [], rv_reg(prog, src)
    raise RuntimeError(f"invalid operand: {src}")


def add_rv(dst: str, src: str, val) -> list[str]:
    """dst = src + val (val = int literal or RISC-V register)"""
    if isinstance(val, Integral):
        val = to_int32(val)
        if fits_imm12(val):
            return [f'addi {dst}, {src}, {val}']
        return [f'li {SCRATCH_REG}, {val}', f'add {dst}, {src}, {SCRATCH_REG}']
    return [f'add {dst}, {src}, {val}']


def abs_time_rv(prog, t_reg) -> list[str]:
    """T_REG = absolute time of t_reg (int ticks or register name) after the reference time."""
    if isinstance(t_reg, Integral):
        return add_rv(T_REG, REF_REG, t_reg)
    return add_rv(T_REG, REF_REG, rv_reg(prog, t_reg))


def rv_data_section(prog, dmem_words: int = 256) -> list[str]:
    """.data block backing ReadWmem/WriteWmem and ReadDmem/WriteDmem.
    Each waveform takes WMEM_STRIDE bytes, one word per field in WMEM_FIELDS order."""
    lines = ['.section .data', '.align 2', f'{WMEM_LABEL}:']
    for wave in prog.waves:
        for f in WMEM_FIELDS:
            val = getattr(wave, f)
            if isinstance(val, QickRawParam):
                val = val.start
            lines.append(f'.word {to_int32(val)}    # {wave.name}.{f}')
    for label, nbytes in [(EXT_LABEL, 8), (DMEM_LABEL, 4*dmem_words)]:
        lines += [f'.type {label}, @object', f'.size {label}, {nbytes}', f'{label}:', f'.space {nbytes}']
    return lines


# wait ch, p, $r
WAIT_RV = ['sw {r}, {addr}({ctrl_base})',
           'lw x0, {addr_cmp}({ctrl_base})']


def wait_rv(r: str) -> list[str]:
    fields = {'r': r, 'addr': WAIT_ADDR, 'addr_cmp': WAIT_ADDR + 8, 'ctrl_base': CTRL_REG}
    return [line.format(**fields) for line in WAIT_RV]

class RvMacro:
    # macros that keep the read_wmem -> write_wmem change tracking alive (see wmem_track)
    KEEPS_WMEM_TRACK = False

    def translate(self, prog):
        lines = self.expand_rv(prog)
        if not self.KEEPS_WMEM_TRACK:
            prog._wtrack = None
        for line in lines:
            prog._add_rv(line)


def has_fire_windows(prog) -> bool:
    return RF_FIRE_AT in prog.soccfg.equs and RF_FIRE_SLOT in prog.soccfg.equs


def _forget(known, reg):
    """`reg` is written: forget its value and every value computed from it."""
    known.pop(reg, None)
    for r in [r for r, k in known.items() if k[0] == 'addi' and k[1] == reg]:
        known.pop(r)


def drop_redundant_li(lines: list[str]) -> list[str]:
    """Drop `li` / `la` that load a register with the value it is already known to hold. Knowledge is per
    straight-line run: cleared at every label (a join point) and at any call, jump or return; a register is
    forgotten as soon as any instruction writes it (its first operand, except stores and branches)."""
    known, out = {}, []
    for line in lines:
        s = line.strip()
        if not s or s.startswith('#') or s.startswith('.'):
            out.append(line)
            continue
        if s.endswith(':'):
            known.clear()
            out.append(line)
            continue
        op, _, rest = s.partition(' ')
        args = [a.strip() for a in rest.split(',')] if rest else []
        if op in ('li', 'la') and len(args) == 2:
            if known.get(args[0]) == (op, args[1]):
                continue
            _forget(known, args[0])
            known[args[0]] = (op, args[1])
        elif op == 'addi' and len(args) == 3 and args[0] != args[1]:
            # rd = rs + imm with rd != rs: a repeat with neither register changed since is redundant
            key = ('addi', args[1], args[2])
            if known.get(args[0]) == key:
                continue
            _forget(known, args[0])
            known[args[0]] = key
        elif op in ('jal', 'jalr', 'call', 'ret', 'j', 'jr', 'tail', 'ecall', 'ebreak'):
            known.clear()
        elif op in ('sw', 'sh', 'sb') or op.startswith('b'):
            pass                                   # stores and branches write no register
        elif args:
            _forget(known, args[0])
        else:
            known.clear()                          # unknown form: forget everything
        out.append(line)
    return out


RV_REGS = {f'x{i}' for i in range(32)} | {'zero', 'ra', 'sp', 'gp', 'tp'} | {f't{i}' for i in range(7)} \
    | {f's{i}' for i in range(12)} | {f'a{i}' for i in range(8)} | {'fp'}


def _regs(arg: str) -> set:
    return {t for t in re.findall(r'[A-Za-z_][A-Za-z0-9_]*', arg) if t in RV_REGS}


def _dead_after_all_calls(lines, i, reg):
    """For a subroutine (the label before line i, with no label in between), True if every `jal ra, <it>`
    is followed by code that overwrites `reg` before reading it."""
    parsed = [_parse(l) for l in lines]
    k = i
    while k >= 0 and not (parsed[k] and parsed[k][0] == 'label'):
        k -= 1
    if k < 0:
        return False
    name = parsed[k][1]
    labels = _label_index(parsed)
    calls = [c for c, p in enumerate(parsed) if p and p[0] == 'inst' and p[1] in ('jal', 'call') and p[2][-1] == name]
    return bool(calls) and all(_dead_at(parsed, labels, c + 1, reg) for c in calls)


def drop_dead_wmem_loads(lines: list[str]) -> list[str]:
    """Drop a read_wmem load (`lw <w reg>, off(base)` with `base` set by `la base, __qick_wmem...`) whose
    register is written again before anything reads it, in the same straight-line run. A load still live at
    a label, jump, call, return or branch is kept. Only w registers loaded from wave memory are touched
    (plain RAM, no side effects), so control-block reads such as the time wait are never dropped."""
    wregs = set(WREG_RV)
    parsed = []
    for line in lines:
        s = line.strip()
        op, _, rest = s.partition(' ')
        parsed.append((s, op, [a.strip() for a in rest.split(',')] if rest else []))
    drop = set()
    wmem_base = {}
    for i, (s, op, args) in enumerate(parsed):
        if not s or s.startswith(('#', '.')):
            continue
        if s.endswith(':') or op in ('jal', 'jalr', 'call', 'ret', 'j', 'jr', 'tail'):
            wmem_base.clear()
            continue
        if op == 'la' and len(args) == 2:
            wmem_base[args[0]] = args[1].startswith(WMEM_LABEL)
            continue
        if op == 'lw' and len(args) == 2 and args[0] in wregs:
            base = re.search(r'\((\w+)\)', args[1])
            if base and wmem_base.get(base.group(1)):
                r = args[0]
                for j2, (s2, op2, args2) in enumerate(parsed[i + 1:], i + 1):
                    if not s2 or s2.startswith(('#', '.')):
                        continue
                    if op2 == 'ret' and _dead_after_all_calls(lines, i, r):
                        drop.add(i)                            # dead in every caller after the return
                        break
                    if s2.endswith(':') or op2.startswith(('b', 'j')) or op2 in ('call', 'ret', 'tail'):
                        # leaves the straight run: follow every path (dead if overwritten before any read)
                        pp = [_parse(x) for x in lines]
                        if r not in _reads(op2, args2) and _dead_at(pp, _label_index(pp), j2, r):
                            drop.add(i)
                        break
                    writes = op2 not in ('sw', 'sh', 'sb') and bool(args2)
                    srcs = set().union(*(_regs(a) for a in (args2[1:] if writes else args2))) if args2 else set()
                    if r in srcs:
                        break                                  # read: live
                    if writes and args2[0] == r:
                        drop.add(i)                            # overwritten unread: dead
                        break
        if args and op not in ('sw', 'sh', 'sb') and not op.startswith('b'):
            wmem_base.pop(args[0], None) if op != 'la' else None
    return [l for i, l in enumerate(lines) if i not in drop]


# ───────────────────────── post-passes over the final instruction list ─────────────────────────
CONTROL_OPS = ('j', 'jal', 'jalr', 'jr', 'ret', 'call', 'tail', 'ecall', 'ebreak')
STORE_OPS = ('sw', 'sh', 'sb')


def _parse(line):
    s = line.strip()
    if not s or s.startswith(('#', '.')):
        return None
    if s.endswith(':'):
        return ('label', s[:-1], [])
    op, _, rest = s.partition(' ')
    return ('inst', op, [a.strip() for a in rest.split(',')] if rest else [])


def _is_branch(op):
    return op.startswith('b')                  # RV32I + Zmmul: every b* mnemonic is a conditional branch


def _writes(op, args):
    if op in STORE_OPS or _is_branch(op) or op in ('j', 'jr', 'ret', 'tail', 'ecall', 'ebreak'):
        return None
    if op in ('jal', 'call'):
        return 'ra'
    return args[0] if args and args[0] in RV_REGS else None


def _reads(op, args):
    if op in ('j', 'jal', 'call', 'tail', 'ret', 'ecall', 'ebreak'):
        return set()
    src = args if (op in STORE_OPS or _is_branch(op) or op in ('jr', 'jalr')) else args[1:]
    out = set()
    for a in src:
        out |= _regs(a)
    return out


def _label_index(parsed):
    return {p[1]: i for i, p in enumerate(parsed) if p and p[0] == 'label'}


def _dead_at(parsed, labels, i, reg, depth=0, seen=None):
    """True if, from instruction index i on, `reg` is written before it is read on every path (following
    branches, jumps and calls); False when it is read, or at a return to an unknown caller or the end.
    Standard backward liveness: each start point is evaluated once (memoised in `seen`); a path that comes
    back to a start point still being evaluated adds no read (a loop), so it counts as dead."""
    memo = {} if seen is None else seen
    if reg in ('x0', 'zero'):
        return True
    if i in memo:
        return True if memo[i] is None else memo[i]
    memo[i] = None
    result = False
    k = i
    while k < len(parsed):
        p = parsed[k]
        if p is None or p[0] == 'label':
            k += 1
            continue
        _, op, args = p
        if reg in _reads(op, args):
            result = False
            break
        if op in ('jal', 'call') and args and args[-1] in labels:
            result = reg != 'ra' and _dead_at(parsed, labels, labels[args[-1]] + 1, reg, depth + 1, memo)
            break
        if op == 'ret' and _enclosing_label(parsed, k) == EXIT_LABEL:
            result = reg not in ('a0', 'ra', 'sp')  # main's return: only the return value is read after it
            break
        if op == 'j':
            result = args[0] in labels and _dead_at(parsed, labels, labels[args[0]] + 1, reg, depth + 1, memo)
            break
        if op in ('jal', 'call', 'jalr', 'jr', 'ret', 'tail', 'ecall', 'ebreak'):
            result = False
            break
        if _is_branch(op):
            tgt = args[-1]
            result = tgt in labels and _dead_at(parsed, labels, labels[tgt] + 1, reg, depth + 1, memo) and \
                _dead_at(parsed, labels, k + 1, reg, depth + 1, memo)
            break
        if _writes(op, args) == reg:
            result = True
            break
        k += 1
    memo[i] = result
    return result


def _enclosing_label(parsed, i):
    while i >= 0 and not (parsed[i] and parsed[i][0] == 'label'):
        i -= 1
    return parsed[i][1] if i >= 0 else None


def _sub_src(line, reg, new):
    """Replace `reg` by `new` in the source operands of one instruction (not its destination)."""
    p = _parse(line)
    _, op, args = p
    first = 0 if (op in STORE_OPS or _is_branch(op)) else 1
    out = list(args)
    for k in range(first, len(args)):
        out[k] = re.sub(rf'(?<![A-Za-z0-9_]){reg}(?![A-Za-z0-9_])', new, args[k])
    indent = line[:len(line) - len(line.lstrip())]
    return f"{indent}{op} {', '.join(out)}"


def _free_regs(lines):
    used = set()
    for l in lines:
        p = _parse(l)
        if p and p[0] == 'inst':
            for a in p[2]:
                used |= _regs(a)
    # QICK data registers the program never mentions (gp / tp / t6 are left alone: the C runtime may use them)
    return [r for r in DREG_RV if r not in used]


def _prologue_end(lines):
    """Index just after `main:`'s stack-frame setup: one-time setup inserted here runs before the start time
    is read, so it costs none of the initial delay."""
    m = lines.index('main:')
    k = m + 1
    while k < len(lines) and lines[k].strip().startswith(('addi sp', 'sw ra')):
        k += 1
    return k


def mirror_ext_counters(lines):
    """Keep the host-visible counters (`__qick_ext+0`, `+4`) in free registers: reads come from the register,
    every write still stores to memory (the host reads it there), and the counter increment loses its load.
    Skipped for a counter whose address is used in any other way."""
    free = _free_regs(lines)
    for off in (0, 4):
        sym = f'{EXT_LABEL}+{off}'
        if not free or not any(sym in l for l in lines):
            continue
        parsed = [_parse(l) for l in lines]
        # every use of a register holding `sym` must be `lw X, 0(B)` / `sw X, 0(B)` in the same straight run
        ok, base = True, {}
        for p in parsed:
            if p is None:
                continue
            if p[0] == 'label' or p[1] in CONTROL_OPS or _is_branch(p[1]):
                base.clear()
                continue
            _, op, args = p
            if op == 'la' and len(args) == 2:
                if args[1] == sym:
                    base[args[0]] = True
                    continue
                if sym in args[1]:
                    ok = False
            uses = [b for b in base if b in _reads(op, args)]
            for b in uses:
                if not (op in ('lw', 'sw') and len(args) == 2 and args[1] == f'0({b})' and args[0] != b):
                    ok = False
            w = _writes(op, args)
            if w in base:
                base.pop(w)
        if not ok:
            continue
        rc = free.pop(0)
        labels = _label_index(parsed)
        out, base, i = [], set(), 0
        while i < len(lines):
            p = parsed[i]
            l = lines[i]
            if p is None:
                out.append(l); i += 1; continue
            if p[0] == 'label' or p[1] in CONTROL_OPS or _is_branch(p[1]):
                base.clear(); out.append(l); i += 1; continue
            _, op, args = p
            ind = l[:len(l) - len(l.lstrip())]
            if op == 'la' and len(args) == 2 and args[1] == sym:
                # increment pattern: la B; lw X,0(B); addi X,X,K; sw X,0(B)  ->  addi rc,rc,K; la B; sw rc,0(B)
                q = [parsed[i + k] if i + k < len(parsed) else None for k in (1, 2, 3)]
                b = args[0]
                if all(q) and q[0][1] == 'lw' and q[0][2][1] == f'0({b})' and q[1][1] == 'addi' and \
                        q[1][2][0] == q[1][2][1] == q[0][2][0] and q[2][1] == 'sw' and q[2][2] == [q[0][2][0], f'0({b})']:
                    x, k = q[0][2][0], q[1][2][2]
                    out += [f'{ind}addi {rc}, {rc}, {k}', l, f'{ind}sw {rc}, 0({b})']
                    if not _dead_at(parsed, labels, i + 4, x):
                        out.append(f'{ind}mv {x}, {rc}')
                    base = {b}
                    i += 4
                    continue
                base.add(args[0]); out.append(l); i += 1; continue
            if op == 'lw' and len(args) == 2 and any(args[1] == f'0({b})' for b in base):
                out.append(f'{ind}mv {args[0]}, {rc}'); i += 1; continue
            out.append(l)
            if op == 'sw' and len(args) == 2 and any(args[1] == f'0({b})' for b in base):
                out.append(f'{ind}mv {rc}, {args[0]}')
            w = _writes(op, args)
            base.discard(w)
            i += 1
        k = _prologue_end(out)
        lines = out[:k] + [f'    la {rc}, {sym}', f'    lw {rc}, 0({rc})'] + out[k:]
    return lines


def hoist_loop_constants(lines):
    """Load constants used inside loops (`li` / `la` between a label and a backward branch to it) into free
    registers once, before the start time is read, and use those registers instead. Applied to one occurrence
    only when the register it loaded is provably not needed afterwards (dead on every path), so behaviour is
    unchanged; occurrences that cannot be proved are left alone."""
    free = _free_regs(lines)
    if not free:
        return lines
    parsed = [_parse(l) for l in lines]
    labels = _label_index(parsed)
    in_loop = [False] * len(lines)
    for b, p in enumerate(parsed):
        if p and p[0] == 'inst' and (_is_branch(p[1]) or p[1] == 'j') and p[2] and p[2][-1] in labels:
            l0 = labels[p[2][-1]]
            if l0 < b:
                for k in range(l0, b + 1):
                    in_loop[k] = True
    # a subroutine called from inside a loop runs every iteration too: its body (label to ret) counts as loop code
    for c, p in enumerate(parsed):
        if in_loop[c] and p and p[0] == 'inst' and p[1] in ('jal', 'call') and p[2] and p[2][-1] in labels:
            k = labels[p[2][-1]]
            while k < len(parsed) and not (parsed[k] and parsed[k][0] == 'inst' and parsed[k][1] == 'ret'):
                in_loop[k] = True
                k += 1
    const_reg, drop, subs = {}, set(), {}
    for i, p in enumerate(parsed):
        if not (in_loop[i] and p and p[0] == 'inst' and p[1] in ('li', 'la') and len(p[2]) == 2):
            continue
        r, c = p[2]
        key = (p[1], c)
        # the uses of r from here until it is overwritten, within this straight run
        uses, j, clean = [], i + 1, False
        while j < len(parsed):
            q = parsed[j]
            if q is None:
                j += 1; continue
            if q[0] == 'label':
                clean = _dead_at(parsed, labels, j, r)
                break
            _, op, args = q
            if r in _reads(op, args):
                uses.append(j)
            if op in CONTROL_OPS or _is_branch(op):
                tgt = labels.get(args[-1]) if args else None
                if op == 'j':
                    clean = tgt is not None and _dead_at(parsed, labels, tgt + 1, r)
                elif _is_branch(op):
                    clean = tgt is not None and _dead_at(parsed, labels, j + 1, r) and _dead_at(parsed, labels, tgt + 1, r)
                else:
                    clean = _dead_at(parsed, labels, j, r)   # call / return: follow it (unknown -> keep)
                break
            if _writes(op, args) == r:
                clean = True
                break
            j += 1
        if not clean or not uses:
            continue
        if key not in const_reg:
            if not free:
                continue
            const_reg[key] = free.pop(0)
        f = const_reg[key]
        drop.add(i)
        for u in uses:
            subs.setdefault(u, []).append((r, f))
    if not const_reg:
        return lines
    out = []
    for i, l in enumerate(lines):
        if i in drop:
            continue
        for r, f in subs.get(i, []):
            l = _sub_src(l, r, f)
        out.append(l)
    k = _prologue_end(out)
    return out[:k] + [f'    {op} {f}, {c}' for (op, c), f in const_reg.items()] + out[k:]


def _global_constants(lines):
    """Registers written exactly once in the whole program, by `li` / `la`: they hold that constant everywhere."""
    writes, const = {}, {}
    for l in lines:
        p = _parse(l)
        if p and p[0] == 'inst':
            w = _writes(p[1], p[2])
            if w:
                writes[w] = writes.get(w, 0) + 1
                if p[1] in ('li', 'la'):
                    const[w] = p[2][1]
    return {r: c for r, c in const.items() if writes[r] == 1}


def schedule_time_waits(lines):
    """Fill the time-compare wait's drain time: the wait read (`lw x0, 8(B)`, B = RQ_CTRL_TIME_CMP) first waits
    for the buffered compare store to land. Instructions that follow it in the same straight run are moved above
    it when that cannot change behaviour: register arithmetic, and stores to the direct-port regions (the RF
    windows, the core RAM labels), which issue without queueing behind the compare store. The wait only paces
    the CPU against the time counter, so these instructions do the same thing a few cycles earlier. Movement
    stops at the first load, other store, label, branch, jump or call."""
    const = _global_constants(lines)
    def direct_base(b):
        c = const.get(b, '')
        return c.startswith('RF_CH') or c.startswith('__qick_')
    out, i = [], 0
    while i < len(lines):
        p = _parse(lines[i])
        if p and p[0] == 'inst' and p[1] == 'lw' and p[2] and p[2][0] in ('x0', 'zero') and \
                re.fullmatch(r'8\((\w+)\)', p[2][1]) and const.get(re.fullmatch(r'8\((\w+)\)', p[2][1]).group(1)) == CTRL_BASE:
            moved, j = [], i + 1
            while j < len(lines):
                q = _parse(lines[j])
                if q is None:
                    j += 1; continue
                if q[0] == 'label' or q[1] in CONTROL_OPS or _is_branch(q[1]):
                    break
                op, args = q[1], q[2]
                if op in ('lw', 'lh', 'lb', 'lhu', 'lbu'):
                    break
                if op in STORE_OPS:
                    b = re.search(r'\((\w+)\)', args[1]) if len(args) == 2 else None
                    if not (b and direct_base(b.group(1))):
                        break
                moved.append(lines[j]); j += 1
            out += moved + [lines[i]]
            out += [l for l in lines[i + 1:j] if l not in moved or _parse(l) is None]
            i = j
            continue
        out.append(lines[i]); i += 1
    return out


def inline_small_calls(lines, max_len=40):
    """Replace `jal ra, F` by F's body when F is short and straight-line (a label, plain instructions, one
    `ret`, no calls, labels or branches inside): saves the call and return pipeline flushes. F's own copy stays."""
    parsed = [_parse(l) for l in lines]
    labels = _label_index(parsed)
    bodies = {}
    for name, k in labels.items():
        body, j = [], k + 1
        while j < len(parsed):
            p = parsed[j]
            if p is None:
                j += 1; continue
            if p[0] == 'label' or (p[1] in CONTROL_OPS and p[1] != 'ret') or _is_branch(p[1]):
                body = None; break
            if p[1] == 'ret':
                break
            body.append(lines[j]); j += 1
        if body is not None and j < len(parsed) and len(body) <= max_len:
            bodies[name] = body
    out = []
    for l, p in zip(lines, parsed):
        if p and p[0] == 'inst' and p[1] in ('jal', 'call') and p[2] and p[2][-1] in bodies and \
                (p[1] == 'call' or p[2][0] == 'ra'):
            out += bodies[p[2][-1]]
        else:
            out.append(l)
    return out


def promote_wmem_words(lines, max_regs=8):
    """Keep wave-memory words that are read inside loops in free registers. Applies only when every access to
    wave memory is a load or store at a constant address (`la B, __qick_wmem+N` then `lw/sw X, off(B)`); a read
    becomes `mv`, every write still stores to memory and also updates the register, so memory stays exact."""
    free = _free_regs(lines)
    if not free:
        return lines
    parsed = [_parse(l) for l in lines]
    labels = _label_index(parsed)
    in_loop = [False] * len(lines)
    for b, p in enumerate(parsed):
        if p and p[0] == 'inst' and (_is_branch(p[1]) or p[1] == 'j') and p[2] and p[2][-1] in labels and labels[p[2][-1]] < b:
            for k in range(labels[p[2][-1]], b + 1):
                in_loop[k] = True
    # walk once: resolve every wave-memory access to an absolute offset, or give up
    base, acc = {}, []          # acc: (index, 'lw'/'sw', reg, word offset)
    for i, p in enumerate(parsed):
        if p is None:
            continue
        if p[0] == 'label' or p[1] in CONTROL_OPS or _is_branch(p[1]):
            base.clear(); continue
        op, args = p[1], p[2]
        if op == 'la' and len(args) == 2 and args[1].startswith(WMEM_LABEL):
            m = re.fullmatch(re.escape(WMEM_LABEL) + r'(?:\+(\d+))?', args[1])
            if not m:
                return lines
            base[args[0]] = int(m.group(1) or 0); continue
        used = [b for b in base if b in _reads(op, args)]
        if used:
            mm = re.fullmatch(r'(-?\d+)\((\w+)\)', args[1]) if op in ('lw', 'sw') and len(args) == 2 else None
            if not mm or mm.group(2) not in base or args[0] in base:
                return lines                                   # some other use of a wave-memory address
            acc.append((i, op, args[0], base[mm.group(2)] + int(mm.group(1))))
        elif any(WMEM_LABEL in a for a in args):
            return lines
        w = _writes(op, args)
        base.pop(w, None)
    hot = []
    for i, op, r, off in acc:
        if op == 'lw' and in_loop[i] and off not in hot:
            hot.append(off)
    hot = hot[:min(max_regs, len(free))]
    if not hot:
        return lines
    reg = {off: free.pop(0) for off in hot}
    edits = {i: (op, r, off) for i, op, r, off in acc if off in reg}
    out = []
    for i, l in enumerate(lines):
        if i in edits:
            op, r, off = edits[i]
            ind = l[:len(l) - len(l.lstrip())]
            if op == 'lw':
                out.append(f'{ind}mv {r}, {reg[off]}')
            else:
                out.append(l)
                if r != reg[off]:
                    out.append(f'{ind}mv {reg[off]}, {r}')
        else:
            out.append(l)
    k = _prologue_end(out)
    init = []
    for off, f in reg.items():
        init += [f'    la {f}, {WMEM_LABEL}+{off}', f'    lw {f}, 0({f})']
    return out[:k] + init + out[k:]


def _rename(line, old, new):
    p = _parse(line)
    _, op, args = p
    out = [re.sub(rf'(?<![A-Za-z0-9_]){old}(?![A-Za-z0-9_])', new, a) for a in args]
    ind = line[:len(line) - len(line.lstrip())]
    return f"{ind}{op} {', '.join(out)}"


def coalesce_copies(lines):
    """`mv X, P` ... `mv P, X` in one straight run, with P untouched in between and X dead after: work on P
    directly (rename X to P in between) and drop both moves."""
    changed = True
    while changed:
        changed = False
        parsed = [_parse(l) for l in lines]
        labels = _label_index(parsed)
        for i, p in enumerate(parsed):
            if not (p and p[0] == 'inst' and p[1] == 'mv' and len(p[2]) == 2):
                continue
            x, src = p[2]
            if x == src or x in ('x0', 'zero'):
                continue
            j = i + 1
            while j < len(parsed):
                q = parsed[j]
                if q is None:
                    j += 1; continue
                if q[0] == 'label' or q[1] in CONTROL_OPS or _is_branch(q[1]):
                    j = None; break
                if q[1] == 'mv' and q[2] == [src, x]:
                    break
                if src in _reads(q[1], q[2]) or _writes(q[1], q[2]) == src:
                    j = None; break
                j += 1
            if j is None or j >= len(parsed):
                continue
            # after `mv P, X`, X and P are equal: later reads of X (until X is overwritten, P changes or the run
            # ends) may read P instead; then X must be dead there
            k = j + 1
            while k < len(parsed):
                q = parsed[k]
                if q is None:
                    k += 1; continue
                if q[0] == 'label' or q[1] in CONTROL_OPS or _is_branch(q[1]):
                    break
                if _writes(q[1], q[2]) in (x, src):
                    break
                k += 1
            if not _dead_at(parsed, labels, k, x):
                continue
            mid = [_rename(l, x, src) if parsed[n] else l for n, l in enumerate(lines[i + 1:j], i + 1)]
            tail = [_sub_src(l, x, src) if parsed[n] and x in _reads(parsed[n][1], parsed[n][2]) else l
                    for n, l in enumerate(lines[j + 1:k], j + 1)]
            lines = lines[:i] + mid + tail + lines[k:]
            changed = True
            break
    return lines


def drop_dead_defs(lines):
    """Drop `li` / `la` / `mv` whose result is never read on any path."""
    parsed = [_parse(l) for l in lines]
    labels = _label_index(parsed)
    keep = []
    for i, (l, p) in enumerate(zip(lines, parsed)):
        if p and p[0] == 'inst' and p[1] in ('li', 'la', 'mv') and p[2] and p[2][0] not in ('x0', 'zero') \
                and _dead_at(parsed, labels, i + 1, p[2][0]):
            continue
        keep.append(l)
    return keep


def optimize_rv(lines):
    lines = inline_small_calls(lines)
    lines = drop_dead_wmem_loads(lines)
    lines = promote_wmem_words(lines)
    lines = mirror_ext_counters(lines)
    lines = hoist_loop_constants(lines)
    lines = drop_redundant_li(lines)
    lines = coalesce_copies(lines)
    lines = drop_dead_defs(lines)
    return schedule_time_waits(lines)


def sweep_value_rv(prog, wname: str, par: str, loops: list) -> list[str]:
    """w[par] = start + sum(index * step) over `loops` (loop names whose counters hold the current index),
    using the multiplier: the value QICK's incremental sweep steps to, computed with no memory load."""
    w = dict(zip(WMEM_FIELDS, WREG_RV))
    val = getattr(prog.waves[prog.wave2idx[wname]], par)
    insts = [f'li {w[par]}, {to_int32(val.start)}']
    for lname in loops:
        st = (val.steps or {}).get(lname)
        if not st or st['step'] == 0:
            continue
        idx = rv_reg(prog, prog.reg_dict[lname].full_addr())
        insts += [f'li {SCRATCH_REG}, {to_int32(st["step"])}', f'mul {SCRATCH_REG}, {idx}, {SCRATCH_REG}',
                  f'add {w[par]}, {w[par]}, {SCRATCH_REG}']
    return insts


def has_mul(prog) -> bool:
    try:
        return bool(prog.soccfg.soc_map.params.with_mul)
    except AttributeError:
        return False


def has_slot_tables(prog) -> bool:
    return RF_SLOT_CONF in prog.soccfg.equs and RF_SLOT_FREQ in prog.soccfg.equs


def wave_slots(prog) -> dict:
    """{(gen ch, waveform name): table slot}. With slot tables in the hardware, every waveform a channel plays
    gets its own pulse-table slot (fields, freq and conf), loaded once before the program reads the start time;
    a pulse is then only a start-time write and one fire per waveform. A channel playing more waveforms than it
    has slots is left out and reloads slots 0, 1, ... before every pulse, as before."""
    if prog._rv_slots is None:
        slots = {}
        if has_slot_tables(prog):
            per_ch = {}
            for m in prog.macro_list:
                if isinstance(m, Pulse):
                    waves = per_ch.setdefault(m.ch, [])
                    waves += [w for w in prog.pulses[m.name].get_wavenames() if w not in waves]
            nslots = prog.soccfg.equs['RQ_GATE_PULSE_NUM']
            counts = {}
            for m in prog.macro_list:
                if isinstance(m, Pulse):
                    for w in prog.pulses[m.name].get_wavenames():
                        counts[(m.ch, w)] = counts.get((m.ch, w), 0) + 1
            for ch, waves in per_ch.items():
                if len(waves) <= nslots:
                    slots.update({(ch, w): i for i, w in enumerate(waves)})
                elif has_fire_windows(prog) and nslots >= 8:
                    # slot cache: the most-played waveforms keep their own slot; the rest take turns in the last
                    # few slots, rewritten just before each fire (a fire captures the slot as it is then)
                    ndyn = max(2, nslots // 8)
                    hot = sorted(waves, key=lambda w: -counts[(ch, w)])[:nslots - ndyn]
                    slots.update({(ch, w): i for i, w in enumerate(hot)})
                    prog._rv_dyn[ch] = list(range(nslots - ndyn, nslots))
        prog._rv_slots = slots
    return prog._rv_slots


def wave_is_constant(prog, wname) -> bool:
    """No sweep and no write_wmem touches this waveform, so its fields are compile-time constants."""
    wave = prog.waves[prog.wave2idx[wname]]
    if any(sw.is_sweep() for sw in wave.sweeps()):
        return False
    return not any(isinstance(m, WriteWmem) and getattr(m, 'name', None) == wname for m in prog.macro_list)


def dyn_slot_load_rv(prog, ch, wname, slot) -> list[str]:
    """Write every field of `wname` into a reused cache slot: from constants when it never changes, else read
    from wave memory."""
    w = dict(zip(WMEM_FIELDS, WREG_RV))
    if wave_is_constant(prog, wname):
        vals = wave_initial(prog.waves[prog.wave2idx[wname]])
        insts = [f'li {w[f]}, {vals[f]}' for f in WMEM_FIELDS]
    else:
        insts = RvReadWmem(name=wname).expand_rv(prog)
    return insts + slot_store_rv(prog, ch, slot, {f: w[f] for f in WMEM_FIELDS})


def slot_store_rv(prog, ch: int, slot: int, regs: dict) -> list[str]:
    """Store waveform fields (field name -> register) into a channel's table slot."""
    ch_base = rf_base(prog, ch)
    base = (slot + 1) * RF_SLOT_STRIDE
    table = {'phase': None, 'gain': base + 4, 'env': base + 8, 'length': base + 12}
    insts = [f'li {CTRL_REG}, {ch_base}']
    for f, reg in regs.items():
        if f == 'phase':
            insts.append(f'sw {reg}, {base}({CTRL_REG})')
        elif f in table:
            insts += seat16(reg, table[f])
        elif f == 'conf':
            insts += [f'li {SCRATCH_REG}, {ch_base}+{RF_SLOT_CONF}+{4*slot}', f'sw {reg}, 0({SCRATCH_REG})']
        elif f == 'freq':
            insts += [f'li {SCRATCH_REG}, {ch_base}+{RF_SLOT_FREQ}+{4*slot}', f'sw {reg}, 0({SCRATCH_REG})']
    return insts


def wave_initial(wave) -> dict:
    vals = {}
    for f in WMEM_FIELDS:
        val = getattr(wave, f)
        if isinstance(val, QickRawParam):
            val = val.start
        vals[f] = to_int32(val)
    return vals


def slot_init_rv(prog) -> list[str]:
    """Load every allocated slot with its waveform's initial fields (runs before the start-time read)."""
    insts = []
    for (ch, wname), slot in wave_slots(prog).items():
        vals = wave_initial(prog.waves[prog.wave2idx[wname]])
        insts += [f'# slot {slot} of gen {ch} <- {wname}']
        regs = {}
        for f, reg in zip(WMEM_FIELDS, WREG_RV):
            insts.append(f'li {reg}, {vals[f]}')
            regs[f] = reg
        insts += slot_store_rv(prog, ch, slot, regs)
    return insts


def wmem_store_rv(prog, name: str, fields) -> list[str]:
    """Store the given fields of waveform `name` from the w registers to wmem, and through to every table slot
    that holds that waveform."""
    w = dict(zip(WMEM_FIELDS, WREG_RV))
    offset = prog.wave2idx[name] * WMEM_STRIDE
    fields = [f for f in WMEM_FIELDS if f in fields]
    if not fields:
        return []
    insts = [f'la {CTRL_REG}, {WMEM_LABEL}+{offset}']
    insts += [f'sw {w[f]}, {4*WMEM_FIELDS.index(f)}({CTRL_REG})' for f in fields]
    for (ch, wname), slot in wave_slots(prog).items():
        if wname == name:
            insts += slot_store_rv(prog, ch, slot, {f: w[f] for f in fields})
    return insts


def wmem_track_field(prog, dst):
    """Note a write to w register `dst` for the open read_wmem -> write_wmem tracking."""
    if prog._wtrack is None or not isinstance(dst, str):
        return
    try:
        reg = rv_reg(prog, dst)
    except RuntimeError:
        return
    if reg in WREG_RV:
        prog._wtrack[1].add(WMEM_FIELDS[WREG_RV.index(reg)])


class RvLabel(RvMacro, Label):
    def expand_rv(self, prog):
        return [f'{self.label}:']


class RvAsmInst(RvMacro, Macro):
    def expand_rv(self, prog):
        return [self.inst]


class RvTprocInst(RvMacro, AsmInst):
    """tProc v2 instruction dict from an AsmV2 snippet: only the commands with a plain RISC-V equivalent translate."""
    TRANSLATABLE = {'NOP': 'nop', 'RET': 'ret'}

    def expand_rv(self, prog):
        cmd = self.inst.get('CMD')
        if cmd not in self.TRANSLATABLE:
            raise RuntimeError(f"no RISC-V translation for tProc v2 instruction {cmd}")
        return [self.TRANSLATABLE[cmd]]


class RvWriteLabel(RvMacro, WriteLabel):
    def expand_rv(self, prog):
        return []


class RvEnd(RvMacro, End):
    def expand_rv(self, prog):
        return [f'j {EXIT_LABEL}']

class RvWriteReg(RvMacro, WriteReg):
    KEEPS_WMEM_TRACK = True

    def expand_rv(self, prog):
        wmem_track_field(prog, self.dst)
        off = ext_off(prog, self.dst)
        if off is not None:
            setup, src = operand_rv(prog, self.src)
            return [f'la {T_REG}, {EXT_LABEL}+{off}', *setup, f'sw {src}, 0({T_REG})']
        dst = rv_reg(prog, self.dst)
        if isinstance(self.src, Integral):
            return [f'li {dst}, {to_int32(self.src)}']
        if isinstance(self.src, str):
            return [f'mv {dst}, {rv_reg(prog, self.src)}']
        raise RuntimeError(f"invalid src: {self.src}")

class RvIncReg(RvMacro, IncReg):
    KEEPS_WMEM_TRACK = True

    def expand_rv(self, prog):
        wmem_track_field(prog, self.dst)
        off = ext_off(prog, self.dst)
        if off is not None:
            return [f'la {T_REG}, {EXT_LABEL}+{off}', f'lw {CTRL_REG}, 0({T_REG})',
                    *add_rv(CTRL_REG, CTRL_REG, self.src if isinstance(self.src, Integral) else rv_reg(prog, self.src)),
                    f'sw {CTRL_REG}, 0({T_REG})']
        dst = rv_reg(prog, self.dst)
        if isinstance(self.src, Integral):
            return add_rv(dst, dst, self.src)
        if isinstance(self.src, str):
            return add_rv(dst, dst, rv_reg(prog, self.src))
        raise RuntimeError(f"invalid src: {self.src}")


class RvReadWmem(RvMacro, ReadWmem):
    KEEPS_WMEM_TRACK = True

    def expand_rv(self, prog):
        offset = prog.wave2idx[self.name] * WMEM_STRIDE
        insts = [f'la {CTRL_REG}, {WMEM_LABEL}+{offset}']
        insts += [f'lw {reg}, {4*i}({CTRL_REG})' for i, reg in enumerate(WREG_RV)]
        # the w registers now equal this waveform's wmem: track which fields change before a write_wmem
        prog._wtrack = (self.name, set())
        return insts


class RvWriteWmem(RvMacro, WriteWmem):
    KEEPS_WMEM_TRACK = True

    def expand_rv(self, prog):
        # straight after a read_wmem of the same waveform (only register writes in between), store only the
        # fields that changed; otherwise all of them
        track = prog._wtrack
        fields = track[1] if track is not None and track[0] == self.name else WMEM_FIELDS
        insts = wmem_store_rv(prog, self.name, fields)
        prog._wtrack = (self.name, set())
        return insts


def dmem_addr_rv(prog, addr) -> list[str]:
    """T_REG = address of dmem word addr (int literal or register name)."""
    if isinstance(addr, Integral):
        return [f'la {T_REG}, {DMEM_LABEL}+{4*addr}']
    if isinstance(addr, str):
        return [f'la {T_REG}, {DMEM_LABEL}',
                f'slli {SCRATCH_REG}, {rv_reg(prog, addr)}, 2',
                f'add {T_REG}, {T_REG}, {SCRATCH_REG}']
    raise RuntimeError(f"invalid addr: {addr}")


class RvReadDmem(RvMacro, ReadDmem):
    def expand_rv(self, prog):
        off = ext_off(prog, self.dst)
        if off is not None:
            return [*dmem_addr_rv(prog, self.addr), f'lw {CTRL_REG}, 0({T_REG})',
                    f'la {T_REG}, {EXT_LABEL}+{off}', f'sw {CTRL_REG}, 0({T_REG})']
        dst = rv_reg(prog, self.dst)
        return [*dmem_addr_rv(prog, self.addr), f'lw {dst}, 0({T_REG})']


class RvWriteDmem(RvMacro, WriteDmem):
    def expand_rv(self, prog):
        insts = dmem_addr_rv(prog, self.addr)
        setup, src = operand_rv(prog, self.src)
        return [*insts, *setup, f'sw {src}, 0({T_REG})']

class RvReadInput(RvMacro, ReadInput):
    def expand_rv(self, prog):
        port_l = rv_reg(prog, 's_port_l')
        port_h = rv_reg(prog, 's_port_h')
        return [f'li {CTRL_REG}, {CTRL_RES}',
                f'lw x0, 0({CTRL_REG})',
                f'lw {port_l}, 4({CTRL_REG})',
                f'lw {port_h}, 8({CTRL_REG})']


class RvJump(RvMacro, Jump):
    def expand_rv(self, prog):
        return [f'j {self.label}']


class RvCall(RvMacro, Call):
    def expand_rv(self, prog):
        return [f'jal ra, {self.label}']


class RvCondJump(RvMacro, CondJump):
    ZERO_TESTS = {'Z': 'beqz', 'NZ': 'bnez', 'S': 'bltz', 'NS': 'bgez'}
    CMP_TESTS = {'Z': 'beq', 'NZ': 'bne', 'S': 'blt', 'NS': 'bge'}
    OPS = {'+': ('add', 'addi'),
           '>>': ('sra', 'srai'),
           '&': ('and', 'andi')}

    def expand_rv(self, prog):
        if self.test == '1':
            return [f'j {self.label}']
        if self.test == '0':
            return []
        if self.test not in self.ZERO_TESTS:
            raise RuntimeError(f"test {self.test} has no RISC-V equivalent")

        arg1 = rv_reg(prog, self.arg1)
        if self.arg2 is None:
            if self.op is not None:
                raise RuntimeError("an operation was supplied, but no second operand")
            return [f'{self.ZERO_TESTS[self.test]} {arg1}, {self.label}']
        if self.op is None:
            raise RuntimeError("a second operand was supplied, but no operation")

        if self.op == '-':
            setup, arg2 = operand_rv(prog, self.arg2)
            return [*setup, f'{self.CMP_TESTS[self.test]} {arg1}, {arg2}, {self.label}']

        reg_op, imm_op = self.OPS[self.op]
        if isinstance(self.arg2, Integral) and fits_imm12(self.arg2):
            insts = [f'{imm_op} {T_REG}, {arg1}, {self.arg2}']
        else:
            setup, arg2 = operand_rv(prog, self.arg2)
            insts = [*setup, f'{reg_op} {T_REG}, {arg1}, {arg2}']
        insts.append(f'{self.ZERO_TESTS[self.test]} {T_REG}, {self.label}')
        return insts



class RvOpenLoop(RvMacro, OpenLoop):
    def expand_rv(self, prog):
        prog.loop_stack.append((self.name, self.n))
        return [*RvWriteReg(dst=self.name, src=0).expand_rv(prog),
                f'{self.name}:']


class RvCloseLoop(RvMacro, CloseLoop):
    def expand_rv(self, prog):
        insts = []

        lname, lcount = prog.loop_stack.pop()
        label = lname

        wave_sweeps = []
        for wave in prog.waves:
            spans_to_apply = []
            for sweep in wave.sweeps():
                if lname in sweep.steps and sweep.steps[lname]['step']!=0:
                    spans_to_apply.append((sweep.par, sweep.steps[lname]))
            if spans_to_apply:
                wave_sweeps.append((wave.name, spans_to_apply))

        reg_sweeps = []
        for reg in prog.reg_dict.values():
            if isinstance(reg.init, QickRawParam) and lname in reg.init.spans and reg.init.steps[lname]['step']!=0:
                reg_sweeps.append((reg, reg.init.steps[lname]))

        for wname, spans_to_apply in wave_sweeps:
            insts += RvReadWmem(name=wname).expand_rv(prog)
            for par, steps in spans_to_apply:
                insts += RvIncReg(dst="w_"+par, src=steps['step']).expand_rv(prog)
            insts += wmem_store_rv(prog, wname, [par for par, _ in spans_to_apply])
        for reg, steps in reg_sweeps:
            insts += RvIncReg(dst=reg.full_addr(), src=steps['step']).expand_rv(prog)

        reg = rv_reg(prog, prog.reg_dict[lname].full_addr())
        if has_mul(prog) and wave_sweeps:
            # no wave-memory loads: recompute each swept field from the loop counters (start + index * step)
            # and store it to wave memory and through to its slots. In the loop: this loop's new index plus
            # every enclosing loop's; after the exit this loop's term is 0 again (QICK resets the sweep).
            outer = [name for name, _ in prog.loop_stack]
            insts = [i for i in insts if False]        # drop the load-based increments built above
            for reg_, steps in reg_sweeps:
                insts += RvIncReg(dst=reg_.full_addr(), src=steps['step']).expand_rv(prog)
            insts.append(f'addi {reg}, {reg}, 1')
            for wname, spans_to_apply in wave_sweeps:
                for par, _ in spans_to_apply:
                    insts += sweep_value_rv(prog, wname, par, outer + [lname])
                insts += wmem_store_rv(prog, wname, [par for par, _ in spans_to_apply])
            insts += [f'li {T_REG}, {lcount}', f'blt {reg}, {T_REG}, {label}']
            for wname, spans_to_apply in wave_sweeps:
                for par, _ in spans_to_apply:
                    insts += sweep_value_rv(prog, wname, par, outer)
                insts += wmem_store_rv(prog, wname, [par for par, _ in spans_to_apply])
            for reg_, steps in reg_sweeps:
                insts += RvIncReg(dst=reg_.full_addr(), src=-steps['step']-steps['span']).expand_rv(prog)
            return insts
        insts += [f'addi {reg}, {reg}, 1',
                  f'li {T_REG}, {lcount}',
                  f'blt {reg}, {T_REG}, {label}']

        for wname, spans_to_apply in wave_sweeps:
            insts += RvReadWmem(name=wname).expand_rv(prog)
            for par, steps in spans_to_apply:
                insts += RvIncReg(dst="w_"+par, src=-steps['step']-steps['span']).expand_rv(prog)
            insts += wmem_store_rv(prog, wname, [par for par, _ in spans_to_apply])
        for reg, steps in reg_sweeps:
            insts += RvIncReg(dst=reg.full_addr(), src=-steps['step']-steps['span']).expand_rv(prog)

        return insts

def set_timereg_rv(prog, t_reg) -> list[str]:
    return RvWriteReg(dst='s_out_time', src=t_reg).expand_rv(prog)


def inc_timereg_rv(prog, t_reg) -> list[str]:
    return RvIncReg(dst='s_out_time', src=t_reg).expand_rv(prog)


class RvDelay(RvMacro, Delay):
    def expand_rv(self, prog):
        t_reg = self.t_regs["t"]
        if t_reg is None:
            return []
        if isinstance(t_reg, int):
            return add_rv(REF_REG, REF_REG, t_reg)
        return add_rv(REF_REG, REF_REG, rv_reg(prog, t_reg))


class RvWait(RvMacro, Wait):
    def expand_rv(self, prog):
        t_reg = self.t_regs["t"]
        if t_reg is None:
            return []
        if not isinstance(t_reg, int):
            raise RuntimeError("WAIT can only take a scalar argument, not a sweep")
        return [*abs_time_rv(prog, t_reg),
                f'li {CTRL_REG}, {CTRL_BASE}',
                *wait_rv(T_REG)]


class RvResync(RvMacro, Resync):
    def expand_rv(self, prog):
        t = self.t_regs["t"]
        t_val = t if isinstance(t, int) else rv_reg(prog, t)
        return [
                f'li {CTRL_REG}, {CTRL_TIME}',
                f'lw {T_REG}, 0({CTRL_REG})',
                f'sub {T_REG}, {T_REG}, {REF_REG}',
                *add_rv(T_REG, T_REG, t_val),
                f'bgez {T_REG}, 1f',
                f'mv {T_REG}, x0',
                '1:',
                f'add {REF_REG}, {REF_REG}, {T_REG}']


def seat16(reg: str, off: int) -> list[str]:
    """Store a 16-bit field: the hardware reads it from data[31:16] (PulseParamBuffer bitOffset = 16)."""
    return [f'slli {SCRATCH_REG}, {reg}, 16', f'sw {SCRATCH_REG}, {off}({CTRL_REG})']


def fire_rv(ch_base: str, slot: int) -> list[str]:
    """Write T_REG as the start time of ch_base, then fire slot."""
    return [f'li {SCRATCH_REG}, {ch_base}+{RF_START_TIME}',
            f'sw {T_REG}, 0({SCRATCH_REG})',
            f'li {CTRL_REG}, {ch_base}',
            *([f'sw x0, {RF_FIRE}({CTRL_REG})'] if slot == 0 else
              [f'li {SCRATCH_REG}, {slot}', f'sw {SCRATCH_REG}, {RF_FIRE}({CTRL_REG})'])]


def init_rv(prog) -> list[str]:
    """Clear the virtual-Z phase offset of every declared gen, which hardware never resets."""
    return [line for ch in prog.gen_chs
            for line in (f'li {CTRL_REG}, {rf_base(prog, ch)}', f'sw x0, {RF_PHASE_OFFSET}({CTRL_REG})')]


class RvPulse(RvMacro, Pulse):
    def expand_rv(self, prog):
        insts = []
        pulse = prog.pulses[self.name]
        ch_base = rf_base(prog, self.ch)
        t_reg = self.t_regs['t']
        if isinstance(t_reg, Integral):
            insts += abs_time_rv(prog, t_reg)
        else:
            insts += set_timereg_rv(prog, t_reg)
            insts += add_rv(T_REG, REF_REG, OUT_REG)
        waves = pulse.get_wavenames()
        slots = wave_slots(prog)
        dyn = prog._rv_dyn.get(self.ch)
        if dyn and has_fire_windows(prog) and any((self.ch, wave) not in slots for wave in waves):
            # slot cache: cold waveforms are written into the rotating slots right before their fire
            step = prog.soccfg.equs[RF_FIRE_SLOT] - prog.soccfg.equs[RF_FIRE_AT]
            for k, wave in enumerate(waves):
                if (self.ch, wave) in slots:
                    slot = slots[(self.ch, wave)]
                else:
                    slot = dyn[prog._rv_dyn_next.get(self.ch, 0) % len(dyn)]
                    prog._rv_dyn_next[self.ch] = prog._rv_dyn_next.get(self.ch, 0) + 1
                    insts += dyn_slot_load_rv(prog, self.ch, wave, slot)
                insts.append(f'li {CTRL_REG}, {ch_base}+{RF_FIRE_AT}')
                insts.append(f'sw {T_REG}, {4*slot}({CTRL_REG})' if k == 0 else
                             f'sw x0, {step + 4*slot}({CTRL_REG})')
            return insts
        if all((self.ch, wave) in slots for wave in waves) and has_fire_windows(prog):
            # one store per waveform: fireAt(slot) sets the start time and fires; each later waveform is a
            # fireSlot (start auto-advanced by the previous one's length). The window base stays in CTRL_REG,
            # so back-to-back pulses on one channel reload nothing (drop_redundant_li).
            step = prog.soccfg.equs[RF_FIRE_SLOT] - prog.soccfg.equs[RF_FIRE_AT]
            insts.append(f'li {CTRL_REG}, {ch_base}+{RF_FIRE_AT}')
            for k, wave in enumerate(waves):
                slot = slots[(self.ch, wave)]
                insts.append(f'sw {T_REG}, {4*slot}({CTRL_REG})' if k == 0 else
                             f'sw x0, {step + 4*slot}({CTRL_REG})')
            return insts
        if all((self.ch, wave) in slots for wave in waves):
            # every waveform already sits in its own slot: set the start time once and fire them in order; each
            # fire advances the channel's start time by that waveform's length (PulseParamBuffer auto-advance)
            insts += [f'li {SCRATCH_REG}, {ch_base}+{RF_START_TIME}',
                      f'sw {T_REG}, 0({SCRATCH_REG})',
                      f'li {CTRL_REG}, {ch_base}']
            for wave in waves:
                slot = slots[(self.ch, wave)]
                insts += ([f'sw x0, {RF_FIRE}({CTRL_REG})'] if slot == 0 else
                          [f'li {SCRATCH_REG}, {slot}', f'sw {SCRATCH_REG}, {RF_FIRE}({CTRL_REG})'])
            return insts
        w = dict(zip(WMEM_FIELDS, WREG_RV))
        for slot, wave in enumerate(waves):
            if slot > 0:
                insts.append(f'add {T_REG}, {T_REG}, {w["length"]}')
            insts += RvReadWmem(name=wave).expand_rv(prog)
            base = (slot + 1) * RF_SLOT_STRIDE
            insts += [f'li {CTRL_REG}, {ch_base}',
                      f'sw {w["freq"]}, {RF_FREQ}({CTRL_REG})',
                      f'sw {w["phase"]}, {base}({CTRL_REG})',
                      *seat16(w["gain"], base + 4),
                      *seat16(w["env"], base + 8),
                      *seat16(w["length"], base + 12),
                      f'li {SCRATCH_REG}, {ch_base}+{RF_CONF}',
                      f'sw {w["conf"]}, 0({SCRATCH_REG})']
            insts += fire_rv(ch_base, slot)
        return insts


class RvConfigReadout(RvMacro, ConfigReadout):
    def expand_rv(self, prog):
        insts = []
        pulse = prog.pulses[self.name]
        w = dict(zip(WMEM_FIELDS, WREG_RV))
        for wave in pulse.get_wavenames():
            insts += RvReadWmem(name=wave).expand_rv(prog)
            # 32-bit codes as the standard firmware takes them; the demod uses the top 16 bits
            insts += [f'li {CTRL_REG}, {RF_DEMOD}',
                      f'sw {w["freq"]}, {RF_FREQ}({CTRL_REG})', f'sw {w["phase"]}, {RF_PHASE_OFFSET}({CTRL_REG})']
        return insts


class RvTrigger(RvMacro, Trigger):
    def preprocess(self, prog):
        self.check()
        super().preprocess(prog)

    def check(self):
        if self.pins or self.tts or self.ddr4 or self.mr:
            raise RuntimeError("RISC-Q only supports readout triggers (no pins, time taggers, ddr4 or mr)")

    def expand_rv(self, prog):
        self.check()
        if not self.ros:
            return []
        t_reg = self.t_regs['t']
        if t_reg is None:
            insts = add_rv(T_REG, REF_REG, OUT_REG)
        else:
            insts = abs_time_rv(prog, t_reg)
        return [*insts, *fire_rv(RF_DEMOD, 0)]


RV_MACROS = {AsmInst: RvTprocInst, Label: RvLabel, WriteLabel: RvWriteLabel, End: RvEnd,
             WriteReg: RvWriteReg, IncReg: RvIncReg,
             ReadWmem: RvReadWmem, WriteWmem: RvWriteWmem,
             ReadDmem: RvReadDmem, WriteDmem: RvWriteDmem,
             ReadInput: RvReadInput, Jump: RvJump, Call: RvCall, CondJump: RvCondJump,
             OpenLoop: RvOpenLoop, CloseLoop: RvCloseLoop,
             Delay: RvDelay, Wait: RvWait, Resync: RvResync,
             Pulse: RvPulse, ConfigReadout: RvConfigReadout, Trigger: RvTrigger}
