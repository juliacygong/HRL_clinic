import re
import struct
from fractions import Fraction

from qick import get_version
from .qick_asm import QickConfig

DREG_QTY = 16
READOUT_CH = 2
TRIGGER_PORT = 1
PIN_PORT = 0
GEN_FREQ_MHZ = 500.0       # axis_signal_gen_v6 clock (= the dsp clock, fixed by the controller design)
GEN_SAMPS_PER_CLK = 16     # QICK N_DDS
GEN_ENV_N = 12             # QICK N (QickGenParams.envN)
REFCLK_MHZ = 245.76        # RF reference; QICK derives every DDS rate as refclk * fs_mult / fdds_div
# fs = 16 * 500 = 8000 MS/s is not an integer multiple of refclk, so express it as fs_mult / fdds_div = 3125 / 96
_FS_RATIO = Fraction(GEN_SAMPS_PER_CLK * GEN_FREQ_MHZ).limit_denominator(10**6) / Fraction(REFCLK_MHZ).limit_denominator(10**6)
GEN_FS_MULT, GEN_FS_DIV = _FS_RATIO.numerator, _FS_RATIO.denominator
assert abs(REFCLK_MHZ * GEN_FS_MULT / GEN_FS_DIV - GEN_SAMPS_PER_CLK * GEN_FREQ_MHZ) < 1e-6


def asm_text(lines, equs):
    """the .s file: .equ block, then the lines (labels and directives flush left, instructions indented)"""
    out = [f'.equ {k}, {v:#x}' for k, v in equs.items()]
    out += [l if l.endswith(':') or l.startswith(('.', '#')) else '    ' + l for l in lines]
    return '\n'.join(out) + '\n'


def words(data):
    data += bytes(-len(data) % 4)
    return list(struct.unpack(f'<{len(data) // 4}I', data))


class RvConfig(QickConfig):
    """QickConfig built from a riscq SocMap instead of a firmware dump.
    v1=True describes the same hardware to the v1 program classes (static readout triggered on a port, one pin)."""

    def __init__(self, soc_map, v1=False):
        self.soc_map = soc_map
        self.equs = {k: int(v, 0) for k, v in re.findall(r'#define (\w+) (\w+)', soc_map.gen_header())}
        f_clk = soc_map.params.dsp_freq_hz / 1e6      # core / time-counter clock
        f_gen = GEN_FREQ_MHZ                           # axis_signal_gen_v6 fabric clock
        fs = GEN_SAMPS_PER_CLK * f_gen
        # axis_signal_gen_v6 as the QICK driver describes it (drivers/generator.py, AxisSignalGen), with the
        # QickGenParams defaults for N and N_DDS: maxlen = 2**N * N_DDS
        gen = {'type': 'axis_signal_gen_v6', 'fullpath': 'riscq', 'maxlen': 2**GEN_ENV_N * GEN_SAMPS_PER_CLK,
               'complex_env': True, 'samps_per_clk': GEN_SAMPS_PER_CLK, 'maxv_scale': 1.0, 'has_dds': True,
               'b_dds': 32, 'b_phase': 32, 'maxv': 32766, 'has_mixer': False, 'revision': 6, 'version': '1.0',
               'dac': '00', 'fs': fs, 'fs_mult': GEN_FS_MULT, 'fs_div': GEN_FS_DIV, 'interpolation': 1,
               'f_fabric': f_gen, 'f_dds': fs, 'fdds_div': GEN_FS_DIV}
        # axis_dyn_readout_v1 as the ZCU216 standard firmware describes it (firmware/testbench/qick_testbench/soccfg.json);
        # declare_readout() is host-side configuration and never enters the compiled program (only trigger / send_readoutconfig do)
        ro = {'avg_maxlen': 8192, 'buf_maxlen': 4096, 'has_edge_counter': False, 'has_weights': False,
              'trigger_type': 'dport', 'trigger_port': TRIGGER_PORT, 'trigger_bit': 0, 'tproc_ch': 0, 'tproc_ctrl': READOUT_CH,
              'adc': '00', 'b_phase': 32, 'fs': 2457.6, 'fs_mult': 40, 'fs_div': 4, 'decimation': 1,
              'f_fabric': 307.2, 'f_dds': 2457.6, 'fdds_div': 4, 'f_output': 307.2, 'b_dds': 32, 'iq_offset': 0.0,
              'has_outsel': True, 'ro_type': 'axis_dyn_readout_v1'}
        cpu = {'type': 'riscq', 'revision': 0, 'pmem_size': soc_map.mem_bytes // 4, 'dmem_size': soc_map.mem_bytes // 4,
               'wmem_size': soc_map.mem_bytes // 4, 'dreg_qty': DREG_QTY, 'f_core': f_clk, 'f_time': f_clk,
               'output_pins': [('dport', PIN_PORT, 0, 'PIN0')] if v1 else []}
        if v1:
            cpu.update(type='axis_tproc64x32_x8', start_pin=None)
            ro.pop('tproc_ctrl')
        super().__init__({'board': soc_map.params.name, 'sw_version': get_version(), 'refclk_freq': REFCLK_MHZ,
                          'fw_timestamp': 'riscq', 'extra_description': [],
                          'gens': [dict(gen, tproc_ch=ch.index) for ch in soc_map.channels()],
                          'readouts': [ro], 'iqs': [], 'time_taggers': [], 'tprocs': [cpu]})

    def __getitem__(self, key):
        if key in ('ddr4_buf', 'mr_buf'):
            raise RuntimeError(f"RISC-Q has no {key.split('_')[0].upper()} buffer")
        return super().__getitem__(key)

    def description(self):
        p, m = self.soc_map.params, self.soc_map
        names = ['gate drive', 'readout drive', 'demod carrier']
        lines = [f"RISC-Q SoC '{p.name}', software version {self['sw_version']}",
                 f"\n\tCore clock (dsp): {p.dsp_freq_hz / 1e6:.3f} MHz, {m.mem_bytes} bytes of RAM, multiply {'on' if p.with_mul else 'off'}",
                 f"\n\t{len(self['gens'])} pulse channels:"]
        lines += [f"\t{i}:\t{names[i]}, {c.slot_count} slot(s), base {c.base:#x}" for i, c in enumerate(m.channels())]
        lines += ["\n\t1 readout:", "\t0:\tdemod, triggered by playing the demod channel"]
        return "\n".join(lines)
