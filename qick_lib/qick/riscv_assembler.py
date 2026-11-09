
import re
from .tprocv2_assembler import integer2bin, find_pattern
from .risc_v_translator import instList

# Register name -> number (x0..x31 plus ABI names).
REGS = {f'x{i}': i for i in range(32)}
REGS.update({
    'zero': 0, 'ra': 1, 'sp': 2, 'gp': 3, 'tp': 4,
    't0': 5, 't1': 6, 't2': 7,
    's0': 8, 'fp': 8, 's1': 9,
    'a0': 10, 'a1': 11, 'a2': 12, 'a3': 13, 'a4': 14, 'a5': 15, 'a6': 16, 'a7': 17,
    's2': 18, 's3': 19, 's4': 20, 's5': 21, 's6': 22, 's7': 23, 's8': 24, 's9': 25,
    's10': 26, 's11': 27,
    't3': 28, 't4': 29, 't5': 30, 't6': 31})

OPCODE = {
    'LOAD'  : 0b0000011,
    'OP_IMM': 0b0010011,
    'AUIPC' : 0b0010111,
    'STORE' : 0b0100011,
    'OP'    : 0b0110011,
    'LUI'   : 0b0110111,
    'BRANCH': 0b1100011,
    'JALR'  : 0b1100111,
    'JAL'   : 0b1101111,
    'SYSTEM': 0b1110011}

instList_rv = {
    'add'   : ('R',  'OP',     0b000, 0b0000000),
    'sub'   : ('R',  'OP',     0b000, 0b0100000),
    'sll'   : ('R',  'OP',     0b001, 0b0000000),
    'slt'   : ('R',  'OP',     0b010, 0b0000000),
    'sltu'  : ('R',  'OP',     0b011, 0b0000000),
    'xor'   : ('R',  'OP',     0b100, 0b0000000),
    'srl'   : ('R',  'OP',     0b101, 0b0000000),
    'sra'   : ('R',  'OP',     0b101, 0b0100000),
    'or'    : ('R',  'OP',     0b110, 0b0000000),
    'and'   : ('R',  'OP',     0b111, 0b0000000),
    'mul'   : ('R',  'OP',     0b000, 0b0000001),
    'mulh'  : ('R',  'OP',     0b001, 0b0000001),
    'mulhsu': ('R',  'OP',     0b010, 0b0000001),
    'mulhu' : ('R',  'OP',     0b011, 0b0000001),
    'div'   : ('R',  'OP',     0b100, 0b0000001),
    'divu'  : ('R',  'OP',     0b101, 0b0000001),
    'rem'   : ('R',  'OP',     0b110, 0b0000001),
    'remu'  : ('R',  'OP',     0b111, 0b0000001),
    'addi'  : ('I',  'OP_IMM', 0b000, None),
    'slti'  : ('I',  'OP_IMM', 0b010, None),
    'sltiu' : ('I',  'OP_IMM', 0b011, None),
    'xori'  : ('I',  'OP_IMM', 0b100, None),
    'ori'   : ('I',  'OP_IMM', 0b110, None),
    'andi'  : ('I',  'OP_IMM', 0b111, None),
    'slli'  : ('SH', 'OP_IMM', 0b001, 0b0000000),
    'srli'  : ('SH', 'OP_IMM', 0b101, 0b0000000),
    'srai'  : ('SH', 'OP_IMM', 0b101, 0b0100000),
    'lb'    : ('L',  'LOAD',   0b000, None),
    'lh'    : ('L',  'LOAD',   0b001, None),
    'lw'    : ('L',  'LOAD',   0b010, None),
    'lbu'   : ('L',  'LOAD',   0b100, None),
    'lhu'   : ('L',  'LOAD',   0b101, None),
    'sb'    : ('S',  'STORE',  0b000, None),
    'sh'    : ('S',  'STORE',  0b001, None),
    'sw'    : ('S',  'STORE',  0b010, None),
    'beq'   : ('B',  'BRANCH', 0b000, None),
    'bne'   : ('B',  'BRANCH', 0b001, None),
    'blt'   : ('B',  'BRANCH', 0b100, None),
    'bge'   : ('B',  'BRANCH', 0b101, None),
    'bltu'  : ('B',  'BRANCH', 0b110, None),
    'bgeu'  : ('B',  'BRANCH', 0b111, None),
    'lui'   : ('U',  'LUI',    None,  None),
    'auipc' : ('U',  'AUIPC',  None,  None),
    'jal'   : ('J',  'JAL',    None,  None),
    'jalr'  : ('JR', 'JALR',   0b000, None),
    'ecall' : ('SYS', 'SYSTEM', 0b000, 0),
    'ebreak': ('SYS', 'SYSTEM', 0b000, 1),
}

regex = {
    'LABEL'    : r'^\s*([A-Za-z_.$][\w.$]*|\d+)\s*:' ,  
    'MEM'      : r'^(.*)\((\w+)\)$'                  ,  
    'LOCAL_REF': r'^(\d+)([fb])$'                    , 
    'TERM'     : r'[+-]|[^+\-\s]+'                   ,  
}

def strip_comment(line: str) -> str:
    return re.split(r'#|//', line, maxsplit=1)[0].strip()

def split_operands(text: str) -> list:
    return [op.strip() for op in text.split(',')] if text.strip() else []

def get_reg(name: str, line_number: int) -> int:
    if name not in REGS:
        raise RuntimeError(f'line {line_number}: register "{name}" not recognized')
    return REGS[name]

def parse_mem(op: str, line_number: int) -> tuple:
    m = re.match(regex['MEM'], op.replace(' ', ''))
    if not m:
        raise RuntimeError(f'line {line_number}: memory operand "{op}" should be offset(reg)')
    return (m.group(1) or '0'), m.group(2)

def eval_expr(text: str, symbols: dict, line_number: int, pc: int = 0, local_labels: dict = None) -> int:
    tokens = re.findall(regex['TERM'], text.replace(' ', ''))
    if not tokens:
        raise RuntimeError(f'line {line_number}: missing value')
    total, sign, expect_term = 0, 1, True
    for tok in tokens:
        if tok in ('+', '-'):
            if tok == '-':
                sign = -sign
            expect_term = True
            continue
        if not expect_term:
            raise RuntimeError(f'line {line_number}: bad expression "{text}"')
        total += sign * resolve_term(tok, symbols, line_number, pc, local_labels)
        sign, expect_term = 1, False
    if expect_term:
        raise RuntimeError(f'line {line_number}: bad expression "{text}"')
    return total

def resolve_term(tok: str, symbols: dict, line_number: int, pc: int, local_labels: dict) -> int:
    try:
        return int(tok, 0)
    except ValueError:
        pass
    if tok in symbols:
        return symbols[tok]
    local = re.match(regex['LOCAL_REF'], tok)
    if local and local_labels is not None:
        addrs = local_labels.get(local.group(1), [])
        if local.group(2) == 'b':
            cands = [a for a in addrs if a <= pc]
            if cands: return cands[-1]
        else:
            cands = [a for a in addrs if a > pc]
            if cands: return cands[0]
        raise RuntimeError(f'line {line_number}: local label "{tok}" not found')
    raise RuntimeError(f'line {line_number}: symbol "{tok}" not defined')

def check_range(val: int, lo: int, hi: int, what: str, line_number: int) -> None:
    if not (lo <= val <= hi):
        raise RuntimeError(f'line {line_number}: {what} {val} out of range [{lo}, {hi}]')

def expand_pseudo(mn: str, ops: list, equs: dict, line_number: int) -> list:
    if mn == 'nop':   return [('addi', ['zero', 'zero', '0'])]
    if mn == 'mv':    return [('addi', [ops[0], ops[1], '0'])]
    if mn == 'not':   return [('xori', [ops[0], ops[1], '-1'])]
    if mn == 'neg':   return [('sub',  [ops[0], 'zero', ops[1]])]
    if mn == 'seqz':  return [('sltiu', [ops[0], ops[1], '1'])]
    if mn == 'snez':  return [('sltu', [ops[0], 'zero', ops[1]])]
    if mn == 'j':     return [('jal',  ['zero', ops[0]])]
    if mn == 'jr':    return [('jalr', ['zero', '0(' + ops[0] + ')'])]
    if mn == 'ret':   return [('jalr', ['zero', '0(ra)'])]
    if mn == 'call':  return [('jal',  ['ra', ops[0]])] 
    if mn == 'beqz':  return [('beq',  [ops[0], 'zero', ops[1]])]
    if mn == 'bnez':  return [('bne',  [ops[0], 'zero', ops[1]])]
    if mn == 'bltz':  return [('blt',  [ops[0], 'zero', ops[1]])]
    if mn == 'bgez':  return [('bge',  [ops[0], 'zero', ops[1]])]
    if mn == 'blez':  return [('bge',  ['zero', ops[0], ops[1]])]
    if mn == 'bgtz':  return [('blt',  ['zero', ops[0], ops[1]])]
    if mn == 'bgt':   return [('blt',  [ops[1], ops[0], ops[2]])]
    if mn == 'ble':   return [('bge',  [ops[1], ops[0], ops[2]])]
    if mn == 'bgtu':  return [('bltu', [ops[1], ops[0], ops[2]])]
    if mn == 'bleu':  return [('bgeu', [ops[1], ops[0], ops[2]])]
    if mn == 'jal' and len(ops) == 1:
        return [('jal', ['ra', ops[0]])]
    if mn == 'jalr' and len(ops) == 1:
        return [('jalr', ['ra', '0(' + ops[0] + ')'])]
    if mn == 'li':
        if len(ops) != 2:
            raise RuntimeError(f'line {line_number}: li needs 2 operands')
        val = eval_expr(ops[1], equs, line_number)
        check_range(val, -2**31, 2**32 - 1, 'li value', line_number)
        if -2048 <= val <= 2047:
            return [('addi', [ops[0], 'zero', str(val)])]
        val &= 0xFFFFFFFF
        hi = ((val + 0x800) >> 12) & 0xFFFFF
        lo = val & 0xFFF
        if lo >= 0x800:
            lo -= 0x1000
        out = [('lui', [ops[0], str(hi)])]
        if lo:
            out.append(('addi', [ops[0], ops[0], str(lo)]))
        return out
    return [(mn, ops)]


class Instruction():

    @staticmethod
    def R(op, f3, f7, rd, rs1, rs2) -> int:
        return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op

    @staticmethod
    def I(op, f3, rd, rs1, imm) -> int:
        return ((imm & 0xFFF) << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op

    @staticmethod
    def S(op, f3, rs1, rs2, imm) -> int:
        imm &= 0xFFF
        return ((imm >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | ((imm & 0x1F) << 7) | op

    @staticmethod
    def B(op, f3, rs1, rs2, imm) -> int:
        imm &= 0x1FFF
        return (((imm >> 12) & 1) << 31) | (((imm >> 5) & 0x3F) << 25) | (rs2 << 20) | (rs1 << 15) \
            | (f3 << 12) | (((imm >> 1) & 0xF) << 8) | (((imm >> 11) & 1) << 7) | op

    @staticmethod
    def U(op, rd, imm20) -> int:
        return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | op

    @staticmethod
    def J(op, rd, imm) -> int:
        imm &= 0x1FFFFF
        return (((imm >> 20) & 1) << 31) | (((imm >> 1) & 0x3FF) << 21) | (((imm >> 11) & 1) << 20) \
            | (((imm >> 12) & 0xFF) << 12) | (rd << 7) | op

def encode(item: dict, symbols: dict, local_labels: dict) -> int:
    mn, ops, pc, ln = item['MN'], item['OPS'], item['PC'], item['LINE']
    fmt, op_name, f3, f7 = instList_rv[mn]
    op = OPCODE[op_name]
    n_ops = {'R': 3, 'I': 3, 'SH': 3, 'L': 2, 'S': 2, 'B': 3, 'U': 2, 'J': 2, 'SYS': 0}
    if fmt in n_ops and len(ops) != n_ops[fmt]:
        raise RuntimeError(f'line {ln}: {mn} expects {n_ops[fmt]} operands, got {len(ops)}')
    ev = lambda text: eval_expr(text, symbols, ln, pc, local_labels)

    if fmt == 'R':
        return Instruction.R(op, f3, f7, get_reg(ops[0], ln), get_reg(ops[1], ln), get_reg(ops[2], ln))
    if fmt == 'I':
        imm = ev(ops[2]); check_range(imm, -2048, 2047, 'immediate', ln)
        return Instruction.I(op, f3, get_reg(ops[0], ln), get_reg(ops[1], ln), imm)
    if fmt == 'SH':
        sh = ev(ops[2]); check_range(sh, 0, 31, 'shift amount', ln)
        return Instruction.I(op, f3, get_reg(ops[0], ln), get_reg(ops[1], ln), (f7 << 5) | sh)
    if fmt == 'L':
        off, base = parse_mem(ops[1], ln)
        imm = ev(off); check_range(imm, -2048, 2047, 'offset', ln)
        return Instruction.I(op, f3, get_reg(ops[0], ln), get_reg(base, ln), imm)
    if fmt == 'S':
        off, base = parse_mem(ops[1], ln)
        imm = ev(off); check_range(imm, -2048, 2047, 'offset', ln)
        return Instruction.S(op, f3, get_reg(base, ln), get_reg(ops[0], ln), imm)
    if fmt == 'B':
        off = ev(ops[2]) - pc
        check_range(off, -4096, 4094, 'branch offset', ln)
        if off % 2:
            raise RuntimeError(f'line {ln}: branch offset {off} is not even')
        return Instruction.B(op, f3, get_reg(ops[0], ln), get_reg(ops[1], ln), off)
    if fmt == 'U':
        imm = ev(ops[1]); check_range(imm, 0, 0xFFFFF, 'upper immediate', ln)
        return Instruction.U(op, get_reg(ops[0], ln), imm)
    if fmt == 'J':
        off = ev(ops[1]) - pc
        check_range(off, -2**20, 2**20 - 2, 'jump offset', ln)
        if off % 2:
            raise RuntimeError(f'line {ln}: jump offset {off} is not even')
        return Instruction.J(op, get_reg(ops[0], ln), off)
    if fmt == 'JR':
        if len(ops) == 2:
            off, base = parse_mem(ops[1], ln)
        elif len(ops) == 3:
            base, off = ops[1], ops[2]
        else:
            raise RuntimeError(f'line {ln}: jalr expects rd, off(rs1)')
        imm = ev(off); check_range(imm, -2048, 2047, 'offset', ln)
        return Instruction.I(op, f3, get_reg(ops[0], ln), get_reg(base, ln), imm)
    if fmt == 'SYS':
        return Instruction.I(op, f3, 0, 0, f7)
    raise RuntimeError(f'line {ln}: format {fmt} not handled')


class Assembler():

    @staticmethod
    def get_list(asm_str: str) -> tuple:
      
        lines = asm_str.splitlines()

        equs = {}
        for line_number, raw in enumerate(lines, start=1):
            line = strip_comment(raw)
            m = re.match(r'^\.(equ|set)\s+([A-Za-z_][\w]*)\s*,\s*(.+)$', line)
            if m:
                if m.group(2) in equs:
                    raise RuntimeError(f'line {line_number}: constant "{m.group(2)}" defined twice')
                equs[m.group(2)] = eval_expr(m.group(3), equs, line_number)

        symbols, label_dict, local_labels = dict(equs), {}, {}
        program_list = []
        pc = 0
        for line_number, raw in enumerate(lines, start=1):
            line = strip_comment(raw)
            while True:
                label = find_pattern(regex['LABEL'], line)
                if not label:
                    break
                name = label.strip()[:-1].strip()
                if name.isdigit():
                    local_labels.setdefault(name, []).append(pc)
                else:
                    if name in symbols:
                        raise RuntimeError(f'line {line_number}: "{name}" already defined')
                    if name in REGS:
                        raise RuntimeError(f'line {line_number}: label "{name}" is a register name')
                    symbols[name] = label_dict[name] = pc
                line = line[len(label):].strip()
            if not line:
                continue

            parts = line.split(None, 1)
            mn = parts[0].lower()
            ops = split_operands(parts[1]) if len(parts) > 1 else []

            if mn.startswith('.'):
                if mn in ('.equ', '.set', '.text', '.globl', '.global'):
                    continue
                if mn == '.word':
                    for val in ops:
                        program_list.append({'LINE': line_number, 'PC': pc, 'WORD': val})
                        pc += 4
                    continue
                raise RuntimeError(f'line {line_number}: directive "{mn}" not supported')

            try:
                expanded = expand_pseudo(mn, ops, equs, line_number)
            except IndexError:
                raise RuntimeError(f'line {line_number}: {mn} has too few operands')
            for base_mn, base_ops in expanded:
                if base_mn not in instList_rv:
                    raise RuntimeError(f'line {line_number}: instruction "{mn}" not recognized')
                program_list.append({'LINE': line_number, 'PC': pc, 'MN': base_mn, 'OPS': base_ops})
                pc += 4
        return program_list, label_dict, symbols, local_labels

    @staticmethod
    def list2bin(program_list: list, symbols: dict, local_labels: dict) -> list:
        words = []
        for item in program_list:
            if 'WORD' in item:
                val = eval_expr(item['WORD'], symbols, item['LINE'], item['PC'], local_labels)
                check_range(val, -2**31, 2**32 - 1, '.word value', item['LINE'])
                words.append(val & 0xFFFFFFFF)
            else:
                words.append(encode(item, symbols, local_labels))
        return words

    @staticmethod
    def str_asm2bin(asm_str: str) -> tuple:
        """:returns: (words, labels) - 32-bit machine words, and label -> byte address."""
        program_list, label_dict, symbols, local_labels = Assembler.get_list(asm_str)
        words = Assembler.list2bin(program_list, symbols, local_labels)
        return words, label_dict

    @staticmethod
    def file_asm2bin(filename: str) -> tuple:
        with open(filename) as f:
            return Assembler.str_asm2bin(f.read())

def assemble(asm_str: str) -> tuple:
    """Assemble RISC-V source. :returns: (words, labels)."""
    return Assembler.str_asm2bin(asm_str)

def render(name: str, op: str = None, **fields) -> list:
    """
        Fill a risc_v_translator template with registers/values.
        e.g. render('mathi', '+', ra='a0', rb='a1', imm=5) -> ['addi a0, a1, 5']
    """
    if name not in instList:
        raise RuntimeError(f'render: "{name}" is not in risc_v_translator.instList')
    rv = instList[name]['rv']
    if isinstance(rv, dict):
        if op not in rv:
            raise RuntimeError(f'render: {name} needs an operator, one of {list(rv)}')
        rv = rv[op]
    try:
        return [line.format(**fields) for line in rv]
    except KeyError as e:
        raise RuntimeError(f'render: {name} is missing field {e}')

def to_hex(words: list) -> list:
    return [f'{w:08x}' for w in words]

def to_bin(words: list) -> list:
    return [integer2bin(str(w), 32, uint=1) for w in words]

def to_bytes(words: list) -> bytes:
    """Little-endian byte image, as RISC-V memory expects."""
    return b''.join(w.to_bytes(4, 'little') for w in words)
