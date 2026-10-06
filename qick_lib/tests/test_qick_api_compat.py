"""Existing QickProgram API programs (unchanged program code) compiled through the RISC-V backend and run on the interpreter."""

from pathlib import Path

import pytest

from qick.riscv import AveragerProgram, NDAveragerProgram, QickSoc, QickSweep
from rvsim import Sim

CONFIG = Path(__file__).resolve().parents[2] / "risc-q" / "software" / "configs" / "sim-2q.json"


@pytest.fixture()
def soc(tmp_path):
    return QickSoc(CONFIG, out=tmp_path)


class Loopback(AveragerProgram):
    def initialize(self):
        cfg = self.cfg
        self.declare_gen(ch=cfg["res_ch"], nqz=1)
        self.declare_readout(ch=0, length=100, freq=cfg["pulse_freq"], gen_ch=cfg["res_ch"])
        freq = self.freq2reg(cfg["pulse_freq"], gen_ch=cfg["res_ch"], ro_ch=0)
        self.set_pulse_registers(ch=cfg["res_ch"], style="const", freq=freq, phase=0, gain=cfg["pulse_gain"], length=20)
        self.synci(200)

    def body(self):
        self.measure(pulse_ch=self.cfg["res_ch"], adcs=[0], adc_trig_offset=100, wait=True, syncdelay=self.us2cycles(1.0))


class GainSweep(NDAveragerProgram):
    def initialize(self):
        cfg = self.cfg
        self.declare_gen(ch=cfg["res_ch"], nqz=1)
        self.declare_readout(ch=0, length=100, freq=cfg["pulse_freq"], gen_ch=cfg["res_ch"])
        freq = self.freq2reg(cfg["pulse_freq"], gen_ch=cfg["res_ch"], ro_ch=0)
        self.set_pulse_registers(ch=cfg["res_ch"], style="const", freq=freq, phase=0, gain=cfg["g_start"], length=20)
        self.res_r_gain = self.get_gen_reg(cfg["res_ch"], "gain")
        self.add_sweep(QickSweep(self, self.res_r_gain, cfg["g_start"], cfg["g_stop"], cfg["g_expts"]))
        self.synci(200)

    def body(self):
        self.measure(pulse_ch=self.cfg["res_ch"], adcs=[0], adc_trig_offset=100, wait=True, syncdelay=self.us2cycles(1.0))


def run(prog, soc, max_steps=5_000_000):
    prog.compile()
    sim = Sim(prog.image.data, soc.soc_map.mem_bytes, soc.soc_map.CTRL_TIME).run(max_steps)
    return sim, sim.word(prog.image.symbols["__qick_dmem"][0] + 4)      # shot counter (data memory word 1)


def test_averager_runs_reps_times(soc):
    cfg = {"res_ch": 1, "reps": 7, "pulse_freq": 100, "pulse_gain": 1000}
    sim, counter = run(Loopback(soc, cfg), soc)
    assert counter == 7
    assert sum(1 for _, a, _ in sim.log if a == soc.soc_map.RF_READOUT) == 7        # one pulse per shot


def test_nd_sweep_iterates_every_point(soc):
    cfg = {"res_ch": 1, "reps": 3, "pulse_freq": 100, "g_start": 100, "g_stop": 500, "g_expts": 5}
    sim, counter = run(GainSweep(soc, cfg), soc)
    assert counter == 15
    gains = [v for _, a, v in sim.log if a == soc.soc_map.RF_READOUT + 0x14]
    assert gains[:5] == [100, 200, 300, 400, 500]


def test_acquire_exports_and_reports_no_core(soc, tmp_path):
    from qick.riscv import NoCoreAttached
    prog = Loopback(soc, {"res_ch": 1, "reps": 1, "pulse_freq": 100, "pulse_gain": 1000})
    with pytest.raises(NoCoreAttached):
        prog.acquire(soc)
    assert (tmp_path / "Loopback.s").exists() and (tmp_path / "Loopback.bin").exists()


def test_unsupported_features_fail_clearly(soc):
    class Ddr(Loopback):
        def body(self):
            self.trigger(ddr4=True)

    with pytest.raises(RuntimeError, match="no DDR4"):
        Ddr(soc, {"res_ch": 1, "reps": 1, "pulse_freq": 100, "pulse_gain": 1000})
