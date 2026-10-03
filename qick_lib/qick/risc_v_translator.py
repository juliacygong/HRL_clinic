__name__ = "qick_lib.qick.risc_v_translator"
# Reference of the Instruction Set for the QICK RISC-V Translator
"""     'NOP'        : '000 - No Operation',
        'TEST'       : '000 - Update ALU Flags with an Operation',
        'JUMP'       : '001 - Branch to a Specific Address',
        'CALL'       : '001 - Function Call',
        'RET'        : '001 - Function Return',
        'FLAG'       : '010 - FLAG set / reset',
        'TIME'       : '010 - Time Instruction',
        'ARITH'      : '010 - Opeates (A+/-B)*C+/-D',
        'DIV'        : '010 - Opeates (A/B) Return Quotient and Reminder',
        'NET'        : '011 - Network Peripheral Instruction',
        'COM'        : '011 - Communication Peripheral Instruction',
        'PA'         : '011 - Cutsom Peripheral Instruction',
        'PB'         : '011 - Cutsom Peripheral Instruction',
        'REG_WR'     : '100 - Register Write',
        'DMEM_WR'    : '101 - Data Memory Write',
        'WMEM_WR'    : '101 - WaveParam Memory Write',
        'TRIG'       : '110 - Trigger Set',
        'DPORT_WR'   : '110 - Data Port Write',
        'DPORT_RD'   : '110 - Data Port Read',
        'WPORT_WR'   : '110 - WaveParam Port Write',
        'CLEAR'      : 'Complex Clear Flag (dt_new).',
        'WAIT'       : 'Complex - Jump [HERE] Until time value arrives.'
        }
"""

# tProc ALU operator -> RV32I instruction templates.
# {rd} = destination, {a} = first operand, {b} = second operand, {t} = a scratch register.
aluList = {
        '+'     : ['add, {ra}, {rb}, {rc}'],
        '-'     : ['sub {ra}, {rb}, {rc}'],
        'AND'   : ['and {ra}, {rb}, {rc}'],
        '&'     : ['and {ra}, {rb}, {rc}'],
        'MSK'   : ['and {ra}, {rb}, {rc}'],
        'ASR'   : ['andi {t}, {rc}, 15', 'sra {ra}, {rb}, {t}'],    
        'ABS'   : ['srai {t}, {rc}, 31', 'xor {ra}, {rc}, {t}', 'sub {ra}, {ra}, {t}'],  
        'MSH'   : ['srli {ra}, {rb}, 16'],                        
        'LSH'   : ['slli {ra}, {rb}, 16', 'srli {ra}, {ra}, 16'],   
        'SWP'   : ['slli {t}, {ra}, 16', 'srli {ra}, {rb}, 16', 'or {ra}, {ra}, {t}'],  
        'NOT'   : ['xori {ra}, {rb}, -1'],
        '!'     : ['xori {ra}, {rb}, -1'],
        'OR'    : ['or   {ra}, {rb}, {rc}'],
        '|'     : ['or   {ra}, {rb}, {rc}'],
        'XOR'   : ['xor  {ra}, {rb}, {rc}'],
        '^'     : ['xor  {ra}, {rb}, {rc}'],
        'CAT'   : ['slli {t}, {rb}, 16', 'slli {ra}, {rc}, 16', 'srli {ra}, {ra}, 16', 'or {ra}, {ra}, {t}'],  
        '::'    : ['slli {t}, {rb}, 16', 'slli {ra}, {rc}, 16', 'srli {ra}, {ra}, 16', 'or {ra}, {ra}, {t}'],
        'RFU'   : ['mv   {ra}, zero'],                             
        'PAR'   : ['srli {t}, {rb}, 16', 'xor {ra}, {rb}, {t}',      
                   'srli {t}, {ra}, 8', 'xor {ra}, {ra}, {t}',
                   'srli {t}, {ra}, 4', 'xor {ra}, {ra}, {t}',
                   'srli {t}, {ra}, 2', 'xor {ra}, {ra}, {t}',
                   'srli {t}, {ra}, 1', 'xor {ra}, {ra}, {t}',
                   'andi {ra}, {ra}, 1'],
        'SL'    : ['andi {t}, {rc}, 15', 'sll {ra}, {rb}, {t}'],
        '<<'    : ['andi {t}, {rc}, 15', 'sll {ra}, {rb}, {t}'],
        'SR'    : ['andi {t}, {rc}, 15', 'srl {ra}, {rb}, {t}'],     
        '>>'    : ['andi {t}, {rc}, 15', 'srl {ra}, {rb}, {t}']}


ARITH_TO_RV = {
    'T'   : ['mul {ra}}, {rb}, {rc}'],                                   
    'TP'  : ['mul {t}, {rb}, {rc}}',  'add {ra}, {t}, {rc}'],             
    'TM'  : ['mul {t}, {rb}, {rc}',  'sub {ra}, {t}, {rc}'],             
    'PT'  : ['add {t}, {ra}, {rb}',  'mul {ra}, {t}, {rb}'],            
    'PTP' : ['add {t}, {ra}, {rb}',  'mul {t}, {t}, {rb}', 'add {ra}, {t}, {rc}'],
    'PTM' : ['add {t}, {ra}, {rb}',  'mul {t}, {t}, {rb}', 'sub {ra}, {t}, {rc}'],
    'MT'  : ['sub {t}, {ra}, {rb}',  'mul {ra}, {t}, {rb}'],             
    'MTP' : ['sub {t}, {ra}, {rb}',  'mul {t}, {t}, {rb}', 'add {ra}, {t}, {rc}'],
    'MTM' : ['sub {t}, {ra}, {rb}',  'mul {t}, {t}, {rb}', 'sub {ra}, {t}, {rc}'],
}

# which operand slot each R1..R4 fills, per Instruction.ARITH
ARITH_OPERANDS = {
    'T': ['ra', 'rb'], 'TP': ['ra', 'rb', 'rc'], 'TM': ['ra', 'rb', 'rc'],
    'PT': ['rd', 'ra', 'rb'], 'MT': ['rd', 'ra', 'rb'],
    'PTP': ['rd', 'ra', 'rb', 'rc'], 'PTM': ['rd', 'ra', 'rb', 'rc'],
    'MTP': ['rd', 'ra', 'rb', 'rc'], 'MTM': ['rd', 'ra', 'rb', 'rc'],
}

instList = {}

# RISC-V Translation Instructions

# I-type.
instList['pushi'] = {'rv': {
    'lw':  ['r, 0(sp)'],
    'addi': ['sp, sp, 4']}}
instList['popi'] = {'rv': {
    'addi': ['sp, sp, -4'],
    'sw':   ['ra, 0(sp)'],
    'addi': ['rb, x0, imm']}}
instList['mathi'] = {'rv': {
    'addi': ['ra, rb, imm'],
    'addi': ['ra, rb, -imm'],
    'li': ['rc, imm'],
    'mul': ['ra, rb, rc']}}
instList['seti'] = {'rv': {
    'sw':   ['{r1}, 0x4(chbase)'], 
    'sw':   ['{r2}, 0x10(chbase)'], 
    'sw':   ['{r3}, 0x14(chbase)'], 
    'sw':   ['{r4}, 0x18(chbase)'], 
    'sw':   ['{r5}, 0x1c(chbase)'], 
    'sw':   ['{r6}, 0x4100(chbase)'], 
    'sw':   ['{r7}, 0x0(chbase)']}}
instList['waiti'] = {'rv': {
    'sw': ['r, addr(ctrl_base)'],
    'lw': ['x0, addr+8(ctrl_base)']}}
instList['bitwi'] = {'rv': {
    '&': ['and {ra}, {rb}, {imm}'],
    '|': ['or {ra}, {rb}, {imm}'],
    '^': ['xor {ra}, {rb}, {imm}'],
    '<<': ['sll {ra}, {rb}, {imm}'],
    '>>': ['srl {ra}, {rb}, {imm}'],
    '~': ['xori {ra}, {rb}, -1']}}
instList['memri'] = {'rv': {
    'lw': ['r, imm(x0)']}}
instList['memwi'] = {'rv': {
    'sw': ['r, imm(x0)']}}
instList['regwi'] = {'rv': {
    'li': ['r, imm']}}
instList['setbi'] = {'rv': {'rv': {
    'sw':   ['{r1}, 0x4(chbase)'], 
    'sw':   ['{r2}, 0x10(chbase)'], 
    'sw':   ['{r3}, 0x14(chbase)'], 
    'sw':   ['{r4}, 0x18(chbase)'], 
    'sw':   ['{r5}, 0x1c(chbase)'], 
    'sw':   ['{r6}, 0x4100(chbase)'], 
    'sw':   ['{r7}, 0x0(chbase)']}}}

# J-type.
instList['condj'] = {'rv': {
    '<':  ['blt {ra}, {rb}, {label}'],
    '<=': ['bge {rb}, {ra}, {label}'],
    '>':  ['blt {rb}, {ra}, {label}'],
    '>=': ['bge {ra}, {rb}, {label}'],
    '==': ['beq {ra}, {rb}, {label}'],
    '!=': ['bne {ra}, {rb}, {label}'],
}}
instList['loopnz'] = {'rv': ['beqz {r}, 1f', 'addi {r}, {r}, -1', 'j {label}', '1:']}


# R-type.
instList['math'] = {'rv': ['p, $r, @label', 'bne {x0} {r1}, {label}', 'addi {r1}, {r1}, -1']}
instList['set'] = {'rv': {
    'sw':   ['{r1}, 0x4(chbase)'], 
    'sw':   ['{r2}, 0x10(chbase)'], 
    'sw':   ['{r3}, 0x14(chbase)'], 
    'sw':   ['{r4}, 0x18(chbase)'], 
    'sw':   ['{r5}, 0x1c(chbase)'], 
    'sw':   ['{r6}, 0x4100(chbase)'], 
    'sw':   ['{r7}, 0x0(chbase)']}}
instList['read'] = {'rv': {
    'lw':   ['r, 4(ch)'], 
    'lw':   ['r, 8(ch)']}}
instList['wait'] = {'rv': {
    'sw':   ['r, addr(ctrl_base)'],
    'lw':   ['x0, addr+8(ctrl_base)']}}
instList['bitw'] = {'rv': {
    '&': ['and {ra}, {rb}, {rc}'],
    '|': ['or {ra}, {rb}, {rc}'],
    '^': ['xor {ra}, {rb}, {rc}'],
    '<<': ['sll {ra}, {rb}, {rc}'],
    '>>': ['srl {ra}, {rb}, {rc}'],
    '~': ['xori {ra}, {rb}, -1']}}
instList['memr'] = {'rv': {
    'slli':   ['{to}, {rb}, 2'], 
    'lw':   ['{ra}, 0{to}']}}
instList['memw'] = {'rv': {
    'slli':   ['{to}, {rb}, 2'], 
    'sw':   ['{ra}, 0{to}']}}
instList['setb'] = {'rv': {
    'sw':   ['{r1}, 0x4(chbase)'], 
    'sw':   ['{r2}, 0x10(chbase)'], 
    'sw':   ['{r3}, 0x14(chbase)'], 
    'sw':   ['{r4}, 0x18(chbase)'], 
    'sw':   ['{r5}, 0x1c(chbase)'], 
    'sw':   ['{r6}, 0x4100(chbase)'], 
    'sw':   ['{r7}, 0x0(chbase)']}}


import re   # loads Python's built in regular expression module
import logging  #creates a logger for this module
logger = logging.getLogger(__name__)



def find_pattern(regex : str, text : str):
    match = re.search(regex, text)
    match = match.group() if (match) else None
    return match

def check_name(name_str : str) -> bool:
    # Check for correct Characters
    name_check = re.findall(regex['NAME'], name_str)
    if not name_check:
        raise RuntimeError('CHECK_NAME, Name Error: ' + name_str)
    name_check = name_check[0]
    if (name_check != name_str):
        raise RuntimeError('CHECK_NAME, Name should use AlphaNumeric and _ characters: ' + name_str)
    # Check for Register Name
    if ( check_reg(name_str) ):
        raise RuntimeError('CHECK_NAME, Name can not be a Register name: ' + name_str)
    return True

def parse_labels(program_list : list, label_dict : dict) -> None:
    """add addresses for labels in command arguments
    """
    for command in program_list:
        if 'LABEL' in command and 'ADDR' not in command:
            if command['LABEL'] in label_dict:
                command['ADDR'] = label_dict[ command['LABEL'] ]
            elif command['LABEL'] == 'PREV':
                command['ADDR'] = "&%d" % (command['P_ADDR'] - 1)
            elif command['LABEL'] == 'HERE':
                command['ADDR'] = "&%d" % (command['P_ADDR'])
            elif command['LABEL'] == 'NEXT':
                command['ADDR'] = "&%d" % (command['P_ADDR'] + 1)
            elif command['LABEL'] == 'SKIP':
                command['ADDR'] = "&%d" % (command['P_ADDR'] + 2)
            else:
                raise RuntimeError('unrecognized label %s (should be a defined label, or PREV/HERE/NEXT/SKIP'%(command['LABEL']))

def integer2bin(strin : str, bits : int = 8, uint : int = 0) -> str:
    """
        receives an integer in str format and returns their bits as a string.
        
    :strin (str): string with an integer
    :bits (int): number of bits to return
    :uint (int): is unsigned 
    :returns (str): bits as a string
    """
    if (uint == 0):
        minv = -2**(bits-1)
        maxv = 2**(bits-1) - 1
    else:
        minv = 0
        maxv = 2**(bits) - 1
    dec = int(strin, 10)
    # Check max.
    if dec < minv:
        raise RuntimeError("integer2bin: number %d is smaller than %d" % (dec, minv))
    # Check max.
    if dec > maxv:
        raise RuntimeError("integer2bin: number %d is bigger than %d" % (dec, maxv))
    # Check if number is negative.
    if dec < 0:
        dec = dec + 2**bits
    # Convert to binary.
    fmt = "{0:0" + str(bits) + "b}"
    binv = fmt.format(dec)
    return binv

def get_src_type (src : str) -> str:
    """
    :returns (tuple): Type of Source
    """
    src_type = 'X'
    REG = re.findall('s(\d+)|r(\d+)|w(\d+)|#([ubh0-9A-F\-]+)',src) #S,R,W,Signed, Unsigned, Binary, Hexa
    if not REG:
        raise RuntimeError('get_src_type: Source Data not Recognized '+src )
    #print('Register Type> ',REG, REG[0])
    if ( len(REG) != 1 ):
        raise RuntimeError('get_src_type: Source Data not Recognized '+src )
    REG = REG[0]
    if   (REG[0]):   
        src_type = 'RS'
    elif (REG[1]):   
        src_type = 'RD'
    elif (REG[2]):   
        src_type = 'RW'
    elif (REG[3]):   
        src_type = 'N'
    else:            
        src_type = 'XX'
    return src_type

def check_num(num_str : str) -> bool:
    r = False
    num     = re.search('^(\d+)', num_str)
    extr_num = num.group(0) if num else ''
    if (extr_num == num_str):
        r = True
    return r

def check_lit(lit_str : str) -> bool:
    r = False
    lit     = re.search('#(-?\d+)|#u(\d+)|#b(\d+)|#h([0-9A-F]+)|&(\d+)|@(-?\d+)', lit_str)
    extr_lit = lit.group(0) if lit else ''
    if (extr_lit == lit_str):
        r = True
    return r

def get_imm_dt (lit : str, bit_len : int, lit_val : int = 0) -> str:
    LIT = re.findall('#(-?\d+)|#u(\d+)|#b(\d+)|#h([0-9A-F]+)|&(\d+)|@(-?\d+)',lit) #S,R,W,Signed, Unsigned, Binary, Hexa
    if ( not LIT or not check_lit(lit)):
        raise RuntimeError("get_imm_dt: Data Format incorrect "+ lit )
    LIT = LIT[0]
    try: 
        if (LIT[0]): ## is Signed
            literal = str(int(LIT[0]))
            DataImm = '_'+ integer2bin(literal, bit_len)
        elif (LIT[1]): ## is Unsigned
            literal = str(int(LIT[1]))
            DataImm = '_'+ integer2bin(literal, bit_len,1)
        elif (LIT[2]): ## is Binary
            literal = str(int(LIT[2],2))
            DataImm = '_'+ integer2bin(literal, bit_len,1)
        elif (LIT[3]): ## is Hexa
            literal = str(int(LIT[3],16))
            DataImm = '_'+ integer2bin(literal, bit_len,1)
        elif (LIT[4]): ## is Address
            literal = str(int(LIT[4]))
            DataImm = '_'+ integer2bin(literal, bit_len,1)
        elif (LIT[5]): ## is Time
            literal = str(int(LIT[5]))
            DataImm = '_'+ integer2bin(literal, bit_len)
        else:
            raise RuntimeError("get_imm_dt: Data Format incorrect "+ lit )
    except:
        raise RuntimeError("get_imm_dt: Data Format incorrect "+ lit )
    if (lit_val) :
        return int(literal)
    else:
        return DataImm

def check_reg(name_reg : str) -> bool:
    r = False
    name     = re.search('s(\d+)|r(\d+)|w(\d+)', name_reg)
    extr_reg = name.group(0) if name else ''
    if (extr_reg == name_reg):
        r = True
    return r

def get_reg_addr (reg : str, Type : str) -> str:
    """
    :returns: register_address.
    """
    if not check_reg(reg): #extr_num == name_num):
        raise RuntimeError('get_reg_addr: Register '+ reg +' Name error' )
    REG = re.findall('s(\d+)|r(\d+)|w(\d+)', reg)[0]
    if (Type=='Dest'):
        if (REG[0]): ## is SREG
            if (int(REG[0]) > 15): raise RuntimeError('get_reg_addr: Register s'+ str(REG[0])+' is not a sreg (Max 15)' )
            return '00'+integer2bin(REG[0], 5,1)
        elif (REG[1]): ## is DREG
            if (int(REG[1]) > 31): raise RuntimeError('get_reg_addr: Register d'+ str(REG[1])+' is not a dreg (Max 31)' )
            return '01'+integer2bin(REG[1], 5,1)
        elif (REG[2]): ## is WREG
            if (int(REG[2]) > 5): raise RuntimeError('get_reg_addr: Register w'+ str(REG[2])+' is not a wreg (Max 5)' )
            return '10'+integer2bin(REG[2], 5,1)
    elif (Type=='src_data'):
        if (REG[0]): ## is SREG
            if (int(REG[0]) > 15): raise RuntimeError('get_reg_addr: Register s'+ str(REG[0])+' is not a sreg (Max 15)' )
            return '0_00'+integer2bin(REG[0], 5,1)
        elif (REG[1]): ## is DREG
            if (int(REG[1]) > 31): raise RuntimeError('get_reg_addr: Register d'+ str(REG[1])+' is not a dreg (Max 31)' )
            return '0_01'+integer2bin(REG[1], 5,1)
        elif (REG[2]): ## is WREG
            if (int(REG[2]) > 5): raise RuntimeError('get_reg_addr: Register w'+ str(REG[1])+' is not a wreg (Max 5)' )
            return '0_10'+integer2bin(REG[2], 5,1)
    elif (Type=='src_addr'):
        if (REG[0]): ## is SREG
            if (int(REG[0]) > 15): raise RuntimeError('get_reg_addr: Register s'+ str(REG[0])+' is not a sreg (Max 15)' )
            return '0'+integer2bin(REG[0], 5,1)
        elif (REG[1]): ## is DREG
            if (int(REG[1]) > 31): raise RuntimeError('get_reg_addr: Register d'+ str(REG[1])+' is not a dreg (Max 31)' )
            return '1'+integer2bin(REG[1], 5,1)
        elif (REG[2]): ## is WREG
            if (int(REG[2]) > 5): raise RuntimeError('get_reg_addr: Register w'+ str(REG[2])+' is not a wreg (Max 5)' )
            raise RuntimeError('get_reg_addr: Register w'+ str(REG[2])+' Can not be wreg' )
    return 'X'

class LFSR:
    def __init__(self):
        self.val_bin = '00000000000000000000000000000000'
        self.val_int = 0
    def seed(self, seed):
        fmt = "{0:032b}"
        self.val_int = seed
        self.val_bin = fmt.format(seed)
    def nxt(self)-> int:
        inv_bin = self.val_bin[::-1]
        feedback = inv_bin[31] + inv_bin[21] + inv_bin[1] + inv_bin[0]
        ones = feedback.count('1')
        if (ones % 2 == 0):
            new_value = '1'
        else:
            new_value = '0'
        self.val_bin = self.val_bin[1:]+new_value
        self.val_int = int(self.val_bin, 2)
        return self.val_int
    def print (self, debug=False):
        if not debug:
            print (self.val_bin, self.val_int)
        else:
            print ('Bin: %32s / Hex: %8x / Dec: %0d' %(self.val_bin, self.val_int, self.val_int))


class Assembler():
    WAIT_TIME_OFFSET = 10
