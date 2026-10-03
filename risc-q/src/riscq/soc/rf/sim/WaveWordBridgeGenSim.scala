package riscq.soc.rf.sim

import spinal.core._
import spinal.core.sim._
import spinal.lib._
import riscq.soc.link.RfCmd
import riscq.soc.rf.{WaveWordBridge, WaveWordBridgeParams}

/**
 * Tier-1 integration: connect WaveWordBridge to QICK's REAL `sg_translator.v` (pure Verilog,
 * combinational) and confirm our 168-bit word is translated into the correct 160-bit gen_v6 command.
 * (The full axis_signal_gen_v6 — VHDL + DDS Compiler sub-IP — needs Vivado xsim, done separately.)
 *
 * Run:  mill runMain riscq.soc.rf.sim.WaveWordBridgeGenSim
 */

/** SpinalHDL BlackBox around firmware/ip/qick_sg_translator/src/sg_translator.v (OUT_TYPE=0 = gen_v6). */
class SgTranslator(outType: Int = 0) extends BlackBox {
  val io = new Bundle {
    val aresetn              = in  Bool()
    val aclk                 = in  Bool()
    val s_axis_tdata         = in  Bits(168 bits)
    val s_axis_tvalid        = in  Bool()
    val s_axis_tready        = out Bool()
    val m_gen_v6_axis_tdata  = out Bits(160 bits)
    val m_gen_v6_axis_tvalid = out Bool()
    val m_gen_v6_axis_tready  = in  Bool()
    val m_int4_axis_tdata    = out Bits(88 bits)
    val m_int4_axis_tvalid   = out Bool()
    val m_int4_axis_tready    = in  Bool()
    val m_mux4_axis_tdata    = out Bits(40 bits)
    val m_mux4_axis_tvalid   = out Bool()
    val m_mux4_axis_tready    = in  Bool()
    val m_readout_axis_tdata    = out Bits(88 bits)
    val m_readout_axis_tvalid   = out Bool()
    val m_readout_axis_tready    = in  Bool()
  }
  setDefinitionName("sg_translator")
  addGeneric("OUT_TYPE", outType)
  noIoPrefix()
  addRTLPath(new java.io.File("../firmware/ip/qick_sg_translator/src/sg_translator.v").getCanonicalPath) // repo-relative (mill runs from risc-q/)
}

/** Wrapper: WaveWordBridge → sg_translator, exposing the bridge inputs and the gen_v6 output. */
case class BridgeToGen(p: WaveWordBridgeParams = WaveWordBridgeParams()) extends Component {
  val io = new Bundle {
    val cmd      = slave port Flow(RfCmd(p.addrWidth))
    val time     = in    port UInt(p.timeWidth bits)
    val genWord  = out   port Bits(160 bits)   // the translated gen_v6 command
    val genValid = out   port Bool()
    val trig     = out   port Bool()
  }

  val bridge = WaveWordBridge(p)
  bridge.io.cmd.valid   := io.cmd.valid
  bridge.io.cmd.payload := io.cmd.payload
  bridge.io.time        := io.time
  io.trig               := bridge.io.trig

  val tr = new SgTranslator(outType = 0)
  tr.io.aclk    := ClockDomain.current.readClockWire   // combinational block; clock unused inside
  tr.io.aresetn := True
  tr.io.s_axis_tdata  := bridge.io.wave.payload
  tr.io.s_axis_tvalid := bridge.io.wave.valid
  bridge.io.wave.ready := tr.io.s_axis_tready
  tr.io.m_gen_v6_axis_tready  := True
  tr.io.m_int4_axis_tready    := False
  tr.io.m_mux4_axis_tready    := False
  tr.io.m_readout_axis_tready := False

  io.genWord  := tr.io.m_gen_v6_axis_tdata
  io.genValid := tr.io.m_gen_v6_axis_tvalid
}

object WaveWordBridgeGenSim extends App {
  val lead = 8
  val p    = WaveWordBridgeParams(leadTime = lead)

  // sg_translator.v uses implicit nets (gen_v6_en/int4_en/…); Verilator errors on those by default.
  SimConfig.withFstWave.addSimulatorFlag("-Wno-IMPLICIT").compile(BridgeToGen(p)).doSim("bridgeToGen") { dut =>
    dut.clockDomain.forkStimulus(10)

    def wr(addr: Int, data: BigInt): Unit = {
      dut.io.cmd.valid #= true
      dut.io.cmd.payload.address #= addr
      dut.io.cmd.payload.data #= data
      dut.clockDomain.waitSampling()
      dut.io.cmd.valid #= false
      dut.clockDomain.waitSampling()
    }

    dut.io.cmd.valid #= false
    dut.io.time #= 0
    dut.clockDomain.waitSampling(5)

    val FREQ  = BigInt("11111111", 16)
    val PHASE = BigInt("22222222", 16)
    val ENV   = BigInt("333333", 16)   // 24-bit; gen_v6 addr takes low 16 → 0x3333
    val GAIN  = BigInt("4444abcd", 16) // gen_v6 gain takes low 16 → 0xabcd
    val NSAMP = BigInt("00000060", 16) // gen_v6 nsamp takes low 16 → 0x0060
    val CONF  = BigInt("0008", 16)     // stdysel = 1 (bit 3)
    val START = 200

    wr(p.freqAddr, FREQ)
    wr(p.phaseAddr, PHASE)
    wr(p.envAddr, ENV)
    wr(p.gainAddr, GAIN)
    wr(p.nsampAddr, NSAMP)
    wr(p.confAddr, CONF)
    wr(p.startTimeAddr, START)
    wr(p.fireAddr, 0)

    // program a trigger: rises at trigTime - leadTrig, stays high for width cycles
    val TRIGT = 210
    val WIDTH = 10
    wr(p.trigTimeAddr, TRIGT)
    wr(p.widthAddr, WIDTH)
    wr(p.fireTrigAddr, 0)

    var t = 0
    var firedAt = -1
    var gw = BigInt(0)
    var trigRiseAt = -1
    var trigHigh = 0
    while (t < TRIGT + 30) {   // run past both the pulse pop and the trigger window
      dut.io.time #= t
      dut.clockDomain.waitSampling()
      if (dut.io.genValid.toBoolean && firedAt < 0) {
        firedAt = t; gw = dut.io.genWord.toBigInt
        println(s"[WaveWordBridgeGenSim] genValid HIGH at io.time=$t, simTime=${simTime()}")
      }
      if (dut.io.trig.toBoolean) {
        if (trigRiseAt < 0) trigRiseAt = t
        trigHigh += 1
      }
      t += 1
    }

    println(s"[WaveWordBridgeGenSim] trig rose at io.time=$trigRiseAt, high for $trigHigh cycles " +
            s"(expected rise ~${TRIGT - p.leadTrig}, width $WIDTH)")
    assert(trigRiseAt >= 0, "trigger never rose")
    assert(scala.math.abs(trigRiseAt - (TRIGT - p.leadTrig)) <= 2, s"trig rose at $trigRiseAt, expected ~${TRIGT - p.leadTrig}")
    assert(trigHigh == WIDTH, s"trig high for $trigHigh cycles, expected $WIDTH")

    println(s"[WaveWordBridgeGenSim] gen_v6 command valid at time=$firedAt (expected ~${START - lead})")
    println(s"[WaveWordBridgeGenSim] gen_v6 word = 0x${gw.toString(16)}")

    def f(hi: Int, lo: Int): BigInt = (gw >> lo) & ((BigInt(1) << (hi - lo + 1)) - 1)
    def check(n: String, got: BigInt, exp: BigInt): Unit =
      assert(got == exp, s"$n mismatch: got 0x${got.toString(16)}, expected 0x${exp.toString(16)}")

    assert(firedAt >= 0, "gen_v6 command never appeared")
    // gen_v6 layout (sg_translator.v:82-97): freq/phase full, addr/gain/nsamp truncated to 16, conf bits split
    check("freq",    f(31, 0),    FREQ)
    check("phase",   f(63, 32),   PHASE)
    check("addr",    f(79, 64),   ENV   & BigInt("ffff", 16))
    check("gain",    f(111, 96),  GAIN  & BigInt("ffff", 16))
    check("nsamp",   f(143, 128), NSAMP & BigInt("ffff", 16))
    check("outsel",  f(145, 144), CONF        & 0x3)
    check("mode",    f(146, 146), (CONF >> 2) & 0x1)
    check("stdysel", f(147, 147), (CONF >> 3) & 0x1)
    check("phrst",   f(148, 148), (CONF >> 4) & 0x1)

    println("[WaveWordBridgeGenSim] PASS — bridge word feeds the real sg_translator and yields the correct gen_v6 command")
  }
}
