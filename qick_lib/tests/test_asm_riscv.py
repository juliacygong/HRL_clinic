import re
from pathlib import Path

import pytest

from conftest import CONFIG
from programs import Pulse, PROGRAMS
from qick.asm_riscv import RvProgram, RvAveragerProgram
from qick.riscq_config import RvConfig
from riscq.map import SocMap, SocParams

NEW_FILES = ["asm_riscv.py", "asm_v2_riscv.py"]
BRANCH = re.compile(r'^\s*(?:j|jal(?:\s+ra,)?|b\w+)\s+(?:.*,\s*)?([A-Za-z_]\w*)\s*$')


@pytest.fixture(scope="module")
def cfg():
    return RvConfig(SocMap(SocParams.load(CONFIG)))




@pytest.fixture(params=PROGRAMS, ids=lambda c: c.__name__)
def prog(request, cfg):
    return request.param(cfg, reps=3, final_delay=1.0)


def test_links(prog):
    img = prog.image
    assert {"main", "__qick_wmem", "__qick_ext", "__qick_dmem"} <= set(img.symbols)
    assert prog.binprog["pmem"] and len(img.data) == 4 * len(prog.binprog["pmem"])


def test_shape(prog):
    lines = [l.strip() for l in prog.asm().splitlines()]
    assert '.globl main' in lines and 'main:' in lines and '__qick_exit:' in lines
    assert lines.count('ret') >= 1 and '.section .data' in lines


def test_labels_defined(prog):
    lines = [l.split('#')[0].strip() for l in prog.asm().splitlines()]
    defined = {l[:-1] for l in lines if l.endswith(':')}
    for l in lines:
        m = BRANCH.match(l)
        if m and not re.fullmatch(r'\d+[fb]', m.group(1)):
            assert m.group(1) in defined, l


def test_write_files(prog, tmp_path):
    prog.write_asm(tmp_path / 'p.s')
    prog.write_bin(tmp_path / 'p.bin')
    assert (tmp_path / 'p.s').read_text() == prog.asm()
    assert (tmp_path / 'p.bin').read_bytes() == prog.image.data


def test_ext_counter_in_memory(cfg):
    asm = Pulse(cfg, reps=3, final_delay=1.0).asm()
    assert 'la t0, __qick_ext+0' in asm and '__qick_ext:' in asm


def test_raw_asm_and_macro_coverage(cfg):
    class P(RvProgram):
        pass
    p = P(cfg)
    p.nop()
    p.label('x')
    p.write_reg(dst='r0', src=5)
    p.inc_reg(dst='r0', src=-1)
    p.cond_jump(label='x', arg1='r0', test='NZ')
    p.end()
    asm = p.asm()
    for frag in ['nop', 'x:', 'li s0, 5', 'addi s0, s0, -1', 'bnez s0, x', 'j __qick_exit']:
        assert frag in asm


def test_unknown_macro_rejected(cfg):
    from qick.asm_v2 import Macro
    with pytest.raises(RuntimeError):
        RvProgram(cfg).append_macro(Macro())


def test_no_legacy_names_in_new_files():
    root = Path(__file__).resolve().parents[1] / "qick"
    for name in NEW_FILES:
        assert 'tproc' not in (root / name).read_text().lower(), name


def test_write_bin_compiles_on_demand(cfg, tmp_path):
    class P(RvProgram):
        pass
    p = P(cfg)
    p.nop()
    p.write_bin(tmp_path / 'p.bin')
    assert (tmp_path / 'p.bin').read_bytes() == p.image.data


def test_pulse_on_missing_channel_rejected(cfg, monkeypatch):
    class P(RvAveragerProgram):
        def _initialize(self, cfg):
            self.declare_gen(ch=0, nqz=1)
            self.add_pulse(ch=0, name='p', ro_ch=None, style='const', freq=100, phase=0, gain=0.5, length=0.1)

        def _body(self, cfg):
            self.pulse(ch=0, name='p', t=0)

    monkeypatch.delitem(cfg.equs, 'RF_CH0')
    with pytest.raises(RuntimeError, match="no RISC-Q drive channel"):
        P(cfg, reps=1, final_delay=1.0)
