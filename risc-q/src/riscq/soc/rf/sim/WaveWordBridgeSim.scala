package riscq.soc.rf.sim

import spinal.core._
import spinal.core.sim._
import riscq.soc.rf.{WaveWordBridge, WaveWordBridgeParams}

/**
 * SpinalSim check for [[riscq.soc.rf.WaveWordBridge]]:
 *   - program a pulse's fields, fire it, and confirm the 168-bit word pops at `startTime − leadTime`
 *     with every field correct;
 *   - program a trigger (time + width), fire it, and confirm the 1-bit trigger rises near
 *     `trigTime − leadTrig` and stays high for exactly `width` cycles.
 *
 * Run:  mill runMain riscq.soc.rf.sim.WaveWordBridgeSim
 */
object WaveWordBridgeSim extends App {
  val lead = 8
  val p    = WaveWordBridgeParams(leadTime = lead)  // leadTrig defaults to 8 too

  SimConfig.withFstWave.compile(WaveWordBridge(p)).doSim("waveWordBridge") { dut =>
    dut.clockDomain.forkStimulus(10)

    // write one register: address + data, one valid cycle
    def wr(addr: Int, data: BigInt): Unit = {
      dut.io.cmd.valid #= true
      dut.io.cmd.payload.address #= addr
      dut.io.cmd.payload.data #= data
      dut.clockDomain.waitSampling()
      dut.io.cmd.valid #= false
      dut.clockDomain.waitSampling()
    }

    // init
    dut.io.cmd.valid #= false
    dut.io.time #= 0
    dut.io.wave.ready #= true
    dut.clockDomain.waitSampling(5)

    // ── program a pulse ──
    val FREQ  = BigInt("11111111", 16)
    val PHASE = BigInt("22222222", 16)
    val ENV   = BigInt("333333", 16)     // 24-bit
    val GAIN  = BigInt("44444444", 16)
    val NSAMP = BigInt("00000060", 16)   // length
    val CONF  = BigInt("0008", 16)       // stdysel = 1
    val START = 200

    wr(p.freqAddr, FREQ)
    wr(p.phaseAddr, PHASE)
    wr(p.envAddr, ENV)
    wr(p.gainAddr, GAIN)
    wr(p.nsampAddr, NSAMP)
    wr(p.confAddr, CONF)
    wr(p.startTimeAddr, START)
    wr(p.fireAddr, 0) // fire the pulse

    // ── program a trigger ──
    val TRIGT = 250
    val WIDTH = 10
    wr(p.trigTimeAddr, TRIGT)
    wr(p.widthAddr, WIDTH)
    wr(p.fireTrigAddr, 0) // fire the trigger

    // ── advance time; watch the wave pop and the trigger level ──
    var t          = 0
    var firedAt    = -1
    var payload    = BigInt(0)
    var trigRiseAt = -1
    var trigHigh   = 0
    val tEnd       = TRIGT + WIDTH + 20
    while (t < tEnd) {
      dut.io.time #= t
      dut.clockDomain.waitSampling()
      if (dut.io.wave.valid.toBoolean && firedAt < 0) {
        firedAt = t
        payload = dut.io.wave.payload.toBigInt
      }
      if (dut.io.trig.toBoolean) {
        if (trigRiseAt < 0) trigRiseAt = t
        trigHigh += 1
      }
      t += 1
    }

    println(s"[WaveWordBridgeSim] wave fired at time=$firedAt (expected ~${START - lead})")
    println(s"[WaveWordBridgeSim] trig rose at time=$trigRiseAt, high for $trigHigh cycles " +
            s"(expected rise ~${TRIGT - p.leadTrig}, width $WIDTH)")

    // ── pulse: field checks (strict) ──
    def field(hi: Int, lo: Int): BigInt = (payload >> lo) & ((BigInt(1) << (hi - lo + 1)) - 1)
    def check(name: String, got: BigInt, exp: BigInt): Unit =
      assert(got == exp, s"$name mismatch: got 0x${got.toString(16)}, expected 0x${exp.toString(16)}")

    assert(firedAt >= 0, "wave never fired")
    check("freq",   field(31, 0),    FREQ)
    check("phase",  field(63, 32),   PHASE)
    check("env",    field(87, 64),   ENV)
    check("gain",   field(119, 88),  GAIN)
    check("length", field(151, 120), NSAMP)
    check("conf",   field(167, 152), CONF)

    // ── pulse: timing (tolerance) ──
    assert(math.abs(firedAt - (START - lead)) <= 2, s"pulse fired at $firedAt, expected ~${START - lead}")

    // ── trigger: rise near trigTime - leadTrig, high for exactly `width` cycles ──
    assert(trigRiseAt >= 0, "trigger never rose")
    assert(math.abs(trigRiseAt - (TRIGT - p.leadTrig)) <= 2, s"trig rose at $trigRiseAt, expected ~${TRIGT - p.leadTrig}")
    assert(trigHigh == WIDTH, s"trig high for $trigHigh cycles, expected $WIDTH")

    println("[WaveWordBridgeSim] PASS — pulse word packed + timed, trigger rose on schedule and held for width")
  }
}
