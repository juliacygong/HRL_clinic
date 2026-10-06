from .asm_v2 import QickProgramV2, AveragerProgramV2
from .asm_v2_riscv import (RV_MACROS, RvMacro, RvAsmInst, RvWriteReg, REF_REG, CTRL_REG, CTRL_TIME,
                           EXIT_LABEL, RF_FIRE, RF_FREQ, RF_PHASE_OFFSET, RF_SLOT_STRIDE, RF_START_TIME,
                           rv_data_section)
from .riscq_config import asm_text, words
from .riscv_toolchain import build_image

STACK_FRAME = 16
LAYOUT = {'RQ_FIRE': RF_FIRE, 'RQ_FREQ': RF_FREQ, 'RQ_PHASE_OFFSET': RF_PHASE_OFFSET,
          'RQ_SLOT_STRIDE': RF_SLOT_STRIDE, 'RQ_START_TIME': RF_START_TIME}


class RvMixin:
    def _check_cfg(self):
        for name, val in LAYOUT.items():
            if self.soccfg.equs[name] != val:
                raise RuntimeError(f"{name} is {self.soccfg.equs[name]:#x}, translator assumes {val:#x}")

    def _init_instructions(self):
        super()._init_instructions()
        self.rv_lines = []

    def _add_rv(self, line):
        self.rv_lines.append(line)

    def append_macro(self, macro):
        if not isinstance(macro, RvMacro):
            if type(macro) not in RV_MACROS:
                raise RuntimeError(f"no RISC-V translation for macro {type(macro).__name__}")
            macro = RV_MACROS[type(macro)](**vars(macro))
        super().append_macro(macro)

    def asm_inst(self, inst, addr_inc=1):
        self.append_macro(RvAsmInst(inst=inst))

    def nop(self):
        self.asm_inst('nop')

    def ret(self):
        self.asm_inst('ret')

    def _init_reg(self, name, val):
        RvWriteReg(dst=name, src=val).translate(self)

    def _asm_lines(self):
        return ['.text', '.globl main', 'main:',
                f'addi sp, sp, -{STACK_FRAME}', f'sw ra, {STACK_FRAME - 4}(sp)',
                f'li {CTRL_REG}, {CTRL_TIME}', f'lw {REF_REG}, 0({CTRL_REG})',
                *self.rv_lines,
                f'{EXIT_LABEL}:', f'lw ra, {STACK_FRAME - 4}(sp)', f'addi sp, sp, {STACK_FRAME}',
                'li a0, 0', 'ret',
                *rv_data_section(self)]

    def _asm_text(self):
        return asm_text(self._asm_lines(), self.soccfg.equs)

    def _compile_prog(self):
        self.image = build_image(self._asm_text(), self.soccfg.soc_map)
        return words(self.image.data)

    def _compile_waves(self):
        return None

    def asm(self):
        if self.binprog is None:
            self.compile()
        return self._asm_text()

    def write_asm(self, path):
        with open(path, 'w') as f:
            f.write(self.asm())

    def write_bin(self, path):
        if self.binprog is None:
            self.compile()
        with open(path, 'wb') as f:
            f.write(self.image.data)


class RvProgram(RvMixin, QickProgramV2):
    pass


class RvAveragerProgram(RvMixin, AveragerProgramV2):
    pass
