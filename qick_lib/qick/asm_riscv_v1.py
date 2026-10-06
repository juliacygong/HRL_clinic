"""RISC-V backend for the v1 QickProgram API: the program classes are unchanged, only the instruction list they
build (prog_list) is translated to RISC-V text and assembled instead of being packed into the old machine code."""
import logging
from collections import Counter

from . import averager_program as _avg
from .asm_v1 import QickProgram, QickRegister, QickRegisterManagerMixin  # noqa: F401
from .riscq_config import TRIGGER_PORT, PIN_PORT, READOUT_CH, asm_text, words
from .riscv_toolchain import build_image

logger = logging.getLogger(__name__)

REF, BASE, CTRL = 's11', 'gp', 't6'            # reference time, virtual-register file base, scratch
PHYS = ['s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7', 's8', 's9', 's10', 'a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7']
TMP = ['t0', 't1', 't2', 't3', 't4', 't5']
REGS_LABEL, DMEM_LABEL, EXIT_LABEL = '__qick_regs', '__qick_dmem', '__qick_exit'
N_PAGES, PAGE_SIZE, DMEM_WORDS = 8, 32, 256
SLOT = {'freq': 0x4, 'phase': 0x10, 'gain': 0x14, 'env': 0x18, 'dur': 0x1c}
START, FIRE = 0x4100, 0x0
JUMP_IF = {'>': 'blt {b}, {a}', '>=': 'bge {a}, {b}', '<': 'blt {a}, {b}', '<=': 'bge {b}, {a}', '==': 'beq {a}, {b}', '!=': 'bne {a}, {b}'}
RR = {'+': 'add', '-': 'sub', '*': 'mul', '&': 'and', '|': 'or', '^': 'xor', '<<': 'sll', '>>': 'srl'}
RI = {'+': 'addi', '&': 'andi', '|': 'ori', '^': 'xori', '<<': 'slli', '>>': 'srli'}


def fits12(v):
    return -2048 <= v < 2048


class Translator:
    """prog_list (v1 instruction dicts) -> RISC-V lines."""

    def __init__(self, prog):
        self.prog, self.out, self.n = prog, [], 0
        self.rf = prog.soccfg.equs
        use = Counter()
        for inst in prog.prog_list:
            for vr in self.vregs(inst):
                use[vr] += 1
        self.phys = dict(zip([vr for vr, _ in use.most_common(len(PHYS))], PHYS))
        self.warned = set()

    def vregs(self, inst):
        n, a = inst['name'], inst['args']
        regs = {'pushi': [(0, 1), (0, 2)], 'popi': [(0, 1)], 'mathi': [(0, 1), (0, 2)], 'bitwi': [(0, 1), (0, 2)],
                'memri': [(0, 1)], 'memwi': [(0, 1)], 'regwi': [(0, 1)], 'loopnz': [(0, 1)], 'condj': [(0, 1), (0, 3)],
                'math': [(0, 1), (0, 2), (0, 4)], 'bitw': [(0, 1), (0, 2), (0, 4)], 'memr': [(0, 1), (0, 2)],
                'memw': [(0, 1), (0, 2)], 'sync': [(0, 1)], 'seti': [(1, 2)], 'wait': [(1, 2)], 'read': [(1, 3)],
                'set': [(1, i) for i in range(2, 8)]}.get(n, [])
        return [(a[p], a[r]) for p, r in regs if a[r] != 0 and a[r] is not None]

    def emit(self, *lines):
        self.out.extend(lines)

    def label(self):
        self.n += 1
        return f'.L{self.n}'

    def src(self, page, reg, tmp):
        """register holding virtual register (page, reg), loading it into tmp if it lives in memory"""
        if reg == 0:
            return 'x0'
        if (page, reg) in self.phys:
            return self.phys[(page, reg)]
        self.emit(f'lw {tmp}, {(page * PAGE_SIZE + reg) * 4}({BASE})')
        return tmp

    def dst(self, page, reg, tmp):
        """(register to compute into, lines that write it back)"""
        if reg == 0:
            return tmp, []
        if (page, reg) in self.phys:
            return self.phys[(page, reg)], []
        return tmp, [f'sw {tmp}, {(page * PAGE_SIZE + reg) * 4}({BASE})']

    def imm(self, value, tmp):
        if value == 0:
            return 'x0'
        self.emit(f'li {tmp}, {value}')
        return tmp

    def translate(self):
        for inst in self.prog.prog_list:
            if inst['name'] == 'comment':
                continue
            if 'label' in inst:
                self.emit(f'{inst["label"]}:')
            c = inst.get('comment')
            self.emit(f'# {inst["name"]} {", ".join(map(str, inst["args"]))}' + (f'  ({c})' if c else ''))
            getattr(self, 'i_' + inst['name'])(*inst['args'])
        return self.out

    # I-type
    def i_regwi(self, p, r, imm):
        d, st = self.dst(p, r, TMP[0])
        self.emit(f'li {d}, {imm}', *st)

    def i_mathi(self, p, ra, rb, op, imm):
        b = self.src(p, rb, TMP[1])
        d, st = self.dst(p, ra, TMP[0])
        if op == '~':
            self.emit(f'xori {d}, {b}, -1', *st)
            return
        if op == '-':
            op, imm = '+', -imm
        if op in RI and fits12(imm):
            self.emit(f'{RI[op]} {d}, {b}, {imm}', *st)
        else:
            self.emit(f'{RR[op]} {d}, {b}, {self.imm(imm, TMP[2])}', *st)

    i_bitwi = i_mathi

    def i_memri(self, p, r, addr):
        d, st = self.dst(p, r, TMP[0])
        self.emit(f'la {TMP[1]}, {DMEM_LABEL}+{4 * addr}', f'lw {d}, 0({TMP[1]})', *st)

    def i_memwi(self, p, r, addr):
        a = self.src(p, r, TMP[0])
        self.emit(f'la {TMP[1]}, {DMEM_LABEL}+{4 * addr}', f'sw {a}, 0({TMP[1]})')

    def i_pushi(self, p, ra, rb, imm):
        a = self.src(p, ra, TMP[0])
        d, st = self.dst(p, rb, TMP[1])
        self.emit('addi sp, sp, -4', f'sw {a}, 0(sp)', f'li {d}, {imm}', *st)

    def i_popi(self, p, r):
        d, st = self.dst(p, r, TMP[0])
        self.emit(f'lw {d}, 0(sp)', 'addi sp, sp, 4', *st)

    def i_synci(self, t):
        if fits12(t):
            self.emit(f'addi {REF}, {REF}, {t}')
        else:
            self.emit(f'li {TMP[0]}, {t}', f'add {REF}, {REF}, {TMP[0]}')

    def i_waiti(self, ch, t):
        self.wait_until(f'li {TMP[0]}, {t}', TMP[0])

    def wait_until(self, load, reg):
        self.emit(load, f'add {TMP[0]}, {REF}, {reg}', f'li {CTRL}, RQ_CTRL_TIME_CMP',
                  f'sw {TMP[0]}, 0({CTRL})', f'lw x0, 8({CTRL})')

    # J-type
    def i_loopnz(self, p, r, label):
        a = self.src(p, r, TMP[0])
        d, st = self.dst(p, r, TMP[0])
        skip = self.label()
        self.emit(f'beqz {a}, {skip}', f'addi {d}, {a}, -1', *st, f'j {label}', f'{skip}:')

    def i_end(self):
        self.emit(f'j {EXIT_LABEL}')

    def i_condj(self, p, ra, op, rb, label):
        a, b = self.src(p, ra, TMP[0]), self.src(p, rb, TMP[1])
        self.emit(f'{JUMP_IF[op].format(a=a, b=b)}, {label}')

    # R-type
    def i_math(self, p, ra, rb, op, rc):
        b, c = self.src(p, rb, TMP[1]), self.src(p, rc, TMP[2])
        d, st = self.dst(p, ra, TMP[0])
        if op == '~':
            self.emit(f'xori {d}, {b}, -1', *st)
        else:
            self.emit(f'{RR[op]} {d}, {b}, {c}', *st)

    i_bitw = i_math

    def i_memr(self, p, ra, rb):
        b = self.src(p, rb, TMP[1])
        d, st = self.dst(p, ra, TMP[0])
        self.emit(f'slli {TMP[1]}, {b}, 2', f'la {TMP[2]}, {DMEM_LABEL}', f'add {TMP[1]}, {TMP[1]}, {TMP[2]}', f'lw {d}, 0({TMP[1]})', *st)

    def i_memw(self, p, ra, rb):
        a, b = self.src(p, ra, TMP[0]), self.src(p, rb, TMP[1])
        self.emit(f'slli {TMP[1]}, {b}, 2', f'la {TMP[2]}, {DMEM_LABEL}', f'add {TMP[1]}, {TMP[1]}, {TMP[2]}', f'sw {a}, 0({TMP[1]})')

    def i_sync(self, p, r):
        a = self.src(p, r, TMP[0])
        self.emit(f'add {REF}, {REF}, {a}')

    def i_wait(self, ch, p, r):
        a = self.src(p, r, TMP[1])
        self.wait_until(f'mv {TMP[1]}, {a}', TMP[1])

    def i_read(self, ch, p, which, r):
        d, st = self.dst(p, r, TMP[0])
        self.emit(f'li {CTRL}, RQ_CTRL_RES', f'lw x0, 0({CTRL})', f'lw {d}, {4 if which == "lower" else 8}({CTRL})', *st)

    def fire(self, base, time_reg):
        self.emit(f'add {TMP[3]}, {REF}, {time_reg}', f'li {TMP[4]}, {base}+{START}', f'sw {TMP[3]}, 0({TMP[4]})',
                  f'li {CTRL}, {base}', f'sw x0, {FIRE}({CTRL})')

    def i_set(self, ch, p, r_freq, r_phase, r_addr, r_gain, r_mode, r_t):
        base = f'RF_CH{ch}'
        self.emit(f'li {CTRL}, {base}')
        for name, r in (('freq', r_freq), ('phase', r_phase), ('gain', r_gain), ('env', r_addr)):
            self.emit(f'sw {self.src(p, r, TMP[0])}, {SLOT[name]}({CTRL})')
        m = self.src(p, r_mode, TMP[0])
        self.emit(f'slli {TMP[1]}, {m}, 16', f'srli {TMP[1]}, {TMP[1]}, 16', f'sw {TMP[1]}, {SLOT["dur"]}({CTRL})')
        self.fire(base, self.src(p, r_t, TMP[2]))

    def i_seti(self, ch, p, r, t):
        if ch == PIN_PORT:
            if 'pin' not in self.warned:
                logger.warning('RISC-Q has no digital output pins: pin triggers are dropped')
                self.warned.add('pin')
            self.emit('# digital pin output: not available on RISC-Q')
            return
        if ch != TRIGGER_PORT:
            raise RuntimeError(f'seti to output port {ch} has no RISC-Q equivalent')
        if r == 0:
            self.emit('# trigger bit cleared: nothing to do')
            return
        a = self.src(p, r, TMP[0])
        skip = self.label()
        self.emit(f'beqz {a}, {skip}')
        self.fire(f'RF_CH{READOUT_CH}', self.imm(t, TMP[2]))
        self.emit(f'{skip}:')

    def i_setb(self, *args):
        raise RuntimeError('setb has no RISC-Q equivalent')

    i_setbi = i_setb


class RiscvMixin:
    """replaces the old machine-code compile and the printable asm of a v1 program"""

    def _rv_lines(self):
        body = Translator(self).translate()
        return ['.text', '.globl main', 'main:', 'addi sp, sp, -16', 'sw ra, 12(sp)',
                f'la {BASE}, {REGS_LABEL}', f'li {CTRL}, RQ_CTRL_TIME', f'lw {REF}, 0({CTRL})',
                *body,
                f'{EXIT_LABEL}:', 'lw ra, 12(sp)', 'addi sp, sp, 16', 'li a0, 0', 'ret',
                '.section .data', '.align 2',
                *[l for lab, n in ((REGS_LABEL, N_PAGES * PAGE_SIZE * 4), (DMEM_LABEL, DMEM_WORDS * 4))
                  for l in (f'.type {lab}, @object', f'.size {lab}, {n}', f'{lab}:', f'.space {n}')]]

    def asm(self):
        return asm_text(self._rv_lines(), self.soccfg.equs)

    def compile(self, debug=False):
        self.image = build_image(self.asm(), self.soccfg.soc_map)
        self.binprog = words(self.image.data)

    def write_asm(self, path):
        with open(path, 'w') as f:
            f.write(self.asm())

    def write_bin(self, path):
        if self.binprog is None:
            self.compile()
        with open(path, 'wb') as f:
            f.write(self.image.data)

    def config_all(self, soc, load_envelopes=True, reset=False, load_mem=True):
        if self.binprog is None:
            self.compile()
        soc.load_program(self)

    def acquire(self, soc, *args, **kwargs):
        self.config_all(soc)
        return soc.no_core(self)

    acquire_decimated = acquire
    run_rounds = acquire


class AveragerProgram(RiscvMixin, _avg.AveragerProgram):
    pass


class RAveragerProgram(RiscvMixin, _avg.RAveragerProgram):
    pass


class NDAveragerProgram(RiscvMixin, _avg.NDAveragerProgram):
    pass


class RiscvQickProgram(RiscvMixin, QickProgram):
    pass
