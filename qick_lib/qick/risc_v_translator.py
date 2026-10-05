instList = {}

# I-type.
instList['pushi'] = {'rv': [
    'addi sp, sp, -4',
    'sw   {ra}, 0(sp)',
    'addi {rb}, x0, {imm}']}
instList['popi'] = {'rv': [
    'lw   {r}, 0(sp)',
    'addi sp, sp, 4']}
instList['mathi'] = {'rv': {
    '+': ['addi {ra}, {rb}, {imm}'],
    '-': ['addi {ra}, {rb}, -{imm}'],
    '*': ['li   {rc}, {imm}', 'mul {ra}, {rb}, {rc}']}}
instList['seti'] = {'rv': [
    'sw   {r1}, 0x4({chbase})',      # freq
    'sw   {r2}, 0x10({chbase})',     # phase
    'sw   {r3}, 0x14({chbase})',     # amp
    'sw   {r4}, 0x18({chbase})',     # env
    'sw   {r5}, 0x1c({chbase})',     # dur
    'sw   {r6}, 0x4100({chbase})',   # start time
    'sw   {r7}, 0x0({chbase})']}     # idx (fires the pulse)
instList['waiti'] = {'rv': [
    'sw   {r}, {addr}({ctrl_base})',
    'lw   x0, {addr}+8({ctrl_base})']}
instList['bitwi'] = {'rv': {
    '&':  ['andi {ra}, {rb}, {imm}'],
    '|':  ['ori  {ra}, {rb}, {imm}'],
    '^':  ['xori {ra}, {rb}, {imm}'],
    '<<': ['slli {ra}, {rb}, {imm}'],
    '>>': ['srli {ra}, {rb}, {imm}'],
    '~':  ['xori {ra}, {rb}, -1']}}
instList['memri'] = {'rv': ['lw   {r}, {imm}(x0)']}
instList['memwi'] = {'rv': ['sw   {r}, {imm}(x0)']}
instList['regwi'] = {'rv': ['li   {r}, {imm}']}
instList['setbi'] = {'rv': instList['seti']['rv']}

# J-type.
instList['condj'] = {'rv': {
    '<':  ['blt {ra}, {rb}, {label}'],
    '<=': ['bge {rb}, {ra}, {label}'],
    '>':  ['blt {rb}, {ra}, {label}'],
    '>=': ['bge {ra}, {rb}, {label}'],
    '==': ['beq {ra}, {rb}, {label}'],
    '!=': ['bne {ra}, {rb}, {label}'],
}}
instList['loopnz'] = {'rv': [
    'bne  x0, {r1}, {label}',
    'addi {r1}, {r1}, -1']}

# R-type.
instList['math'] = {'rv': {
    '+': ['add {ra}, {rb}, {rc}'],
    '-': ['sub {ra}, {rb}, {rc}'],
    '*': ['mul {ra}, {rb}, {rc}']}}
instList['set'] = {'rv': instList['seti']['rv']}
instList['read'] = {'rv': [
    'lw   {ra}, 4({ch})',
    'lw   {rb}, 8({ch})']}
instList['wait'] = {'rv': instList['waiti']['rv']}
instList['bitw'] = {'rv': {
    '&':  ['and {ra}, {rb}, {rc}'],
    '|':  ['or  {ra}, {rb}, {rc}'],
    '^':  ['xor {ra}, {rb}, {rc}'],
    '<<': ['sll {ra}, {rb}, {rc}'],
    '>>': ['srl {ra}, {rb}, {rc}'],
    '~':  ['xori {ra}, {rb}, -1']}}
instList['memr'] = {'rv': [
    'slli {to}, {rb}, 2',
    'lw   {ra}, 0({to})']}
instList['memw'] = {'rv': [
    'slli {to}, {rb}, 2',
    'sw   {ra}, 0({to})']}
instList['setb'] = {'rv': instList['seti']['rv']}
