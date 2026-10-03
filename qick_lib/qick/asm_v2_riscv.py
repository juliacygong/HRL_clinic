from .asm_v2 import Wait
CTRL_BASE = 0x4000            
WAIT_ADDR = 0x0               

CTRL_REG = "t1"               
REF_REG  = "s11"              
T_REG    = "t0"               

# wait ch, p, $r 
WAIT_RV = ['sw {r}, {addr}({ctrl_base})',
           'lw x0, {addr_cmp}({ctrl_base})']


def wait_rv(r: str) -> list[str]:
    fields = {'r': r, 'addr': WAIT_ADDR, 'addr_cmp': WAIT_ADDR + 8, 'ctrl_base': CTRL_REG}
    return [line.format(**fields) for line in WAIT_RV]


class RvWait(Wait):
    def expand_rv(self, prog):
        t_reg = self.t_regs["t"]
        if t_reg is None:
            return []
        if not isinstance(t_reg, int):
            raise RuntimeError("WAIT can only take a scalar argument, not a sweep")
        return [f'li {T_REG}, {t_reg}',
                f'add {T_REG}, {T_REG}, {REF_REG}',
                f'li {CTRL_REG}, {CTRL_BASE}',
                *wait_rv(T_REG)]
