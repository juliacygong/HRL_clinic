"""Tests for qick.riscv_translate: golden RV32I encodings, plus translated tProc v2 programs executed
on a small RV32I interpreter with a model of RISC-Q's timer and MMIO. Run with
`python3 -m unittest discover qick_lib/tests` (or pytest)."""
import importlib.util
import os
import sys
import unittest

# Load the module by path: importing the qick package pulls in numpy/pynq.
_PATH = os.path.join(os.path.dirname(__file__), "..", "qick", "riscv_translate.py")
_spec = importlib.util.spec_from_file_location("riscv_translate", _PATH)
rt = importlib.util.module_from_spec(_spec)
sys.modules["riscv_translate"] = rt
_spec.loader.exec_module(rt)

M32 = 0xFFFFFFFF


def sx(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


class Rv32:
    """Just enough RV32IM to run translated programs. Every instruction takes one timer tick."""

    def __init__(self, image, start_time=5000):
        self.base = image.base
        self.ram = bytearray(image.ram_bytes)
        blob = image.to_bytes()
        self.ram[:len(blob)] = blob
        self.x = [0] * 32
        self.pc = image.base
        self.time = start_time
        self.start_time = start_time
        self.time_cmp = 0
        self.waits = []         # time at which each halting wait read returned
        self.mmio = []          # (time, addr, value) for every RF-window store
        self.readout = {rt.CTRL_RES: 1, rt.CTRL_REAL: 111, rt.CTRL_IMAG: 222}

    def load(self, a):
        if self.base <= a < self.base + len(self.ram):
            assert a % 4 == 0, hex(a)
            return int.from_bytes(self.ram[a - self.base:a - self.base + 4], "little")
        if a == rt.CTRL_TIME:
            return self.time & M32
        if a == rt.CTRL_WAIT_TIME_CMP:
            self.time = max(self.time, self.time_cmp - 3)
            self.waits.append(self.time)
            return 0
        if a in self.readout:
            return self.readout[a] & M32
        raise AssertionError("load from unmapped %#x" % a)

    def store(self, a, v):
        if self.base <= a < self.base + len(self.ram):
            assert a % 4 == 0, hex(a)
            self.ram[a - self.base:a - self.base + 4] = (v & M32).to_bytes(4, "little")
        elif a == rt.CTRL_TIME_CMP:
            self.time_cmp = v
        elif a >= rt.RF_GATE:
            self.mmio.append((self.time, a, v & M32))
        else:
            raise AssertionError("store to unmapped %#x" % a)

    def step(self):
        w = self.load(self.pc)
        opc, rd, f3 = w & 0x7F, (w >> 7) & 31, (w >> 12) & 7
        rs1, rs2, f7 = (w >> 15) & 31, (w >> 20) & 31, w >> 25
        a, b = self.x[rs1], self.x[rs2]
        nxt, res = self.pc + 4, None
        if opc == 0x37:
            res = w & 0xFFFFF000
        elif opc == 0x17:
            res = self.pc + (w & 0xFFFFF000)
        elif opc == 0x6F:
            imm = sx(((w >> 31) & 1) << 20 | ((w >> 12) & 0xFF) << 12 | ((w >> 20) & 1) << 11
                     | ((w >> 21) & 0x3FF) << 1, 21)
            res, nxt = self.pc + 4, self.pc + imm
        elif opc == 0x67:
            res, nxt = self.pc + 4, (a + sx(w >> 20, 12)) & ~1
        elif opc == 0x63:
            imm = sx(((w >> 31) & 1) << 12 | ((w >> 7) & 1) << 11 | ((w >> 25) & 0x3F) << 5
                     | ((w >> 8) & 0xF) << 1, 13)
            sa, sb = sx(a, 32), sx(b, 32)
            taken = {0: a == b, 1: a != b, 4: sa < sb, 5: sa >= sb, 6: a < b, 7: a >= b}[f3]
            if taken:
                nxt = self.pc + imm
        elif opc == 0x03:
            assert f3 == 2
            res = self.load((a + sx(w >> 20, 12)) & M32)
        elif opc == 0x23:
            assert f3 == 2
            self.store((a + sx((w >> 25) << 5 | (w >> 7) & 31, 12)) & M32, b)
        elif opc == 0x13:
            imm = sx(w >> 20, 12)
            sh = rs2
            res = {0: a + imm, 2: int(sx(a, 32) < imm), 3: int(a < (imm & M32)), 4: a ^ imm,
                   6: a | imm, 7: a & imm, 1: a << sh,
                   5: (sx(a, 32) >> sh) if f7 == 0x20 else (a >> sh)}[f3]
        elif opc == 0x33:
            if f7 == 1:
                assert f3 == 0
                res = a * b
            else:
                res = {(0, 0): a + b, (0x20, 0): a - b, (0, 1): a << (b & 31),
                       (0, 4): a ^ b, (0, 5): a >> (b & 31), (0x20, 5): sx(a, 32) >> (b & 31),
                       (0, 6): a | b, (0, 7): a & b}[(f7, f3)]
        else:
            raise AssertionError("illegal instruction %08x at %#x" % (w, self.pc))
        if res is not None and rd:
            self.x[rd] = res & M32
        self.pc = nxt & M32
        self.time += 1

    def run(self, max_steps=500000):
        for _ in range(max_steps):
            if self.load(self.pc) == 0x0000006F:        # jal zero, 0: the park loop
                return
            self.step()
        raise AssertionError("program did not finish")

    def word(self, addr):
        return sx(self.load(addr), 32)


def run(src, target=None, **kw):
    img = rt.to_image(src, target, **kw)
    m = Rv32(img)
    m.run()
    return img, m


def dmem(img, m, i):
    return m.word(img.symbols["__qick_dmem"] + 4 * i)


def wmem(img, m, i):
    return [m.word(img.symbols["__qick_wmem"] + 32 * i + 4 * k) for k in range(6)]


def rf(m, base):
    """(offset from `base`, value) of every RF-window store to that channel."""
    return [(a - base, v) for _, a, v in m.mmio if base <= a < base + 0x10000]


class EncodingTest(unittest.TestCase):
    def test_golden_words(self):
        cases = [
            ("addi", (10, 10, 1), 0x00150513),
            ("addi", (2, 2, -16), 0xFF010113),
            ("sw", (1, 2, 12), 0x00112623),
            ("lw", (1, 2, 12), 0x00C12083),
            ("jalr", (0, 1, 0), 0x00008067),
            ("lui", (6, 0xD04E0), 0xD04E0337),
            ("auipc", (10, 0), 0x00000517),
            ("sub", (10, 10, 11), 0x40B50533),
            ("mul", (10, 10, 11), 0x02B50533),
            ("srai", (10, 10, 1), 0x40155513),
            ("slli", (10, 10, 16), 0x01051513),
            ("sw", (0, 5, 0), 0x0002A023),
        ]
        for op, args, word in cases:
            self.assertEqual(rt._encode(rt.RvInst(op, args), 0, {}), [word], op)

    def test_golden_control_flow(self):
        syms = {"L": 0x108}
        self.assertEqual(rt._encode(rt.RvInst("beq", (10, 11, "L")), 0x100, syms), [0x00B50463])
        self.assertEqual(rt._encode(rt.RvInst("blt", (10, 11, "L")), 0x100, syms), [0x00B54463])
        self.assertEqual(rt._encode(rt.RvInst("jal", (1, "L")), 0x100, syms), [0x008000EF])
        self.assertEqual(rt._encode(rt.RvInst("jal", (0, "L")), 0x108, syms), [0x0000006F])


class RegisterTest(unittest.TestCase):
    def test_reg_wr_imm(self):
        values = [0, 1, -1, 2047, -2048, 2048, 0x7FFFFFFF, -(1 << 31), -123456789]
        src = "".join("REG_WR r1 imm #%d\nDMEM_WR [&%d] op -op(r1)\n" % (v, i)
                      for i, v in enumerate(values))
        src += "REG_WR r2 imm #hFF\nDMEM_WR [&20] op -op(r2)\nREG_WR r3 imm #b101\nDMEM_WR [&21] op -op(r3)\n"
        img, m = run(src + "JUMP HERE\n")
        self.assertEqual([dmem(img, m, i) for i in range(len(values))], values)
        self.assertEqual([dmem(img, m, 20), dmem(img, m, 21)], [0xFF, 5])

    def test_alu(self):
        a, b = -7, 3
        cases = [("r1 + r2", a + b), ("r1 - r2", a - b), ("r1 + #5000", a + 5000),
                 ("r1 - #4", a - 4), ("r1 AND r2", a & b), ("r1 AND #hF0", a & 0xF0),
                 ("r1 OR r2", a | b), ("r1 XOR #3", a ^ 3), ("r1 SL #4", a << 4),
                 ("r1 SR #12", (a & M32) >> 12), ("r1 ASR #1", a >> 1), ("r1 SL r3", a << 2),
                 ("r4 CAT r5", 0x56781234), ("MSH r4", 0x1234), ("LSH r4", 0x5678),
                 ("SWP r4", 0x56781234), ("NOT r2", ~b), ("ABS r1", 7), ("PAR r2", 0),
                 ("PAR r1", bin(a & M32).count("1") & 1), ("r1 SL r6", a << 4)]  # shift uses B[3:0]
        src = "REG_WR r1 imm #%d\nREG_WR r2 imm #%d\nREG_WR r3 imm #2\n" % (a, b)
        src += "REG_WR r4 imm #h12345678\nREG_WR r5 imm #h1234\nREG_WR r6 imm #20\n"
        for i, (op, _) in enumerate(cases):
            src += "REG_WR r7 op -op(%s)\nDMEM_WR [&%d] op -op(r7)\n" % (op, i)
        img, m = run(src + "JUMP HERE\n")
        self.assertEqual([dmem(img, m, i) for i in range(len(cases))],
                         [sx(v, 32) for _, v in cases])

    def test_s0_is_zero_and_writes_to_it_vanish(self):
        img, m = run("REG_WR s0 imm #55\nREG_WR r1 op -op(s0 + #3)\nDMEM_WR [&0] op -op(r1)\n"
                     "DMEM_WR [&1] op -op(s0)\nJUMP HERE\n")
        self.assertEqual([dmem(img, m, 0), dmem(img, m, 1)], [3, 0])

    def test_spilled_registers(self):
        regs = ["r%d" % i for i in range(32)] + ["s%d" % i for i in (12, 13, 15)]
        src = "".join("REG_WR %s imm #%d\n" % (r, 100 + i) for i, r in enumerate(regs))
        src += "".join("REG_WR %s op -op(%s SL #1)\n" % (r, r) for r in regs)
        src += "".join("DMEM_WR [&%d] op -op(%s)\n" % (i, r) for i, r in enumerate(regs))
        img, m = run(src + "JUMP HERE\n")
        self.assertTrue(any("__qick_state" in v for v in img.reg_map.values()))
        for i in range(len(regs)):
            self.assertEqual(dmem(img, m, i), 2 * (100 + i))

    def test_dmem_register_addresses_wrap(self):
        img, m = run("""
            REG_WR r1 imm #7
            REG_WR r2 imm #42
            DMEM_WR [r1] op -op(r2)
            REG_WR r1 imm #261
            REG_WR r3 dmem [r1 + &2]
            DMEM_WR [&8] op -op(r3)
            DMEM_WR [r1 + &3] imm #-9
            JUMP HERE
        """)
        self.assertEqual(dmem(img, m, 8), -9)       # 261 + 3 wraps to 8, after r3 was stored
        img, m = run("REG_WR r1 imm #7\nREG_WR r2 imm #42\nDMEM_WR [r1] op -op(r2)\n"
                     "REG_WR r1 imm #261\nREG_WR r3 dmem [r1 + &2]\nDMEM_WR [&9] op -op(r3)\nJUMP HERE\n")
        self.assertEqual([dmem(img, m, 7), dmem(img, m, 9)], [42, 42])

    def test_initial_dmem(self):
        img, m = run("REG_WR r1 dmem [&2]\nREG_WR r1 op -op(r1 + #1)\nDMEM_WR [&3] op -op(r1)\n"
                     "JUMP HERE\n", dmem=[5, 6, 7])
        self.assertEqual([dmem(img, m, i) for i in range(4)], [5, 6, 7, 8])

    def test_arith(self):
        src = """
            REG_WR r1 imm #-6
            REG_WR r2 imm #7
            REG_WR r3 imm #100
            REG_WR r4 imm #1000
            ARITH T r1 r2
            DMEM_WR [&0] op -op(s3)
            ARITH TP r1 r2 r3
            DMEM_WR [&1] op -op(s3)
            ARITH TM r1 r2 r3
            DMEM_WR [&2] op -op(s3)
            ARITH PT r4 r1 r2
            DMEM_WR [&3] op -op(s3)
            ARITH MTM r4 r1 r2 r3
            DMEM_WR [&4] op -op(s3)
            JUMP HERE
        """
        for has_mul in (False, True):
            img, m = run(src, rt.Target(has_mul=has_mul))
            self.assertEqual([dmem(img, m, i) for i in range(5)],
                             [-42, 58, -142, (1000 - 6) * 7, (1000 + 6) * 7 - 100])

    def test_div(self):
        img, m = run("""
            REG_WR r1 imm #1000
            REG_WR r2 imm #7
            DIV r1 r2
            DMEM_WR [&0] op -op(s4)
            DMEM_WR [&1] op -op(s5)
            DIV r1 #33
            DMEM_WR [&2] op -op(s4)
            DMEM_WR [&3] op -op(s5)
            JUMP HERE
        """)
        self.assertEqual([dmem(img, m, i) for i in range(4)], [142, 6, 30, 10])


class ControlFlowTest(unittest.TestCase):
    def test_conditions(self):
        conds = ["Z", "NZ", "S", "NS"]      # the assembler's -if() regex can't spell 1 or 0
        vals = [-5, 0, 9]
        src, i, expect = "", 0, []
        for v in vals:
            for cond in conds:
                src += ("REG_WR r1 imm #%d\nREG_WR r2 imm #0\nTEST -op(r1)\n"
                        "REG_WR r2 imm #1 -if(%s)\nDMEM_WR [&%d] op -op(r2)\n" % (v, cond, i))
                expect.append(int({"Z": v == 0, "NZ": v != 0, "S": v < 0, "NS": v >= 0}[cond]))
                i += 1
        img, m = run(src + "JUMP HERE\n")
        self.assertEqual([dmem(img, m, k) for k in range(i)], expect)

    def test_asm_v2_loop(self):
        # CloseLoop: TEST i - (n-1); JUMP back if nonzero, incrementing i in the same instruction
        img, m = run("""
            REG_WR r1 imm #0
            REG_WR r2 imm #0
        LOOP:
            REG_WR r2 op -op(r2 + #3)
            TEST -op(r1 - #4)
            JUMP LOOP -if(NZ) -wr(r1 op) -op(r1 + #1)
            DMEM_WR [&0] op -op(r2)
            DMEM_WR [&1] op -op(r1)
            JUMP HERE
        """)
        self.assertEqual([dmem(img, m, 0), dmem(img, m, 1)], [15, 4])

    def test_conditional_write_leaves_flags_alone(self):
        # Resync: scratch = s11 + t -uf; scratch = 0 if negative
        img, m = run("""
            REG_WR r3 imm #-5
            REG_WR r1 op -op(r3 + #0) -uf
            REG_WR r1 op -op(s0) -if(S)
            DMEM_WR [&0] op -op(r1)
            REG_WR r2 op -op(r3 + #10) -uf
            REG_WR r2 op -op(s0) -if(S)
            DMEM_WR [&1] op -op(r2)
            JUMP HERE
        """)
        self.assertEqual([dmem(img, m, 0), dmem(img, m, 1)], [0, 5])

    def test_flag_f(self):
        img, m = run("""
            REG_WR r1 imm #0
            FLAG set
            REG_WR r1 op -op(r1 + #1) -if(F)
            FLAG inv
            REG_WR r1 op -op(r1 + #10) -if(F)
            REG_WR r1 op -op(r1 + #100) -if(NF)
            DMEM_WR [&0] op -op(r1)
            JUMP HERE
        """)
        self.assertEqual(dmem(img, m, 0), 101)

    def test_call_ret_nest(self):
        img, m = run("""
            REG_WR r1 imm #0
            CALL OUTER
            REG_WR r1 op -op(r1 + #1000)
            DMEM_WR [&0] op -op(r1)
            JUMP HERE
        OUTER:
            REG_WR r1 op -op(r1 + #1)
            CALL INNER
            REG_WR r1 op -op(r1 + #10)
            RET
        INNER:
            REG_WR r1 op -op(r1 + #100)
            RET
        """)
        self.assertEqual(dmem(img, m, 0), 1111)

    def test_end_publishes_done(self):
        img, m = run("REG_WR r1 imm #9\nJUMP HERE\nDMEM_WR [&0] op -op(r1)\n")
        self.assertEqual(dmem(img, m, 0), 0)
        self.assertEqual(m.load(img.symbols["__rq_status"]), rt.RQ_DONE)
        self.assertEqual(m.load(img.symbols["__rq_magic"]), rt.RQ_MAGIC)

    def test_s15_jumps(self):
        # big-pmem asm_v2 idioms: WriteLabel + JUMP s15, including end() as REG_WR s15 label NEXT
        img, m = run("""
            REG_WR r1 imm #0
            REG_WR s15 label SKIPPED
            JUMP s15
            REG_WR r1 imm #99
        SKIPPED:
            REG_WR r1 op -op(r1 + #1)
            DMEM_WR [&0] op -op(r1)
            REG_WR s15 label NEXT
            JUMP s15
            DMEM_WR [&0] imm #-1
        """)
        self.assertEqual(dmem(img, m, 0), 1)
        self.assertEqual(m.load(img.symbols["__rq_status"]), rt.RQ_DONE)

    def test_dynamic_s15_jump(self):
        # s15 picked at run time: the translator can't know it, so JUMP s15 goes through jalr
        img, m = run("""
            REG_WR r1 imm #1
            REG_WR s15 label A
            TEST -op(r1)
            JUMP PICKED -if(Z)
            REG_WR s15 label B
        PICKED:
            JUMP s15
        A:
            DMEM_WR [&0] imm #10
            JUMP HERE
        B:
            DMEM_WR [&0] imm #20
            JUMP HERE
        """)
        self.assertEqual(dmem(img, m, 0), 20)

    def test_program_list_input(self):
        plist = [{"CMD": "NOP", "P_ADDR": 0},
                 {"CMD": "REG_WR", "DST": "r1", "SRC": "imm", "LIT": "#3", "P_ADDR": 1},
                 {"CMD": "REG_WR", "DST": "r1", "SRC": "op", "OP": "r1 + #2", "P_ADDR": 2},
                 {"CMD": "TEST", "OP": "r1 - #11", "UF": "1", "P_ADDR": 3},
                 {"CMD": "JUMP", "LABEL": "top", "IF": "NZ", "P_ADDR": 4},
                 {"CMD": "DMEM_WR", "DST": "[&0]", "SRC": "op", "OP": "r1", "P_ADDR": 5},
                 {"CMD": "JUMP", "LABEL": "HERE", "P_ADDR": 6}]
        img, m = run((plist, {"top": "&2"}))
        self.assertEqual(dmem(img, m, 0), 11)


class TimingTest(unittest.TestCase):
    def test_wait_time(self):
        img, m = run("TIME inc_ref #1000\nWAIT time @200\nTIME inc_ref #500\nWAIT time @100\n"
                     "WAIT time @10\nJUMP HERE\n")
        t0 = m.start_time + rt.LEAD
        off = rt.WAIT_TIME_OFFSET
        self.assertEqual(len(m.waits), 3)
        for got, want in zip(m.waits[:2], (1200, 1600)):
            self.assertGreaterEqual(got, t0 + want - off - 3)
            self.assertLessEqual(got, t0 + want - off + 16)
        self.assertLess(m.waits[2] - m.waits[1], 10)     # already in the past: no stall

    def test_register_wait_polls_s11(self):
        # asm_v2 Wait with a 32-bit time: TEST s11 - t; JUMP HERE -if(S) -op(s11 - t) -uf
        img, m = run("""
            REG_WR r1 imm #3000
            TEST -op(s11 - r1)
            JUMP HERE -if(S) -op(s11 - r1) -uf
            REG_WR r2 op -op(s11)
            DMEM_WR [&0] op -op(r2)
            JUMP HERE
        """)
        self.assertGreaterEqual(dmem(img, m, 0), 3000)
        self.assertLess(dmem(img, m, 0), 3030)

    def test_set_ref_and_s11(self):
        img, m = run("TIME inc_ref #700\nTIME set_ref #50\nREG_WR r1 op -op(s11)\n"
                     "DMEM_WR [&0] op -op(r1)\nJUMP HERE\n")
        self.assertLess(abs(dmem(img, m, 0) - (-rt.LEAD - 50)), 20)


class OutputTest(unittest.TestCase):
    WAVES = [[0x12340000, 0x40000000, 3, 30000, 0x50064, 0x11, 0, 0],
             [0x0ABC0000, 0x1000, 9, 2000, 40, 0, 0, 0]]

    def test_wport_wr_from_wmem(self):
        target = rt.Target(wave_ports={1: rt.Channel(rt.RF_GATE, slot=2)})
        img, m = run("TIME inc_ref #10\nWPORT_WR p1 wmem [&1] @250\nJUMP HERE\n", target,
                     wmem=self.WAVES)
        writes = rf(m, rt.RF_GATE)
        slot = (2 + 1) * rt.RF_SLOT_STRIDE
        tref0 = writes[0][1]                       # init: startTime = now()
        self.assertEqual(writes[1:3], [(rt.RF_PHASE_OFFSET, 0), (rt.RF_DC_OFFSET, 0)])
        self.assertEqual(writes[3:], [
            (rt.RF_START_TIME, tref0 + rt.LEAD + 260),
            (rt.RF_FREQ, 0x0ABC0000),
            (slot + 0x0, 0x1000),
            (slot + 0x4, 2000 << 16),
            (slot + 0x8, 9),
            (slot + 0xC, 40),
            (rt.RF_FIRE, 2),
        ])

    def test_wport_wr_untimed_uses_s14_and_config_kind_does_not_fire(self):
        target = rt.Target(wave_ports={0: rt.Channel(rt.RF_DEMOD, kind="config")})
        img, m = run("REG_WR s14 imm #400\nWPORT_WR p0 wmem [&0]\nJUMP HERE\n", target,
                     wmem=self.WAVES)
        writes = rf(m, rt.RF_DEMOD)
        self.assertEqual(writes[3], (rt.RF_START_TIME, writes[0][1] + rt.LEAD + 400))
        self.assertEqual(writes[4], (rt.RF_FREQ, 0x12340000))
        self.assertEqual(writes[-1], (rt.RF_SLOT_STRIDE + 0xC, 0x64))   # length[15:0]
        self.assertNotIn(rt.RF_FIRE, [a for a, _ in writes])

    def test_wave_sweep_updates_wmem(self):
        # CloseLoop's wave sweep: ReadWmem, IncReg w_gain, WriteWmem, then play from r_wave
        target = rt.Target(wave_ports={2: rt.Channel(rt.RF_READOUT)})
        img, m = run("""
            REG_WR r_wave wmem [&1]
            REG_WR w3 op -op(w3 + #500)
            REG_WR w_freq op -op(w_freq + #1)
            WMEM_WR [&1]
            WPORT_WR p2 r_wave @0
            JUMP HERE
        """, target, wmem=self.WAVES)
        self.assertEqual(wmem(img, m, 1), [0x0ABC0001, 0x1000, 9, 2500, 40, 0])
        self.assertEqual(wmem(img, m, 0), [sx(v, 32) for v in self.WAVES[0][:6]])
        self.assertIn((rt.RF_SLOT_STRIDE + 0x4, 2500 << 16), rf(m, rt.RF_READOUT))

    def test_trig_and_dport(self):
        target = rt.Target(trig_ports={4: rt.Channel(rt.RF_DEMOD, kind="trigger")},
                           data_ports={1: rt.Channel(rt.RF_READOUT, slot=3, kind="trigger")})
        img, m = run("""
            TRIG set p4 @300
            TRIG clr p4 @310
            DPORT_WR p1 imm 5 @20
            DPORT_WR p1 imm 0 @30
            REG_WR r1 imm #0
            DPORT_WR p1 reg r1 @40
            REG_WR r1 imm #2
            DPORT_WR p1 reg r1 @3000
            JUMP HERE
        """, target)
        demod = [(a, v) for a, v in rf(m, rt.RF_DEMOD)]
        self.assertEqual([v for a, v in demod if a == rt.RF_FIRE], [0])
        ro = rf(m, rt.RF_READOUT)
        self.assertEqual([v for a, v in ro if a == rt.RF_FIRE], [3, 3])
        starts = [v for a, v in ro if a == rt.RF_START_TIME]
        self.assertEqual(starts[1] - starts[0], 2980)
        t_trig = [v for a, v in demod if a == rt.RF_START_TIME][0]
        self.assertEqual(starts[0] - t_trig, 20 - 300)

    def test_dport_rd(self):
        img, m = run("WAIT port_dt\nDPORT_RD p0\nDMEM_WR [&0] op -op(s8)\nDMEM_WR [&1] op -op(s9)\n"
                     "JUMP HERE\n")
        self.assertEqual([dmem(img, m, 0), dmem(img, m, 1)], [111, 222])

    def test_to_asm(self):
        asm = rt.to_asm("LOOP:\nREG_WR r1 imm #70000\nJUMP LOOP\n", wmem=self.WAVES)
        self.assertIn("main:", asm)
        self.assertIn("lui a0, 0x11", asm)
        self.assertIn(".Lq1:", asm)
        self.assertIn("jalr zero, 0(ra)", asm)
        self.assertIn("__qick_dmem:", asm)
        self.assertIn("__qick_wmem:", asm)
        self.assertIn(".word 0x0abc0000", asm)


class ProgramTest(unittest.TestCase):
    # AveragerProgramV2 output from firmware/notebooks/qick_testbench/test01_basic_multipulse.ipynb
    # (ConfigReadout, Delay, a reps loop with Trigger, Pulses, Wait/Delay auto, IncReg, End), with
    # the loop count raised from 1 to 3 and the pulse list shortened
    ASM = """
        NOP
        REG_WR s12 imm #0
        WPORT_WR p4 wmem [&2] @0
        TIME #430 inc_ref
        REG_WR r0 imm #0
    reps:
        TRIG p0 set @172
        TRIG p9 set @172
        TRIG p10 set @172
        TRIG p0 clr @182
        TRIG p9 clr @182
        TRIG p10 clr @182
        WPORT_WR p0 wmem [&0] @0
        WPORT_WR p0 wmem [&0] @2
        WPORT_WR p0 wmem [&1] @4
        WPORT_WR p0 wmem [&1] @6
        WAIT [&20] @602 time
        TIME #817 inc_ref
        REG_WR s12 op -op(s12 + #1)
        TEST -op(r0 - #2)
        JUMP reps -if(NZ) -wr(r0 op) -op(r0 + #1)
        JUMP HERE
    """
    WMEM = [[0x0d5acdac, 0, 0, 0x7ffe, 3, 8], [0x0d5acdac, 0x80000000, 3, 0x1fff, 3, 8],
            [0xcbeaaaae, 0, 0, 0, 3, 0x108]]
    TARGET = rt.Target(wave_ports={0: rt.Channel(rt.RF_GATE),
                                   4: rt.Channel(rt.RF_DEMOD, kind="config")},
                       trig_ports={9: rt.Channel(rt.RF_DEMOD, kind="trigger"),
                                   0: rt.Channel(0, kind="none"),      # PMOD pin
                                   10: rt.Channel(0, kind="none")})    # DDR4 buffer

    def test_averager_program(self):
        img, m = run(self.ASM, self.TARGET, wmem=self.WMEM)
        self.assertEqual(m.load(img.symbols["__rq_status"]), rt.RQ_DONE)
        gate, demod = rf(m, rt.RF_GATE), rf(m, rt.RF_DEMOD)
        t0 = gate[0][1]                         # init: startTime = now()
        ref = [rt.LEAD + 430 + 817 * i for i in range(3)]
        self.assertEqual([v - t0 for a, v in gate if a == rt.RF_START_TIME][1:],
                         [r + dt for r in ref for dt in (0, 2, 4, 6)])
        self.assertEqual([v for a, v in gate if a == rt.RF_FIRE], [0] * 12)
        self.assertEqual([v - t0 for a, v in demod if a == rt.RF_START_TIME][1:],
                         [rt.LEAD] + [r + 172 for r in ref])
        self.assertEqual([v for a, v in demod if a == rt.RF_FIRE], [0] * 3)
        self.assertEqual([w - t0 for w in m.waits], [r + 602 - rt.WAIT_TIME_OFFSET - 3 for r in ref])
        self.assertIn((rt.RF_FREQ, 0xcbeaaaae), demod)
        # every batch is written before it is due
        for tm, a, v in m.mmio:
            if a & 0xFFFF == rt.RF_START_TIME and tm > m.start_time + 20:
                self.assertLess(tm, v, "late schedule at %#x" % a)


class ErrorTest(unittest.TestCase):
    def check(self, src, msg, target=None, **kw):
        with self.assertRaisesRegex(rt.TranslateError, msg):
            rt.to_image(src, target, **kw)

    def test_errors(self):
        self.check("JUMP NOWHERE\n", "undefined label|unrecognized label")
        self.check("WPORT_WR p3 wmem [&0]\n", "wave port 3 has no RISC-Q Channel")
        self.check("TRIG set p5\n", "trigger port 5 has no RISC-Q Channel")
        self.check("WPORT_WR p3 wmem [&0]\n", "kind 'pulse', 'config' or 'none'",
                   rt.Target(wave_ports={3: rt.Channel(rt.RF_GATE, kind="trigger")}))
        self.check("DMEM_WR [&256] imm #1\n", "outside the 256-word")
        self.check("REG_WR r1 op -op(s1)\n", "LFSR")
        self.check("NET set_net\n", "QNET")
        self.check("FROB r1\n", "assembler")


if __name__ == "__main__":
    unittest.main()
