from qick.asm_riscv import RvAveragerProgram
from qick.asm_v2 import QickSweep1D


class Delay(RvAveragerProgram):
    def _initialize(self, cfg):
        pass

    def _body(self, cfg):
        self.delay(1.0)


class Pulse(RvAveragerProgram):
    def _initialize(self, cfg):
        self.declare_gen(ch=0, nqz=1)
        self.add_pulse(ch=0, name='p', ro_ch=None, style='const', freq=100, phase=0, gain=0.5, length=0.1)

    def _body(self, cfg):
        self.pulse(ch=0, name='p', t=0)
        self.delay_auto(0.2)


class Sweep(RvAveragerProgram):
    def _initialize(self, cfg):
        self.declare_gen(ch=0, nqz=1)
        self.declare_readout(ch=0, length=1.0)
        self.add_readoutconfig(ch=0, name='ro', freq=100, gen_ch=0)
        self.add_pulse(ch=0, name='p', ro_ch=0, style='const', freq=QickSweep1D('f', 90, 110), phase=0,
                       gain=QickSweep1D('g', 0.1, 0.5), length=0.1)
        self.add_loop('f', 5)
        self.add_loop('g', 4)

    def _body(self, cfg):
        self.send_readoutconfig(ch=0, name='ro', t=0)
        self.pulse(ch=0, name='p', t=0.1)
        self.trigger(ros=[0], t=0.2)
        self.wait_auto()
        self.read_input(ro_ch=0)
        self.delay_auto(0.2)


PROGRAMS = [Delay, Pulse, Sweep]
