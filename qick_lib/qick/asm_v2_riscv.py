from numbers import Integral

import numpy as np

from .asm_v2 import (WriteLabel, End, WriteReg, IncReg, ReadWmem, WriteWmem, ReadDmem, WriteDmem,
                     ReadInput, Jump, Call, CondJump, OpenLoop, CloseLoop, Delay, Wait, Resync,
                     Pulse, ConfigReadout, Trigger, QickRawParam)

# from riscq.map.SocMap.CTRL_*
CTRL_BASE = 0x4000            
WAIT_ADDR = 0x0
CTRL_TIME = 0xBFF8            
CTRL_RES  = 0x4200           

RF_BASES = {0: 0x10000,       
            1: 0x20000,       
            2: 0x30000}       
RF_DEMOD = RF_BASES[2]
RF_FIRE = 0x0
RF_FREQ = 0x4
RF_PHASE_OFFSET = 0xC
RF_SLOT_STRIDE = 0x10         
RF_START_TIME = 0x4100

DMEM_LABEL = "__qick_dmem"
WMEM_LABEL = "__qick_wmem"
WMEM_FIELDS = ['freq', 'phase', 'env', 'gain', 'length', 'conf']
WMEM_STRIDE = 4 * len(WMEM_FIELDS)

CTRL_REG    = "t1"            
REF_REG     = "s11"           
T_REG       = "t0"            
SCRATCH_REG = "t2"           

# tProc register -> RISC-V register
DREG_RV = ['s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7', 's8', 's9', 's10',
           'a0', 'a1', 'a2', 'a3', 'a4']                      
WREG_RV = ['a5', 'a6', 'a7', 't3', 't4', 't5']                 
SREG_RV = {'s0': 'x0',                                         
           's8': 'gp',                                         
           's9': 'tp',                                         
           's14': 't6'}                                        
OUT_REG = SREG_RV['s14']


def rv_reg(prog, name: str) -> str:
    """Translate a QICK register name or tProc address to a RISC-V register."""
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


def fits_imm12(val: int) -> bool:
    return -2048 <= val < 2048


def to_int32(val: int) -> int:
    # constrain the value to signed 32-bit (same as tProc)
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
            lines.append(f'    .word {to_int32(val)}    # {wave.name}.{f}')
    lines += [f'{DMEM_LABEL}:', f'    .space {4*dmem_words}']
    return lines


# wait ch, p, $r
WAIT_RV = ['sw {r}, {addr}({ctrl_base})',
           'lw x0, {addr_cmp}({ctrl_base})']


def wait_rv(r: str) -> list[str]:
    fields = {'r': r, 'addr': WAIT_ADDR, 'addr_cmp': WAIT_ADDR + 8, 'ctrl_base': CTRL_REG}
    return [line.format(**fields) for line in WAIT_RV]

class RvWriteLabel(WriteLabel):
    def expand_rv(self, prog):
        return []


class RvEnd(End):
    def expand_rv(self, prog):
        return ['j .']

class RvWriteReg(WriteReg):
    def expand_rv(self, prog):
        dst = rv_reg(prog, self.dst)
        if isinstance(self.src, Integral):
            return [f'li {dst}, {to_int32(self.src)}']
        if isinstance(self.src, str):
            return [f'mv {dst}, {rv_reg(prog, self.src)}']
        raise RuntimeError(f"invalid src: {self.src}")

class RvIncReg(IncReg):
    def expand_rv(self, prog):
        dst = rv_reg(prog, self.dst)
        if isinstance(self.src, Integral):
            return add_rv(dst, dst, self.src)
        if isinstance(self.src, str):
            return add_rv(dst, dst, rv_reg(prog, self.src))
        raise RuntimeError(f"invalid src: {self.src}")


class RvReadWmem(ReadWmem):
    def expand_rv(self, prog):
        offset = prog.wave2idx[self.name] * WMEM_STRIDE
        insts = [f'la {CTRL_REG}, {WMEM_LABEL}+{offset}']
        insts += [f'lw {reg}, {4*i}({CTRL_REG})' for i, reg in enumerate(WREG_RV)]
        return insts


class RvWriteWmem(WriteWmem):
    def expand_rv(self, prog):
        offset = prog.wave2idx[self.name] * WMEM_STRIDE
        insts = [f'la {CTRL_REG}, {WMEM_LABEL}+{offset}']
        insts += [f'sw {reg}, {4*i}({CTRL_REG})' for i, reg in enumerate(WREG_RV)]
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


class RvReadDmem(ReadDmem):
    def expand_rv(self, prog):
        dst = rv_reg(prog, self.dst)
        return [*dmem_addr_rv(prog, self.addr), f'lw {dst}, 0({T_REG})']


class RvWriteDmem(WriteDmem):
    def expand_rv(self, prog):
        insts = dmem_addr_rv(prog, self.addr)
        setup, src = operand_rv(prog, self.src)
        return [*insts, *setup, f'sw {src}, 0({T_REG})']

class RvReadInput(ReadInput):
    def expand_rv(self, prog):
        port_l = rv_reg(prog, 's_port_l')
        port_h = rv_reg(prog, 's_port_h')
        return [f'li {CTRL_REG}, {CTRL_RES}',
                f'lw x0, 0({CTRL_REG})',          
                f'lw {port_l}, 4({CTRL_REG})',   
                f'lw {port_h}, 8({CTRL_REG})']    


class RvJump(Jump):
    def expand_rv(self, prog):
        return [f'j {self.label}']


class RvCall(Call):
    def expand_rv(self, prog):
        return [f'jal ra, {self.label}']


class RvCondJump(CondJump):
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



class RvOpenLoop(OpenLoop):
    def expand_rv(self, prog):
        prog.loop_stack.append((self.name, self.n))
        return [*RvWriteReg(dst=self.name, src=0).expand_rv(prog),
                f'{self.name}:']


class RvCloseLoop(CloseLoop):
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
            insts += RvWriteWmem(name=wname).expand_rv(prog)
        for reg, steps in reg_sweeps:
            insts += RvIncReg(dst=reg.full_addr(), src=steps['step']).expand_rv(prog)

        reg = rv_reg(prog, prog.reg_dict[lname].full_addr())
        insts += [f'addi {reg}, {reg}, 1',
                  f'li {T_REG}, {lcount}',
                  f'blt {reg}, {T_REG}, {label}']

        for wname, spans_to_apply in wave_sweeps:
            insts += RvReadWmem(name=wname).expand_rv(prog)
            for par, steps in spans_to_apply:
                insts += RvIncReg(dst="w_"+par, src=-steps['step']-steps['span']).expand_rv(prog)
            insts += RvWriteWmem(name=wname).expand_rv(prog)
        for reg, steps in reg_sweeps:
            insts += RvIncReg(dst=reg.full_addr(), src=-steps['step']-steps['span']).expand_rv(prog)

        return insts

def set_timereg_rv(prog, t_reg) -> list[str]:
    return RvWriteReg(dst='s_out_time', src=t_reg).expand_rv(prog)


def inc_timereg_rv(prog, t_reg) -> list[str]:
    return RvIncReg(dst='s_out_time', src=t_reg).expand_rv(prog)


class RvDelay(Delay):
    def expand_rv(self, prog):
        t_reg = self.t_regs["t"]
        if t_reg is None:
            return []
        if isinstance(t_reg, int):
            return add_rv(REF_REG, REF_REG, t_reg)
        return add_rv(REF_REG, REF_REG, rv_reg(prog, t_reg))


class RvWait(Wait):
    def expand_rv(self, prog):
        t_reg = self.t_regs["t"]
        if t_reg is None:
            return []
        if not isinstance(t_reg, int):
            raise RuntimeError("WAIT can only take a scalar argument, not a sweep")
        return [*abs_time_rv(prog, t_reg),
                f'li {CTRL_REG}, {CTRL_BASE}',
                *wait_rv(T_REG)]


class RvResync(Resync):
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


def fire_rv(ch_base: int, slot: int) -> list[str]:
    """Write T_REG as the start time of ch_base, then fire slot."""
    return [f'li {SCRATCH_REG}, {ch_base + RF_START_TIME}',
            f'sw {T_REG}, 0({SCRATCH_REG})',
            f'li {CTRL_REG}, {ch_base}',
            *([f'sw x0, {RF_FIRE}({CTRL_REG})'] if slot == 0 else
              [f'li {SCRATCH_REG}, {slot}', f'sw {SCRATCH_REG}, {RF_FIRE}({CTRL_REG})'])]


class RvPulse(Pulse):
    def expand_rv(self, prog):
        insts = []
        pulse = prog.pulses[self.name]
        if self.ch not in RF_BASES:
            raise RuntimeError(f"gen channel {self.ch} has no RISC-Q drive channel")
        ch_base = RF_BASES[self.ch]
        t_reg = self.t_regs['t']
        if isinstance(t_reg, Integral):
            insts += abs_time_rv(prog, t_reg)
        else:
            insts += set_timereg_rv(prog, t_reg)
            insts += add_rv(T_REG, REF_REG, OUT_REG)
        w = dict(zip(WMEM_FIELDS, WREG_RV))
        for slot, wave in enumerate(pulse.get_wavenames()):
            if slot > 0:
                insts.append(f'add {T_REG}, {T_REG}, {w["length"]}')
            insts += RvReadWmem(name=wave).expand_rv(prog)
            base = (slot + 1) * RF_SLOT_STRIDE
            insts += [f'li {CTRL_REG}, {ch_base}',
                      f'sw {w["freq"]}, {RF_FREQ}({CTRL_REG})',
                      f'sw {w["phase"]}, {base}({CTRL_REG})',
                      f'sw {w["gain"]}, {base + 4}({CTRL_REG})',
                      f'sw {w["env"]}, {base + 8}({CTRL_REG})',
                      f'sw {w["length"]}, {base + 12}({CTRL_REG})']
            insts += fire_rv(ch_base, slot)
        return insts


class RvConfigReadout(ConfigReadout):
    def expand_rv(self, prog):
        insts = []
        pulse = prog.pulses[self.name]
        w = dict(zip(WMEM_FIELDS, WREG_RV))
        for wave in pulse.get_wavenames():
            insts += RvReadWmem(name=wave).expand_rv(prog)
            insts += [f'li {CTRL_REG}, {RF_DEMOD}',
                      f'sw {w["freq"]}, {RF_FREQ}({CTRL_REG})',
                      f'sw {w["phase"]}, {RF_PHASE_OFFSET}({CTRL_REG})']
        return insts


class RvTrigger(Trigger):
    def expand_rv(self, prog):
        if self.pins or self.tts or self.ddr4 or self.mr:
            raise RuntimeError("RISC-Q only supports readout triggers (no pins, time taggers, ddr4 or mr)")
        if not self.ros:
            return []
        t_reg = self.t_regs['t']
        if t_reg is None:
            insts = add_rv(T_REG, REF_REG, OUT_REG)
        else:
            insts = abs_time_rv(prog, t_reg)
        return [*insts, *fire_rv(RF_DEMOD, 0)]


RV_MACROS = {WriteLabel: RvWriteLabel, End: RvEnd,
             WriteReg: RvWriteReg, IncReg: RvIncReg,
             ReadWmem: RvReadWmem, WriteWmem: RvWriteWmem,
             ReadDmem: RvReadDmem, WriteDmem: RvWriteDmem,
             ReadInput: RvReadInput, Jump: RvJump, Call: RvCall, CondJump: RvCondJump,
             OpenLoop: RvOpenLoop, CloseLoop: RvCloseLoop,
             Delay: RvDelay, Wait: RvWait, Resync: RvResync,
             Pulse: RvPulse, ConfigReadout: RvConfigReadout, Trigger: RvTrigger}
