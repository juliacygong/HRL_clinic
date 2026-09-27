"""
Translates QICK tProcessor (tProc v2) programs into RV32I code for the RISC-Q core.

Every tProc v2 instruction is lowered to a short RV32I sequence that implements the same semantics,
including register allocation, spill to data memory, and scheduling of RISC-Q channels.

Input
    A compiled :class:`qick.asm_v2.QickProgramV2` (its ``prog_list``/``labels`` plus the wave and data
    memory images), tProc v2 assembly text (parsed with :mod:`qick.tprocv2_assembler`), or a
    ``(prog_list, labels)`` pair in the assembler's instruction-dict format.

Semantics follow the tProc v2 RTL (firmware/ip/qick_processor/src: qcore_cpu.sv, qcore_reg_bank.sv,
_qproc_ips.sv AB_alu, qproc_ctrl.sv) and the assembler (tprocv2_assembler.py); the RISC-Q side follows
risc-q/software/fw/riscq.h and risc-q/software/riscq/map.py.

* :func:`to_asm` -- GNU assembly defining ``main``, to link with risc-q/software/fw/start.S.
* :func:`to_image` -- self-contained, bootable RV32I image (machine words), encoded here so no RISC-V
  toolchain is needed. It follows start.S's ``__rq_status``/``__rq_magic`` protocol.

Register model
    s0 reads as zero (x0). r0-r31, w0-w5 and the writable special registers get dedicated RISC-V
    registers by use count (22 available); the rest live in a memory-backed spill area. s11
    (usr_time) reads ``now() - time_ref``, s10 (status) reads with the arith/div ready bits and
    port_new set, and s1 (LFSR) is not supported. Reserved: ra (CALL/RET), sp (call stack), gp (the
    last flag-updating ALU result: Z = gp == 0, S = gp < 0), s0 (time_ref), s1 (state base), t0-t3
    (scratch).

Control flow
    ``-if()`` tests the flags the previous instruction left and gates that instruction's register,
    flag, data-memory and branch effects (qcore_cpu.sv id_exec_ok). The internal flag F is set by
    FLAG. ``JUMP`` to itself with no condition (asm_v2's ``end()``) ends the program. CALL/RET use
    the RISC-V stack, so calls nest.

Timing
    Timed port writes fire at ``time_ref + t``, t from ``@t`` or s14 (out_usr_time); ``TIME
    inc_ref/set_ref`` move time_ref, which lives in s0 and starts at ``now() + lead``. ``WAIT time
    @t`` halts on RISC-Q's timeCmp until ``time_ref + t - WAIT_TIME_OFFSET``, as the assembler's
    expansion does. Times pass through unscaled: tProc cycles become RISC-Q timer ticks.

Outputs
    Wave ports (WPORT_WR, WMEM_WR -wp) need a :class:`Channel` in ``Target.wave_ports``; trigger
    ports (TRIG) and data ports (DPORT_WR) need one in ``Target.trig_ports``/``Target.data_ports``.
    No values are converted: frequency, phase, gain, envelope-address, length and time codes computed
    for QICK hardware must be regenerated for RISC-Q before the translated program means the same
    thing. The wave's conf word (mode/outsel/phrst) is not used.
"""
from __future__ import annotations
import importlib.util
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List

try:
    from .tprocv2_assembler import Alias_List, Assembler
except ImportError:     # loaded by path (the qick package pulls in numpy/pynq)
    _spec = importlib.util.spec_from_file_location(
        "_qick_tprocv2_assembler", os.path.join(os.path.dirname(__file__), "tprocv2_assembler.py"))
    _asm = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_asm)
    Alias_List, Assembler = _asm.Alias_List, _asm.Assembler

# RISC-Q core-local memory map; mirrors risc-q/software/riscq/map.py (SocMap, LEAD).

MEM_BASE = 0x80000000
CTRL_TIME_CMP = 0x4000
CTRL_WAIT_TIME_CMP = 0x4008 # read halts until time + 3 >= timeCmp
CTRL_RES = 0x4200 #read halts until the readout integral settles
CTRL_REAL = 0x4204
CTRL_IMAG = 0x4208
CTRL_TIME = 0xBFF8
RF_GATE = 0x10000
RF_READOUT = 0x20000
RF_DEMOD = 0x30000
RF_FIRE = 0x0
RF_FREQ = 0x4
RF_DC_OFFSET = 0x8
RF_PHASE_OFFSET = 0xC
RF_SLOT_STRIDE = 0x10
RF_START_TIME = 0x4100
LEAD = 96
RQ_DONE = 0xD04E0000
RQ_MAGIC = 0x52515121

# tProc v2 constants
WAIT_TIME_OFFSET = Assembler.WAIT_TIME_OFFSET
STATUS_READY = 0x800F       # s10: arith_rdy | arith_new | div_rdy | div_new | port_new
WMEM_STRIDE = 32            # bytes per wave memory entry: w0..w5 plus two pad words (Waveform.compile)


class TranslateError(ValueError):
    """The tProc program can't be translated as written."""


@dataclass(frozen=True)
class Channel:
    """Where a tProc output port lands on RISC-Q.

    kind="pulse": a wave-port write loads the 6-word wave {freq, phase, env, gain, length, conf} into
    `slot` of the RISC-Q channel at `base` and fires it at the scheduled time.
    kind="config": like "pulse" but only programs the slot (e.g. a readout's demod carrier, fired
    later by a trigger).
    kind="trigger": on a trigger/data port, `slot` fires when the port is raised (TRIG set, or a
    nonzero DPORT_WR value); clearing writes don't fire.
    kind="none": the port has no RISC-Q counterpart (a PMOD pin, a DDR4 buffer trigger) and writes
    to it are dropped; `base` and `slot` are unused.
    """
    base: int
    slot: int = 0
    kind: str = "pulse"


@dataclass
class Target:
    """Translation settings for one RISC-Q build."""
    wave_ports: Dict[int, Channel] = field(default_factory=dict)
    trig_ports: Dict[int, Channel] = field(default_factory=dict)
    data_ports: Dict[int, Channel] = field(default_factory=dict)
    lead: int = LEAD            # ticks between program start and time_ref = 0
    dmem_words: int = 256       # tProc data memory; a power of two, addresses wrap like the RTL
    wmem_entries: int = 0       # wave memory entries; 0 sizes it to the program
    has_mul: bool = False       # RiscqParam.withMul; without it ARITH becomes a shift-add loop


# ---------------------------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------------------------

@dataclass
class ProgramV2:
    """A tProc v2 program: assembler instruction dicts, label addresses and memory images."""
    insts: List[dict]
    labels: Dict[str, int]
    wmem: List[List[int]]
    dmem: List[int]


_REG_RE = re.compile(r"([rsw])(\d+)")
_REG_MAX = {"s": 15, "r": 31, "w": 5}
_LIT_RE = re.compile(r"([#&@])([ubh]?)(-?[0-9A-Fa-f_]+)")
_NO_WRITE = {"s0", "s1", "s10", "s11"}      # zero, LFSR, status, usr_time: never allocated
_WAVE_REGS = ["w%d" % i for i in range(6)]
# keys whose values name registers (DST of port writes is a port number instead)
_REG_KEYS = ("DST", "OP", "WR", "ADDR", "DATA", "R1", "R2", "R3", "R4", "NUM", "DEN")
_PORT_CMDS = {"WPORT_WR", "DPORT_WR", "DPORT_RD", "TRIG"}


def _lit(tok, where):
    """Value of an assembler literal: #n, #un, #bn, #hn, &n (address) or @n (time)."""
    m = _LIT_RE.fullmatch(tok.strip())
    if not m:
        raise TranslateError("%s: bad literal %r" % (where, tok))
    base = {"b": 2, "h": 16}.get(m.group(2), 10)
    try:
        return int(m.group(3).replace("_", ""), base)
    except ValueError:
        raise TranslateError("%s: bad literal %r" % (where, tok))


def _reg(tok, where):
    """Canonical register name ('r3', 's14', 'w0') of a register token or alias."""
    tok = tok.strip()
    tok = Alias_List.get(tok, tok)
    m = _REG_RE.fullmatch(tok)
    if not m or int(m.group(2)) > _REG_MAX[m.group(1)]:
        raise TranslateError("%s: %r is not a tProc v2 register" % (where, tok))
    return m.group(1) + str(int(m.group(2)))


def _is_lit(tok):
    return tok.strip()[:1] in "#&@"


def _where(c):
    return "line %s (%s)" % (c.get("LINE", "?"), c["CMD"])


def _regs_in(c):
    """The registers an instruction names, plus the ones it reads or writes implicitly."""
    out = []
    for k in _REG_KEYS:
        if k in c and not (k == "DST" and c["CMD"] in _PORT_CMDS):
            for tok in re.findall(r"[A-Za-z_]\w*", str(c[k])):
                tok = Alias_List.get(tok, tok)
                if tok == "r_wave":
                    out += _WAVE_REGS
                elif _REG_RE.fullmatch(tok):
                    out.append(_reg(tok, _where(c)))
    cmd = c["CMD"]
    if cmd == "ARITH":
        out.append("s3")
    elif cmd == "DIV":
        out += ["s4", "s5"]
    elif cmd == "DPORT_RD":
        out += ["s8", "s9"]
    elif cmd in ("JUMP", "CALL") and c.get("ADDR") == "s15":
        out.append("s15")
    if (cmd in ("WPORT_WR", "DPORT_WR", "TRIG") or "WP" in c) and "TIME" not in c:
        out.append("s14")
    if cmd == "WMEM_WR" or c.get("SRC") == "r_wave" or "WP" in c:
        out += _WAVE_REGS
    return out


def parse(program, wmem=None, dmem=None):
    """Read a tProc v2 program into a :class:`ProgramV2`.

    `program` is a QickProgramV2 (compiled if needed), tProc v2 assembly text, or a
    ``(prog_list, labels)`` pair. `wmem` (a list of 6- or 8-word waves) and `dmem` (a list of words)
    give the initial wave/data memory; a QickProgramV2 supplies its own unless they're passed.
    """
    if hasattr(program, "prog_list"):
        if getattr(program, "binprog", None) is None:
            program.compile()
        plist, labels = program.prog_list, program.labels
        binprog = program.binprog or {}
        if wmem is None:
            wmem = binprog.get("wmem")
        if dmem is None:
            dmem = binprog.get("dmem")
    elif isinstance(program, str):
        try:
            plist, labels = Assembler.str_asm2list(program)
        except RuntimeError as e:
            raise TranslateError("tProc v2 assembler: %s" % e) from None
    else:
        plist, labels = program
    insts, addr = [], 0
    for c in plist:
        c = dict(c)
        if "CMD" not in c:
            raise TranslateError("instruction without CMD: %r" % (c,))
        c.setdefault("P_ADDR", addr)
        addr = c["P_ADDR"] + (2 if c["CMD"] == "WAIT" else 1)
        insts.append(c)
    lab = {}
    for name, v in labels.items():
        m = re.fullmatch(r"&(\d+)", str(v))
        lab[name] = int(m.group(1)) if m else int(v)
    return ProgramV2(insts, lab, [list(w) for w in (wmem or [])], list(dmem or []))


# ---------------------------------------------------------------------------------------------
# RV32I instructions, encoding and rendering
# ---------------------------------------------------------------------------------------------

ABI = ["zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2", "s0", "s1",
       "a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7",
       "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10", "s11",
       "t3", "t4", "t5", "t6"]
ZERO, RA, SP, FLAGS, A0 = 0, 1, 2, 3, 10
T0, T1, T2, T3 = 5, 6, 7, 28
TREF, MBASE = 8, 9
POOL = list(range(10, 28)) + [29, 30, 31, 4]

_R_OPS = {"add": (0x00, 0), "sub": (0x20, 0), "sll": (0x00, 1), "slt": (0x00, 2),
          "sltu": (0x00, 3), "xor": (0x00, 4), "srl": (0x00, 5), "sra": (0x20, 5),
          "or": (0x00, 6), "and": (0x00, 7), "mul": (0x01, 0)}
_I_OPS = {"addi": 0, "slti": 2, "sltiu": 3, "xori": 4, "ori": 6, "andi": 7}
_SHIFT_OPS = {"slli": (0x00, 1), "srli": (0x00, 5), "srai": (0x20, 5)}
_BRANCH_OPS = {"beq": 0, "bne": 1, "blt": 4, "bge": 5, "bltu": 6, "bgeu": 7}


@dataclass
class RvInst:
    """One RV32I instruction (or `label` / `la` pseudo-op). Operand order:
    R (rd, rs1, rs2) · I/shift (rd, rs1, imm) · lw/jalr (rd, rs1, imm) · sw (rs2, rs1, imm) ·
    branch (rs1, rs2, label) · jal (rd, label) · lui/auipc (rd, imm20) · la (rd, symbol)."""
    op: str
    args: tuple
    note: str = ""

    @property
    def size(self):
        return 0 if self.op == "label" else 8 if self.op == "la" else 4


def _s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def _hilo(v):
    """Split v so that (hi << 12) + sign-extended lo == v (mod 2^32)."""
    hi = ((v + 0x800) >> 12) & 0xFFFFF
    return hi, _s32(v - (hi << 12))


def _fits12(v):
    return -2048 <= v < 2048


def _encode(inst, pc, syms):
    """Encode one instruction at `pc` into a list of 32-bit words."""
    op, a = inst.op, inst.args
    if op in _R_OPS:
        f7, f3 = _R_OPS[op]
        return [f7 << 25 | a[2] << 20 | a[1] << 15 | f3 << 12 | a[0] << 7 | 0x33]
    if op in _I_OPS or op in ("lw", "jalr"):
        opcode, f3 = {"lw": (0x03, 2), "jalr": (0x67, 0)}.get(op, (0x13, _I_OPS.get(op)))
        if not _fits12(a[2]):
            raise TranslateError("%s immediate %d out of range" % (op, a[2]))
        return [(a[2] & 0xFFF) << 20 | a[1] << 15 | f3 << 12 | a[0] << 7 | opcode]
    if op in _SHIFT_OPS:
        f7, f3 = _SHIFT_OPS[op]
        return [f7 << 25 | (a[2] & 31) << 20 | a[1] << 15 | f3 << 12 | a[0] << 7 | 0x13]
    if op == "sw":
        if not _fits12(a[2]):
            raise TranslateError("sw offset %d out of range" % a[2])
        imm = a[2] & 0xFFF
        return [(imm >> 5) << 25 | a[0] << 20 | a[1] << 15 | 2 << 12 | (imm & 31) << 7 | 0x23]
    if op in _BRANCH_OPS:
        off = syms[a[2]] - pc
        if not -4096 <= off < 4096:
            raise TranslateError("branch to %s out of range" % a[2])
        return [((off >> 12) & 1) << 31 | ((off >> 5) & 0x3F) << 25 | a[1] << 20 | a[0] << 15
                | _BRANCH_OPS[op] << 12 | ((off >> 1) & 0xF) << 8 | ((off >> 11) & 1) << 7 | 0x63]
    if op == "jal":
        off = syms[a[1]] - pc
        if not -(1 << 20) <= off < 1 << 20:
            raise TranslateError("jump to %s out of range" % a[1])
        return [((off >> 20) & 1) << 31 | ((off >> 1) & 0x3FF) << 21 | ((off >> 11) & 1) << 20
                | ((off >> 12) & 0xFF) << 12 | a[0] << 7 | 0x6F]
    if op in ("lui", "auipc"):
        return [(a[1] & 0xFFFFF) << 12 | a[0] << 7 | (0x37 if op == "lui" else 0x17)]
    if op == "la":
        hi, lo = _hilo(syms[a[1]] - pc)
        return [hi << 12 | a[0] << 7 | 0x17, (lo & 0xFFF) << 20 | a[0] << 15 | a[0] << 7 | 0x13]
    raise TranslateError("can't encode %s" % op)


def _render(inst):
    op, a = inst.op, inst.args
    r = ABI.__getitem__
    if op in _R_OPS:
        return "%s %s, %s, %s" % (op, r(a[0]), r(a[1]), r(a[2]))
    if op in _I_OPS or op in _SHIFT_OPS:
        return "%s %s, %s, %d" % (op, r(a[0]), r(a[1]), a[2])
    if op in ("lw", "jalr"):
        return "%s %s, %d(%s)" % (op, r(a[0]), a[2], r(a[1]))
    if op == "sw":
        return "sw %s, %d(%s)" % (r(a[0]), a[2], r(a[1]))
    if op in _BRANCH_OPS:
        return "%s %s, %s, %s" % (op, r(a[0]), r(a[1]), a[2])
    if op == "jal":
        return "jal %s, %s" % (r(a[0]), a[1])
    if op in ("lui", "auipc"):
        return "%s %s, 0x%x" % (op, r(a[0]), a[1])
    if op == "la":
        return "la %s, %s" % (r(a[0]), a[1])
    raise TranslateError("can't render %s" % op)


# ---------------------------------------------------------------------------------------------
# Lowering
# ---------------------------------------------------------------------------------------------

# -if(cond): branch that skips the instruction when the condition is FALSE -> (op, rs1, rs2)
_COND_SKIP = {"Z": ("bne", FLAGS, ZERO), "NZ": ("beq", FLAGS, ZERO),
              "S": ("bge", FLAGS, ZERO), "NS": ("blt", FLAGS, ZERO)}
_ALU_R = {"+": "add", "-": "sub", "AND": "and", "&": "and", "MSK": "and", "OR": "or", "|": "or",
          "XOR": "xor", "^": "xor"}
_ALU_I = {"+": "addi", "AND": "andi", "&": "andi", "MSK": "andi", "OR": "ori", "|": "ori",
          "XOR": "xori", "^": "xori"}
_ALU_SHIFT = {"ASR": ("srai", "sra"), "SL": ("slli", "sll"), "<<": ("slli", "sll"),
              "SR": ("srli", "srl"), ">>": ("srli", "srl")}
_ALU_ONE = {"ABS", "MSH", "LSH", "SWP", "PAR", "NOT", "!"}
_ARITH = {  # op -> (operand roles in R1..R4 order, D sign, C sign); result = (D +- A) * B +- C
    "T": ("AB", 0, 0), "TP": ("ABC", 0, 1), "TM": ("ABC", 0, -1),
    "PT": ("DAB", 1, 0), "PTP": ("DABC", 1, 1), "PTM": ("DABC", 1, -1),
    "MT": ("DAB", -1, 0), "MTP": ("DABC", -1, 1), "MTM": ("DABC", -1, -1)}
_UNSUPPORTED = {"NET": "QNET", "COM": "QCOM", "PA": "custom peripheral A",
                "PB": "custom peripheral B"}

# words at the start of the state area (s1 points here)
_ST_TIME_BASE = 0       # time_ref when absolute tProc time was 0
_ST_FLAG = 4            # the internal flag F
_ST_WORDS = 2


def _pow2(n):
    p = 1
    while p < n:
        p <<= 1
    return p


class _Lowering:
    def __init__(self, prog, target, standalone):
        t = target
        if t.dmem_words < 1 or t.dmem_words & (t.dmem_words - 1):
            raise TranslateError("dmem_words must be a power of two")
        if not 0 <= t.lead < 2048:
            raise TranslateError("lead must be in 0..2047")
        if len(prog.dmem) > t.dmem_words:
            raise TranslateError("initial data memory has %d words but dmem_words is %d"
                                 % (len(prog.dmem), t.dmem_words))
        self.prog, self.insts, self.target, self.standalone = prog, prog.insts, target, standalone
        self.out = []
        self._note = ""
        self._uid = 0
        self.by_addr = {c["P_ADDR"]: c for c in self.insts}
        self.end_addr = max([c["P_ADDR"] + (2 if c["CMD"] == "WAIT" else 1) for c in self.insts]
                            + [0])
        self._size_wmem()
        self._collect_targets()
        self._allocate()

    # -- layout --
    def _size_wmem(self):
        n = max(self.target.wmem_entries, len(self.prog.wmem))
        for c in self.insts:
            if c["CMD"] in ("WMEM_WR", "WPORT_WR") or c.get("SRC") == "wmem":
                text = c.get("DST" if c["CMD"] == "WMEM_WR" else "ADDR", "")
                for m in re.finditer(r"&(\d+)", text):
                    n = max(n, int(m.group(1)) + 1)
        self.wmem_entries = _pow2(n) if n else 0

    # -- control-flow targets --
    def resolve(self, c, label=None, addr=None):
        """tProc program address a JUMP/CALL/REG_WR label refers to, snapped to an instruction."""
        p = c["P_ADDR"]
        if label is not None:
            rel = {"PREV": -1, "HERE": 0, "NEXT": 1, "SKIP": 2}
            if label in rel:
                n = p + rel[label]
            elif label in self.prog.labels:
                n = self.prog.labels[label]
            else:
                raise TranslateError("%s: undefined label %s" % (_where(c), label))
        else:
            n = _lit(addr, _where(c))
        if n in self.by_addr or n >= self.end_addr:
            return min(n, self.end_addr)
        if self.by_addr.get(n - 1, {}).get("CMD") == "WAIT":
            return n - 1        # into the middle of WAIT's test/jump pair: re-run the wait
        raise TranslateError("%s: address %d is not an instruction" % (_where(c), n))

    def static_target(self, c):
        """The address a JUMP/CALL/REG_WR-label names at translate time, or None for s15."""
        if "LABEL" in c:
            return self.resolve(c, label=c["LABEL"])
        if c.get("ADDR", "s15") != "s15":
            return self.resolve(c, addr=c["ADDR"])
        return None

    def _collect_targets(self):
        self.branch_targets, self.targets = set(), set()
        for c in self.insts:
            if c["CMD"] in ("JUMP", "CALL") or (c["CMD"] == "REG_WR" and c.get("SRC") == "label"):
                n = self.static_target(c)
                if n is not None:
                    self.targets.add(n)
                    if c["CMD"] != "REG_WR":
                        self.branch_targets.add(n)

    # -- register allocation --
    def _allocate(self):
        uses, first = Counter(), {}
        for c in self.insts:
            for key in _regs_in(c):
                if key not in _NO_WRITE:
                    uses[key] += 1
                    first.setdefault(key, len(first))
        ranked = sorted(uses, key=lambda k: (-uses[k], first[k]))
        self.reg = dict(zip(ranked, POOL))
        self.spill = {k: _ST_WORDS + i for i, k in enumerate(ranked[len(POOL):])}
        self.dmem_off = 4 * (_ST_WORDS + len(self.spill))
        self.wmem_off = self.dmem_off + 4 * self.target.dmem_words

    def reg_map(self):
        """{tProc register: location} for every tProc register the program uses."""
        m = {k: ABI[x] for k, x in self.reg.items()}
        m.update({k: "__qick_state+%d" % (4 * i) for k, i in self.spill.items()})
        return m

    def src(self, key, scratch):
        """RISC-V register holding tProc register `key`, loading/computing into `scratch`."""
        if key == "s0":
            return ZERO
        if key == "s10":
            self.li(scratch, STATUS_READY)
            return scratch
        if key == "s11":        # usr_time = abs time - time_ref = now - time_ref here
            self.mmio_lw(scratch, CTRL_TIME)
            self.emit("sub", scratch, scratch, TREF)
            return scratch
        if key == "s1":
            raise TranslateError("s1 (the LFSR) has no RISC-Q equivalent")
        if key in self.reg:
            return self.reg[key]
        self.emit("lw", scratch, MBASE, 4 * self.spill[key])
        return scratch

    def dst(self, key):
        """Register to compute tProc register `key` into; follow with commit()."""
        return self.reg.get(key, T0)

    def commit(self, key):
        if key in self.spill:
            self.emit("sw", T0, MBASE, 4 * self.spill[key])

    def store(self, key, x):
        """tProc register `key` = RISC-V register x."""
        if key in self.reg:
            if self.reg[key] != x:
                self.emit("addi", self.reg[key], x, 0)
        elif key in self.spill:
            self.emit("sw", x, MBASE, 4 * self.spill[key])

    # -- emission helpers --
    def emit(self, op, *args):
        self.out.append(RvInst(op, args, self._note))
        self._note = ""

    def label(self, name):
        self.out.append(RvInst("label", (name,)))

    def fresh(self):
        self._uid += 1
        return ".Lt%d" % self._uid

    def li(self, rd, v):
        v = _s32(v)
        if _fits12(v):
            self.emit("addi", rd, ZERO, v)
            return
        hi, lo = _hilo(v)
        self.emit("lui", rd, hi)
        if lo:
            self.emit("addi", rd, rd, lo)

    def addi(self, rd, rs, v):
        """rd = rs + v for any 32-bit v (uses T1 when v doesn't fit 12 bits)."""
        v = _s32(v)
        if _fits12(v):
            self.emit("addi", rd, rs, v)
        else:
            self.li(T1, v)
            self.emit("add", rd, rs, T1)

    def mmio_sw(self, val, addr):
        hi, lo = _hilo(addr)
        base = ZERO
        if hi:
            self.emit("lui", T3, hi)
            base = T3
        self.emit("sw", val, base, lo)

    def mmio_lw(self, rd, addr):
        hi, lo = _hilo(addr)
        base = ZERO
        if hi:
            self.emit("lui", T3, hi)
            base = T3
        self.emit("lw", rd, base, lo)

    def mul(self, rd, a, b):
        """rd = a * b (low 32 bits). Without the M extension: shift-and-add over t0-t3."""
        if self.target.has_mul:
            self.emit("mul", rd, a, b)
            return
        loop, skip, done = self.fresh(), self.fresh(), self.fresh()
        self.emit("addi", T2, a, 0)
        self.emit("addi", T3, b, 0)
        self.emit("addi", T0, ZERO, 0)
        self.label(loop)
        self.emit("beq", T3, ZERO, done)
        self.emit("andi", T1, T3, 1)
        self.emit("beq", T1, ZERO, skip)
        self.emit("add", T0, T0, T2)
        self.label(skip)
        self.emit("slli", T2, T2, 1)
        self.emit("srli", T3, T3, 1)
        self.emit("jal", ZERO, loop)
        self.label(done)
        if rd != T0:
            self.emit("addi", rd, T0, 0)

    def sext(self, rd, rs, bits):
        self.emit("slli", rd, rs, 32 - bits)
        self.emit("srai", rd, rd, 32 - bits)

    def state_ptr(self, rd, off):
        """rd = s1 + off; returns (base, imm) addressing that word."""
        if _fits12(off):
            return MBASE, off
        self.li(rd, off)
        self.emit("add", rd, rd, MBASE)
        return rd, 0

    # -- operands --
    def operand(self, tok, scratch, where):
        """RISC-V register holding an ALU operand (register or #literal)."""
        tok = Alias_List.get(tok, tok)
        if _is_lit(tok):
            self.li(scratch, _lit(tok, where))
            return scratch
        return self.src(_reg(tok, where), scratch)

    def eval_op(self, c, rd):
        """rd = the value of the instruction's -op(); rd may equal a source."""
        where = _where(c)
        toks = c["OP"].split()
        if len(toks) == 1:
            x = self.operand(toks[0], T0, where)
            if x != rd:
                self.emit("addi", rd, x, 0)
            return
        if len(toks) == 2:
            op, a_tok, b_tok = toks[0], toks[1], toks[1]
            if op not in _ALU_ONE:
                raise TranslateError("%s: unknown one-operand ALU operation %s" % (where, op))
        elif len(toks) == 3:
            a_tok, op, b_tok = toks
        else:
            raise TranslateError("%s: can't parse -op(%s)" % (where, c["OP"]))
        a = self.operand(a_tok, T0, where)
        imm = _lit(b_tok, where) if _is_lit(b_tok) else None
        if op in _ALU_SHIFT:
            if imm is not None:
                self.emit(_ALU_SHIFT[op][0], rd, a, imm & 15)
            else:
                self.emit("andi", T1, self.operand(b_tok, T1, where), 15)
                self.emit(_ALU_SHIFT[op][1], rd, a, T1)
        elif op in _ALU_R and imm is not None and op != "-" and _fits12(imm):
            self.emit(_ALU_I[op], rd, a, imm)
        elif op == "-" and imm is not None and _fits12(-imm):
            self.emit("addi", rd, a, -imm)
        elif op in _ALU_R:
            self.emit(_ALU_R[op], rd, a, self.operand(b_tok, T1, where))
        elif op == "ABS":       # |B|
            b = self.operand(b_tok, T1, where)
            self.emit("srai", T2, b, 31)
            self.emit("xor", T1, b, T2)
            self.emit("sub", rd, T1, T2)
        elif op == "MSH":
            self.emit("srli", rd, a, 16)
        elif op == "LSH":
            self.emit("slli", T2, a, 16)
            self.emit("srli", rd, T2, 16)
        elif op == "SWP":
            self.emit("slli", T2, a, 16)
            self.emit("srli", T1, a, 16)
            self.emit("or", rd, T2, T1)
        elif op in ("NOT", "!"):
            self.emit("xori", rd, a, -1)
        elif op in ("CAT", "::"):
            b = self.operand(b_tok, T1, where)
            self.emit("slli", T2, a, 16)
            self.emit("slli", T1, b, 16)
            self.emit("srli", T1, T1, 16)
            self.emit("or", rd, T2, T1)
        elif op == "PAR":
            self.emit("srli", T2, a, 16)
            self.emit("xor", T2, T2, a)
            for sh in (8, 4, 2, 1):
                self.emit("srli", T1, T2, sh)
                self.emit("xor", T2, T2, T1)
            self.emit("andi", rd, T2, 1)
        elif op == "RFU":
            self.emit("addi", rd, ZERO, 0)
        else:
            raise TranslateError("%s: unknown ALU operation %s" % (where, op))

    def cond_skip(self, c):
        """Branch over the instruction when its -if() is false; returns the label to place."""
        cond = c.get("IF", "1")
        if cond == "1":
            return None
        skip = self.fresh()
        if cond in _COND_SKIP:
            br, a, b = _COND_SKIP[cond]
            self.emit(br, a, b, skip)
        elif cond in ("F", "NF"):
            self.emit("lw", T0, MBASE, _ST_FLAG)
            self.emit("beq" if cond == "F" else "bne", T0, ZERO, skip)
        elif cond == "0":
            self.emit("jal", ZERO, skip)
        else:
            raise TranslateError("%s: unknown condition -if(%s)" % (_where(c), cond))
        return skip

    def end_cond(self, skip):
        if skip:
            self.label(skip)

    def dual_write(self, c):
        """The -wr(reg op|imm) register write and -uf flag update most instructions can carry."""
        where = _where(c)
        if "WR" in c:
            toks = c["WR"].split()
            if len(toks) != 2 or toks[1] not in ("op", "imm"):
                raise TranslateError("%s: bad -wr(%s)" % (where, c["WR"]))
            key = _reg(toks[0], where)
            d = self.dst(key)
            if toks[1] == "op":
                self.eval_op(c, d)
            else:
                self.li(d, _lit(c["LIT"], where))
            self.commit(key)
            if c.get("UF") == "1":
                self.emit("addi", FLAGS, d, 0)
        elif c.get("UF") == "1" and "OP" in c:
            self.eval_op(c, FLAGS)

    def mem_index(self, c, text):
        """(registers, constant) of a memory address: &n, rX, &rX, rX + &n, rX + rY."""
        regs, const = [], 0
        for term in text.strip().strip("[]").split("+"):
            term = term.strip()
            if re.fullmatch(r"&-?\d+", term):
                const += int(term[1:])
            else:
                regs.append(_reg(term.lstrip("&"), _where(c)))
        return regs, const

    def dmem_ref(self, c, text):
        """(base, imm) addressing data-memory word `text`; register addresses wrap like the RTL."""
        regs, const = self.mem_index(c, text)
        if not regs:
            if not 0 <= const < self.target.dmem_words:
                raise TranslateError("%s: address %d outside the %d-word data memory"
                                     % (_where(c), const, self.target.dmem_words))
            return self.state_ptr(T1, self.dmem_off + 4 * const)
        self.sum_regs(regs, const, T1)
        self.emit("andi", T1, T1, self.target.dmem_words - 1)
        self.emit("slli", T1, T1, 2)
        self.emit("add", T1, T1, MBASE)
        if _fits12(self.dmem_off):
            return T1, self.dmem_off
        self.li(T2, self.dmem_off)
        self.emit("add", T1, T1, T2)
        return T1, 0

    def wmem_ref(self, c, text):
        """T1 = address of wave-memory entry `text`."""
        regs, const = self.mem_index(c, text)
        if not self.wmem_entries:
            raise TranslateError("%s: the program has no wave memory; set Target.wmem_entries"
                                 % _where(c))
        if not regs:
            base, imm = self.state_ptr(T1, self.wmem_off + WMEM_STRIDE * const)
            if base != T1:
                self.emit("addi", T1, base, imm)
            return
        self.sum_regs(regs, const, T1)
        self.emit("andi", T1, T1, self.wmem_entries - 1)
        self.emit("slli", T1, T1, 5)
        self.emit("add", T1, T1, MBASE)
        if _fits12(self.wmem_off):
            self.emit("addi", T1, T1, self.wmem_off)
        else:
            self.li(T2, self.wmem_off)
            self.emit("add", T1, T1, T2)

    def sum_regs(self, regs, const, rd):
        self.emit("addi", rd, self.src(regs[0], rd), 0)
        for r in regs[1:]:
            self.emit("add", rd, rd, self.src(r, T2))
        if const:
            self.emit("addi", rd, rd, const)

    # -- outputs --
    def port(self, c, table, what):
        n = int(c["DST"] if c["CMD"] in _PORT_CMDS else c["PORT"])
        if n not in table:
            raise TranslateError("%s: tProc %s port %d has no RISC-Q Channel in Target.%s"
                                 % (_where(c), what, n, {"wave": "wave_ports",
                                    "trigger": "trig_ports", "data": "data_ports"}[what]))
        return table[n]

    def port_time(self, c):
        """T0 = time_ref + (@t or s14)."""
        if "TIME" in c:
            self.addi(T0, TREF, _lit(c["TIME"], _where(c)))
        else:
            self.emit("add", T0, TREF, self.src("s14", T0))

    def fire(self, chan):
        """Schedule `chan.slot` at the time in T0."""
        if chan.kind == "none":
            return
        self.mmio_sw(T0, chan.base + RF_START_TIME)
        if chan.kind != "config":
            self.emit("addi", T0, ZERO, chan.slot)
            self.mmio_sw(T0, chan.base + RF_FIRE)

    def wave_out(self, c, chan, from_wmem):
        """Program `chan` from a wave (wmem entry c['ADDR'] or w0-w5) and fire it at port_time."""
        if chan.kind == "none":
            return
        if chan.kind not in ("pulse", "config"):
            raise TranslateError("%s: a wave port needs a Channel of kind 'pulse', 'config' or "
                                 "'none'" % _where(c))
        slot = chan.base + (chan.slot + 1) * RF_SLOT_STRIDE
        self.port_time(c)
        self.mmio_sw(T0, chan.base + RF_START_TIME)         # freq is scheduled against it
        if from_wmem:
            self.wmem_ref(c, c["ADDR"])
        # (wave register, RISC-Q address, transform); w5 (conf) has no RISC-Q equivalent
        for w, addr, how in ((0, chan.base + RF_FREQ, None),   # 32-bit code: top 16 bits used
                             (1, slot + 0x0, None),             # phase: top 16 bits used
                             (3, slot + 0x4, "gain"),           # 16-bit gain -> data[31:16]
                             (2, slot + 0x8, None),             # envelope address
                             (4, slot + 0xC, "length")):        # length[15:0]
            if from_wmem:
                self.emit("lw", T0, T1, 4 * w)
                x = T0
            else:
                x = self.src("w%d" % w, T0)
            if how == "gain":
                self.emit("slli", T0, x, 16)
                x = T0
            elif how == "length":
                self.emit("slli", T0, x, 16)
                self.emit("srli", T0, T0, 16)
                x = T0
            self.mmio_sw(x, addr)
        if chan.kind == "pulse":
            self.emit("addi", T0, ZERO, chan.slot)
            self.mmio_sw(T0, chan.base + RF_FIRE)

    def wave_regs_to_wmem(self, c, text):
        self.wmem_ref(c, text)
        for i, w in enumerate(_WAVE_REGS):
            self.emit("sw", self.src(w, T0), T1, 4 * i)

    # -- program --
    def run(self):
        if self.standalone:
            self.emit("la", SP, "__stack_top")
            self.emit("la", T0, "__rq_status")
            self.emit("addi", T1, ZERO, 1)            # RUNNING
            self.emit("sw", T1, T0, 0)
        self.emit("la", MBASE, "__qick_state")
        self.emit("addi", FLAGS, ZERO, 0)
        self.mmio_lw(T0, CTRL_TIME)
        self.emit("addi", TREF, T0, self.target.lead)
        self.emit("sw", TREF, MBASE, _ST_TIME_BASE)
        chans = list(self.target.wave_ports.values()) + list(self.target.trig_ports.values()) \
            + list(self.target.data_ports.values())
        for base in sorted({ch.base for ch in chans if ch.kind in ("pulse", "config")}):
            # init_pulse_params: these live registers are never reset, so clear stale state
            self.mmio_sw(T0, base + RF_START_TIME)
            self.mmio_sw(ZERO, base + RF_PHASE_OFFSET)
            self.mmio_sw(ZERO, base + RF_DC_OFFSET)
        self.s15 = None     # program address s15 holds, when known at translate time
        for c in self.insts:
            p = c["P_ADDR"]
            here = [n for n in (p, p + 1) if n in self.targets and (n == p or c["CMD"] == "WAIT")]
            for n in here:
                self.label(".Lq%d" % n)
                # a label only REG_WR s15 names is reached through s15 == n, so s15 stays known
                # when fall-through agrees; a JUMP/CALL target can arrive with any s15
                if n in self.branch_targets or self.s15 != n:
                    self.s15 = None
            self._note = "%d: %s" % (p, self._text(c))
            cmd = c["CMD"]
            if cmd in _UNSUPPORTED:
                raise TranslateError("%s: %s instructions have no RISC-Q equivalent"
                                     % (_where(c), _UNSUPPORTED[cmd]))
            handler = getattr(self, "_" + cmd.lower(), None)
            if handler is None:
                raise TranslateError("%s: unknown tProc v2 instruction" % _where(c))
            handler(c)
        if self.end_addr in self.targets:
            self.label(".Lq%d" % self.end_addr)
        self._note = "end of program"
        self.label(".Lqick_end")
        if self.standalone:
            self.emit("la", T0, "__rq_status")
            self.emit("lui", T1, RQ_DONE >> 12)
            self.emit("sw", T1, T0, 0)
            self.label(".Lpark")
            self.emit("jal", ZERO, ".Lpark")
        else:
            self.emit("addi", A0, ZERO, 0)            # main returns 0
            self.emit("jalr", ZERO, RA, 0)
        return self.out

    @staticmethod
    def _text(c):
        """The instruction as assembly (the order list2asm prints fields in)."""
        parts = [c["CMD"]]
        if "DST" in c:
            parts.append("p" + c["DST"] if c["CMD"] in _PORT_CMDS else c["DST"])
        parts += [c[k] for k in ("SRC", "DATA") if k in c]
        if "LABEL" in c:
            parts.append(c["LABEL"])
        elif "ADDR" in c:
            parts.append("[%s]" % c["ADDR"])
        fmt = (("C_OP", "%s"), ("NUM", "%s"), ("DEN", "%s"), ("R1", "%s"), ("R2", "%s"),
               ("R3", "%s"), ("R4", "%s"), ("IF", "-if(%s)"), ("WR", "-wr(%s)"), ("LIT", "%s"),
               ("OP", "-op(%s)"), ("WP", "-wp(%s)"), ("PORT", "p%s"), ("TIME", "%s"))
        parts += [f % c[k] for k, f in fmt if k in c and not (k == "DEN" and "LIT" in c)]
        parts += ["-uf"] if c.get("UF") == "1" and c["CMD"] != "TEST" else []
        parts += ["-ww"] if "WW" in c else []
        return " ".join(parts)

    def jump_label(self, n):
        return ".Lqick_end" if n >= self.end_addr and n not in self.targets else ".Lq%d" % n

    @staticmethod
    def _writes_s15(c):
        dsts = [c["DST"]] if c["CMD"] == "REG_WR" else []
        dsts += [c["WR"].split()[0]] if "WR" in c else []
        return any(Alias_List.get(d, d) == "s15" for d in dsts)

    # -- instructions --
    def _nop(self, c):
        pass

    def _clear(self, c):
        pass            # clears peripheral "new data" flags; RISC-Q has none to clear

    def _test(self, c):
        skip = self.cond_skip(c)
        self.eval_op(c, FLAGS)
        if "WR" in c:
            self.dual_write(dict(c, UF="0"))
        self.end_cond(skip)

    def _reg_wr(self, c):
        where = _where(c)
        src = c["SRC"]
        if self._writes_s15(c):
            self.s15 = None
        skip = self.cond_skip(c)
        if c["DST"] == "r_wave":
            if src != "wmem":
                raise TranslateError("%s: r_wave can only be loaded from wmem" % where)
            self.wmem_ref(c, c["ADDR"])
            for i, w in enumerate(_WAVE_REGS):
                d = self.dst(w)
                self.emit("lw", d, T1, 4 * i)
                self.commit(w)
            if "WP" in c:
                self._wp(c)
            self.dual_write(c)
            self.end_cond(skip)
            return
        key = _reg(c["DST"], where)
        d = self.dst(key)
        if src == "imm":
            self.li(d, _lit(c["LIT"], where))
        elif src == "op":
            self.eval_op(c, d)
        elif src == "label":
            n = self.static_target(c)
            self.emit("la", d, ".Lq%d" % n)
            if key == "s15" and not skip:
                self.s15 = n
        elif src == "dmem":
            base, imm = self.dmem_ref(c, c["ADDR"])
            self.emit("lw", d, base, imm)
        elif src == "wmem":
            raise TranslateError("%s: wmem loads go to r_wave" % where)
        else:
            raise TranslateError("%s: unknown REG_WR source %s" % (where, src))
        self.commit(key)
        if c.get("UF") == "1":
            self.emit("addi", FLAGS, d, 0)
        self.end_cond(skip)

    def _dmem_wr(self, c):
        where = _where(c)
        skip = self.cond_skip(c)
        if c["SRC"] == "imm":
            self.li(T0, _lit(c["LIT"], where))
            x = T0
        elif c["SRC"] == "op" and len(c["OP"].split()) == 1:
            x = self.operand(c["OP"], T0, where)
        elif c["SRC"] == "op":
            self.eval_op(c, T0)
            x = T0
        else:
            raise TranslateError("%s: DMEM_WR sources are op and imm" % where)
        base, imm = self.dmem_ref(c, c["DST"])         # leaves T0 alone
        self.emit("sw", x, base, imm)
        self.dual_write(c)
        self.end_cond(skip)

    def _wmem_wr(self, c):
        self.wave_regs_to_wmem(c, c["DST"])
        if "WP" in c:
            self._wp(c)
        self.dual_write(c)

    def _wp(self, c):
        """-wp(r_wave) pX: also send the wave registers to wave port X."""
        if c["WP"].strip() != "r_wave":
            raise TranslateError("%s: only -wp(r_wave) is supported" % _where(c))
        self.wave_out(c, self.port(c, self.target.wave_ports, "wave"), from_wmem=False)

    def _wport_wr(self, c):
        chan = self.port(c, self.target.wave_ports, "wave")
        if c["SRC"] == "wmem":
            self.wave_out(c, chan, from_wmem=True)
        elif c["SRC"] == "r_wave":
            self.wave_out(c, chan, from_wmem=False)
            if "WW" in c:
                self.wave_regs_to_wmem(c, c["ADDR"])
        else:
            raise TranslateError("%s: WPORT_WR sources are wmem and r_wave" % _where(c))
        self.dual_write(c)

    def _trig(self, c):
        chan = self.port(c, self.target.trig_ports, "trigger")
        if c["SRC"] not in ("set", "clr"):
            raise TranslateError("%s: TRIG takes set or clr" % _where(c))
        if c["SRC"] == "set" and chan.kind != "none":
            self.port_time(c)
            self.fire(chan)
        self.dual_write(c)

    def _dport_wr(self, c):
        chan = self.port(c, self.target.data_ports, "data")
        if chan.kind == "none" and c["SRC"] in ("imm", "reg"):
            pass
        elif c["SRC"] == "imm":
            if int(c["DATA"]):
                self.port_time(c)
                self.fire(chan)
        elif c["SRC"] == "reg":
            skip = self.fresh()
            self.emit("beq", self.src(_reg(c["DATA"], _where(c)), T0), ZERO, skip)
            self.port_time(c)
            self.fire(chan)
            self.label(skip)
        else:
            raise TranslateError("%s: DPORT_WR sources are imm and reg" % _where(c))
        self.dual_write(c)

    def _dport_rd(self, c):
        self.mmio_lw(T0, CTRL_RES)                  # halts until the integral settles
        self.mmio_lw(T0, CTRL_REAL)
        self.store("s8", T0)
        self.mmio_lw(T0, CTRL_IMAG)
        self.store("s9", T0)

    def _jump(self, c, call=False):
        n = self.static_target(c)
        if n is None and self.s15 is not None:
            n = self.s15
        skip = self.cond_skip(c)
        self.dual_write(c)
        if self._writes_s15(c):
            self.s15 = None
        if n is not None and n == c["P_ADDR"] and not call and not skip and "WR" not in c \
                and c.get("UF") != "1":
            self.emit("jal", ZERO, ".Lqick_end")     # asm_v2 end(): JUMP HERE
        elif call:
            self.emit("addi", SP, SP, -4)
            self.emit("sw", RA, SP, 0)
            if n is not None:
                self.emit("jal", RA, self.jump_label(n))
            else:
                self.emit("jalr", RA, self.src("s15", T0), 0)
            self.emit("lw", RA, SP, 0)
            self.emit("addi", SP, SP, 4)
            self.s15 = None
        elif n is not None:
            self.emit("jal", ZERO, self.jump_label(n))
        else:
            self.emit("jalr", ZERO, self.src("s15", T0), 0)
        self.end_cond(skip)

    def _call(self, c):
        self._jump(c, call=True)

    def _ret(self, c):
        self.emit("jalr", ZERO, RA, 0)

    def _wait(self, c):
        op = c.get("C_OP")
        if op == "time":
            self.addi(T0, TREF, _lit(c["TIME"], _where(c)) - WAIT_TIME_OFFSET)
            self.mmio_sw(T0, CTRL_TIME_CMP)
            self.mmio_lw(T0, CTRL_WAIT_TIME_CMP)      # the load halts until the time is reached
        elif op == "port_dt":
            self.mmio_lw(T0, CTRL_RES)                # halts until the readout completes
        elif op in ("div_rdy", "div_dt"):
            pass                                      # DIV finishes before the next instruction
        else:
            raise TranslateError("%s: WAIT %s has no RISC-Q equivalent" % (_where(c), op))

    def _time(self, c):
        where = _where(c)
        op = c["C_OP"]
        skip = self.cond_skip(c)
        if op == "rst":             # absolute time restarts at 0 now; time_ref is kept
            self.emit("lw", T1, MBASE, _ST_TIME_BASE)
            self.emit("sub", T2, TREF, T1)
            self.mmio_lw(T0, CTRL_TIME)
            self.emit("addi", T0, T0, self.target.lead)
            self.emit("sw", T0, MBASE, _ST_TIME_BASE)
            self.emit("add", TREF, T0, T2)
            self.end_cond(skip)
            return
        if "LIT" in c:
            self.li(T0, _lit(c["LIT"], where))
            v = T0
        elif "R1" in c:
            v = self.src(_reg(c["R1"], where), T0)
        else:
            raise TranslateError("%s: TIME %s needs a value" % (where, op))
        if op == "inc_ref":
            self.emit("add", TREF, TREF, v)
        elif op == "set_ref":
            self.emit("lw", T1, MBASE, _ST_TIME_BASE)
            self.emit("add", TREF, T1, v)
        elif op == "updt":          # absolute time += v: everything scheduled moves v earlier
            self.emit("lw", T1, MBASE, _ST_TIME_BASE)
            self.emit("sub", T1, T1, v)
            self.emit("sw", T1, MBASE, _ST_TIME_BASE)
            self.emit("sub", TREF, TREF, v)
        else:
            raise TranslateError("%s: unknown TIME operation %s" % (where, op))
        self.end_cond(skip)

    def _flag(self, c):
        skip = self.cond_skip(c)
        op = c["C_OP"]
        if op == "set":
            self.emit("addi", T0, ZERO, 1)
        elif op == "clr":
            self.emit("addi", T0, ZERO, 0)
        elif op == "inv":
            self.emit("lw", T0, MBASE, _ST_FLAG)
            self.emit("xori", T0, T0, 1)
        else:
            raise TranslateError("%s: FLAG takes set, clr or inv" % _where(c))
        self.emit("sw", T0, MBASE, _ST_FLAG)
        self.end_cond(skip)

    def _arith(self, c):
        # s3 = (D +- A) * B +- C on the DSP's 27/18/32/27-bit signed inputs (low 32 bits)
        where = _where(c)
        if c.get("C_OP") not in _ARITH:
            raise TranslateError("%s: unknown ARITH operation %s" % (where, c.get("C_OP")))
        roles, dsign, csign = _ARITH[c["C_OP"]]
        regs = {}
        for i, role in enumerate(roles, 1):
            if "R%d" % i not in c:
                raise TranslateError("%s: ARITH %s needs %d registers" % (where, c["C_OP"], len(roles)))
            regs[role] = _reg(c["R%d" % i], where)
        skip = self.cond_skip(c)
        self.sext(T0, self.src(regs["A"], T0), 27)
        if dsign:
            self.sext(T1, self.src(regs["D"], T1), 27)
            self.emit("add" if dsign > 0 else "sub", T0, T1, T0)
        self.sext(T1, self.src(regs["B"], T1), 18)
        self.mul(T0, T0, T1)
        if csign:
            self.emit("add" if csign > 0 else "sub", T0, T0, self.src(regs["C"], T1))
        self.store("s3", T0)
        self.end_cond(skip)

    def _div(self, c):
        # s4 = NUM / DEN, s5 = NUM % DEN, unsigned (div_r); restoring division over t0-t3 and ra
        where = _where(c)
        skip = self.cond_skip(c)
        num = self.src(_reg(c["NUM"], where), T0)
        if num != T0:
            self.emit("addi", T0, num, 0)
        den = c["DEN"]
        if _is_lit(den):
            self.li(T1, _lit(den, where))
        else:
            d = self.src(_reg(den, where), T1)
            if d != T1:
                self.emit("addi", T1, d, 0)
        loop, keep = self.fresh(), self.fresh()
        self.emit("addi", SP, SP, -4)
        self.emit("sw", RA, SP, 0)
        self.emit("addi", T2, ZERO, 0)          # remainder
        self.emit("addi", RA, ZERO, 32)
        self.label(loop)
        self.emit("srli", T3, T0, 31)
        self.emit("slli", T2, T2, 1)
        self.emit("or", T2, T2, T3)
        self.emit("slli", T0, T0, 1)            # T0 shifts the dividend out, the quotient in
        self.emit("bltu", T2, T1, keep)
        self.emit("sub", T2, T2, T1)
        self.emit("ori", T0, T0, 1)
        self.label(keep)
        self.emit("addi", RA, RA, -1)
        self.emit("bne", RA, ZERO, loop)
        self.emit("lw", RA, SP, 0)
        self.emit("addi", SP, SP, 4)
        self.store("s4", T0)
        self.store("s5", T2)
        self.end_cond(skip)


# ---------------------------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------------------------

@dataclass
class Image:
    """A bootable RV32I image: code, run-state words, state area, data and wave memory."""
    base: int
    words: List[int]
    symbols: Dict[str, int]
    listing: str
    reg_map: Dict[str, str]

    def to_bytes(self):
        return b"".join(w.to_bytes(4, "little") for w in self.words)

    @property
    def ram_bytes(self):
        """RAM the image needs from `base`, including its stack."""
        return self.symbols["__stack_top"] - self.base


def _lower(program, target, standalone, wmem, dmem):
    prog = parse(program, wmem, dmem)
    low = _Lowering(prog, target or Target(), standalone)
    return low.run(), low


def _state_words(low):
    """Initial contents of __qick_state: control words, spill, data memory, wave memory."""
    words = [0] * (_ST_WORDS + len(low.spill))
    dmem = [v & 0xFFFFFFFF for v in low.prog.dmem]
    words += dmem + [0] * (low.target.dmem_words - len(dmem))
    for i in range(low.wmem_entries):
        w = [v & 0xFFFFFFFF for v in (low.prog.wmem[i] if i < len(low.prog.wmem) else [])][:8]
        words += w + [0] * (8 - len(w))
    return words


def to_asm(program, target=None, wmem=None, dmem=None):
    """GNU assembly defining `main`, to link with risc-q/software/fw/start.S."""
    code, low = _lower(program, target, False, wmem, dmem)
    lines = ["/* Generated by qick.riscv_translate from tProc v2 assembly -- do not edit. */",
             "/* tProc register -> RISC-V location: */"]
    lines += ["/*   %-8s %s */" % kv for kv in low.reg_map().items()]
    lines += ["", "    .text", "    .globl main", "    .type main, @function", "main:"]
    for inst in code:
        if inst.note:
            lines.append("    # %s" % inst.note)
        lines.append(inst.args[0] + ":" if inst.op == "label" else "    " + _render(inst))
    words = _state_words(low)
    lines += ["    .size main, .-main", "",
              "    /* in .data, not .bss: start.S zeroes .bss, which would wipe host-loaded memory */",
              "    .section .data", "    .align 2", "    .globl __qick_state", "__qick_state:"]
    marks = {low.dmem_off // 4: "__qick_dmem", low.wmem_off // 4: "__qick_wmem"}
    for i in range(0, len(words) + 1):
        if i in marks:
            lines += ["    .globl %s" % marks[i], "%s:" % marks[i]]
        if i < len(words):
            lines.append("    .word 0x%08x" % words[i])
    lines.append("")
    return "\n".join(lines)


def to_image(program, target=None, base=MEM_BASE, stack_bytes=1024, wmem=None, dmem=None):
    """Translate to a self-contained RV32I image loaded at `base`.

    Layout: code | __rq_status | __rq_magic | __qick_state (control words, spill) | __qick_dmem |
    __qick_wmem | stack (not stored).
    """
    code, low = _lower(program, target, True, wmem, dmem)
    syms, pc = {}, base
    for inst in code:
        if inst.op == "label":
            syms[inst.args[0]] = pc
        pc += inst.size
    syms["__rq_status"] = pc
    syms["__rq_magic"] = pc + 4
    syms["__qick_state"] = pc + 8
    syms["__qick_dmem"] = syms["__qick_state"] + low.dmem_off
    syms["__qick_wmem"] = syms["__qick_state"] + low.wmem_off
    state = _state_words(low)
    end = syms["__qick_state"] + 4 * len(state)
    syms["__stack_top"] = (end + stack_bytes + 15) & ~15

    words, listing, pc = [], [], base
    for inst in code:
        if inst.note:
            listing.append("%40s// %s" % ("", inst.note))
        if inst.op == "label":
            listing.append("%s:" % inst.args[0])
            continue
        enc = _encode(inst, pc, syms)
        listing.append("  %08x: %s  %s" % (pc, " ".join("%08x" % w for w in enc), _render(inst)))
        words += enc
        pc += 4 * len(enc)
    words += [0, RQ_MAGIC] + state
    return Image(base, words, syms, "\n".join(listing), low.reg_map())
