package riscq.soc.sim

import spinal.core._
import spinal.core.sim._
import riscq.soc.comm.QickCom

/**
 * Two [[QickCom]] cores wired back-to-back over their PMOD pins — the minimal "two boards on a
 * cable" rig. `a` transmits, `b` receives; each one's `pmod_o` drives the other's `pmod_i`, which
 * is exactly how two chassis are cabled.
 */
class QickComPair(maxPulseDelay: Int = 64) extends Component {
  val io = new Bundle {
    val cfg  = in Bits (4 bits)   // link symbol period, in core clocks
    val req  = in Bool ()
    val op   = in Bits (4 bits)
    val dt   = in Bits (32 bits)
    val ack  = out Bool ()
    val rdy  = out Bool ()
    val dt1  = out Bits (32 bits) // b's received register 1
    val dt2  = out Bits (32 bits) // b's received register 2
    val vld  = out Bool ()        // b's one-cycle "a register was written" pulse
    val flag = out Bool ()        // b's sticky flag
    val wire = out Bits (4 bits)  // the link itself, for eyeballing waveforms
    val pulse  = in Bool ()       // the shared external sync tick, as board A sees it
    val bDelay = in UInt (7 bits) // cycles by which board B's copy of the tick is LATE
    val aStart = out Bool ()      // a's qproc_start_o — the sync firing
    val bStart = out Bool ()      // b's qproc_start_o
  }

  val a = QickCom().driveClocksFrom(clockDomain)
  val b = QickCom().driveClocksFrom(clockDomain)

  for (q <- List(a, b)) {
    q.io.qcom_cfg_i := io.cfg
  }

  // Board B sees the reference tick `bDelay` cycles late — real boards are not handed a
  // zero-skew tick, so this is the knob that makes the alignment claim falsifiable.
  val tickChain = Vec(Bool(), maxPulseDelay + 1)
  tickChain(0) := io.pulse
  for (i <- 1 to maxPulseDelay) tickChain(i) := RegNext(tickChain(i - 1)) init False
  a.io.pulse_i := io.pulse
  b.io.pulse_i := tickChain(io.bDelay.resize(log2Up(maxPulseDelay + 1)))

  // a is the sender
  a.io.cmd_req_i := io.req
  a.io.cmd_op_i  := io.op
  a.io.cmd_dt_i  := io.dt

  // b never sends
  b.io.cmd_req_i := False
  b.io.cmd_op_i  := 0
  b.io.cmd_dt_i  := 0

  // the cable
  b.io.pmod_i := a.io.pmod_o
  a.io.pmod_i := b.io.pmod_o

  io.ack  := a.io.cmd_ack_o
  io.rdy  := a.io.qcom_rdy_o
  io.dt1  := b.io.qcom_dt1_o
  io.dt2  := b.io.qcom_dt2_o
  io.vld  := b.io.qcom_vld_o
  io.flag := b.io.qcom_flag_o
  io.wire   := a.io.pmod_o
  io.aStart := a.io.qproc_start_o
  io.bStart := b.io.qproc_start_o
}

/**
 * First light for the communication track: proves QICK's protocol core builds and runs inside
 * RISC-Q's own simulator, and that a packet issued on one board lands in the peer's registers.
 *
 * Scenarios: a 32-bit word to the peer's `dt1`, a second to its `dt2` (exercising the destination
 * bit), and flag set/clear (the 1-symbol packet path). Each asserts the payload arrives intact and
 * reports the observed link latency in core clocks.
 *
 * Run with `mill runMain riscq.soc.sim.QickComSim`.
 */
object QickComSim extends App {
  val tickCfg  = 8     // symbol period in core clocks
  val maxWait  = 8000  // generous bound; a 32-bit packet is 12 symbols

  // RISCQ_WAVES=1 dumps a VCD of the link (simWorkspace/QickComPair/*.vcd)
  val base = if (sys.env.contains("RISCQ_WAVES")) SimConfig.withWave else SimConfig
  val compiled = QickCom.rtlSources
    .foldLeft(base.addSimulatorFlag("-Wno-fatal"))((cfg, src) => cfg.addRtl(src))
    .compile(new QickComPair)

  compiled.doSim("qickcom_link", seed = 42) { dut =>
    dut.clockDomain.forkStimulus(10)
    dut.io.cfg #= tickCfg
    dut.io.req   #= false
    dut.io.op    #= 0
    dut.io.dt    #= 0
    dut.io.pulse  #= false         // data packets do not use the sync tick
    dut.io.bDelay #= 0
    dut.clockDomain.waitSampling(50)

    /** Issue one command on `a` and wait for `b` to report a received register write. */
    def send(op: Int, data: BigInt, what: String): Int = {
      assert(dut.io.rdy.toBoolean, s"$what: sender was not ready before the command")
      dut.io.dt  #= data
      dut.io.op  #= op
      dut.io.req #= true

      var guard = 0
      while (!dut.io.ack.toBoolean && guard < 100) { dut.clockDomain.waitSampling(); guard += 1 }
      assert(guard < 100, s"$what: command never acknowledged (cmd_ack_o stayed low)")
      dut.io.req #= false

      var cycles = guard
      var seen   = false
      while (!seen && cycles < maxWait) {
        dut.clockDomain.waitSampling(); cycles += 1
        seen = dut.io.vld.toBoolean
      }
      cycles
    }

    // ── 32-bit payload to the peer's dt1 ──
    val p1 = BigInt("deadbeef", 16)
    val c1 = send(QickCom.Op.send32Dt1, p1, "32-bit → dt1")
    assert(c1 < maxWait, s"32-bit → dt1: nothing received within $maxWait cycles")
    val r1 = dut.io.dt1.toBigInt
    assert(r1 == p1, f"32-bit → dt1: got 0x$r1%x, expected 0x$p1%x")
    println(f"[QickComSim] 32-bit → dt1 : 0x$p1%08x received intact in $c1 core clocks")

    dut.clockDomain.waitSampling(100)

    // ── 32-bit payload to the peer's dt2 (destination bit flipped) ──
    val p2 = BigInt("0f1e2d3c", 16)
    val c2 = send(QickCom.Op.send32Dt2, p2, "32-bit → dt2")
    assert(c2 < maxWait, s"32-bit → dt2: nothing received within $maxWait cycles")
    val r2 = dut.io.dt2.toBigInt
    assert(r2 == p2, f"32-bit → dt2: got 0x$r2%x, expected 0x$p2%x")
    assert(dut.io.dt1.toBigInt == p1, "32-bit → dt2: clobbered dt1")
    println(f"[QickComSim] 32-bit → dt2 : 0x$p2%08x received intact in $c2 core clocks (dt1 untouched)")

    dut.clockDomain.waitSampling(100)

    // ── flag set / clear: the 1-symbol packet path ──
    assert(!dut.io.flag.toBoolean, "flag: expected clear at start")
    var g = 0
    dut.io.op #= QickCom.Op.setFlag; dut.io.dt #= 0; dut.io.req #= true
    while (!dut.io.ack.toBoolean && g < 100) { dut.clockDomain.waitSampling(); g += 1 }
    dut.io.req #= false
    var fc = g
    while (!dut.io.flag.toBoolean && fc < maxWait) { dut.clockDomain.waitSampling(); fc += 1 }
    assert(dut.io.flag.toBoolean, s"flag: never set within $maxWait cycles")
    println(s"[QickComSim] flag set     : peer flag raised in $fc core clocks")

    dut.clockDomain.waitSampling(100)
    g = 0
    dut.io.op #= QickCom.Op.clearFlag; dut.io.req #= true
    while (!dut.io.ack.toBoolean && g < 100) { dut.clockDomain.waitSampling(); g += 1 }
    dut.io.req #= false
    var cc = g
    while (dut.io.flag.toBoolean && cc < maxWait) { dut.clockDomain.waitSampling(); cc += 1 }
    assert(!dut.io.flag.toBoolean, s"flag: never cleared within $maxWait cycles")
    println(s"[QickComSim] flag clear   : peer flag lowered in $cc core clocks")

    println(s"[QickComSim] PASS — qick_com runs inside RISC-Q's simulator; board-to-board link verified (tick_cfg=$tickCfg).")
  }
}

/**
 * Multi-board SYNC: the mechanism RISC-Q must replace.
 *
 * QICK's SYNC command (`cmd_op_i = 0xa`) does '''not''' create synchronization out of nothing — it
 * coordinates which edge of an already-shared reference tick (`pulse_i`, in hardware a common
 * SYSREF-style signal) both boards act on:
 *
 *   1. the sender parks in `TX_WSYNC` until the next `pulse_i` rising edge, then transmits;
 *   2. the receiver decodes the SYNC header and raises its own `rx_sync`;
 *   3. '''both''' sides then wait for the next `pulse_i` edge and assert `qproc_start_o` on it.
 *
 * So alignment is exact whenever the tick period exceeds the link latency — both boards latch the
 * same edge. When the period is shorter, the receiver misses the edge the sender caught and fires a
 * period late. This sweep finds that boundary and reports the skew in core clocks.
 *
 * Why it matters for RISC-Q: `qproc_start_o` restarts QICK's tProcessor. RISC-Q has no processor to
 * restart — the intended target is the SoC's `timeOffset` register, so that a sync realigns the
 * shared `time` counter every `TimedQueue` compares against. The skew measured here is the floor on
 * how well two RISC-Q boards could agree on `time` using this link.
 *
 * Run with `mill runMain riscq.soc.sim.QickComSyncSim`.
 */
object QickComSyncSim extends App {
  val tickCfg = 8
  val periods = Seq(600)          // shared-tick period, in core clocks
  val skews   = (0 to 24) ++ Seq(40, 80)  // cycles by which board B's copy of the tick is late
  val watchWindow = 4000   // fixed observation window per trial
  val ackBudget   = 200    // fixed budget for the command handshake

  val compiled = QickCom.rtlSources
    .foldLeft(SimConfig.addSimulatorFlag("-Wno-fatal"))((cfg, src) => cfg.addRtl(src))
    .compile(new QickComPair)

  compiled.doSim("qickcom_sync", seed = 42) { dut =>
    dut.clockDomain.forkStimulus(10)
    dut.io.cfg   #= tickCfg
    dut.io.req   #= false
    dut.io.op    #= 0
    dut.io.dt    #= 0
    dut.io.pulse  #= false
    dut.io.bDelay #= 0

    // The shared reference tick, driven to BOTH boards. Period is retuned between trials.
    var halfPeriod = periods.head / 2
    var tickLevel  = false
    fork {
      while (true) {
        dut.clockDomain.waitSampling(halfPeriod)
        tickLevel = !tickLevel
        dut.io.pulse #= tickLevel
      }
    }

    dut.clockDomain.waitSampling(100)
    println(f"[QickComSyncSim] tick_cfg=$tickCfg%d, tick period=${periods.head}%d core clocks")
    println("[QickComSyncSim] board B's copy of the reference tick is delayed by `bDelay`:")
    println("[QickComSyncSim]   bDelay   a fires   b fires   skew")

    val results = for (d <- skews) yield {
      dut.io.bDelay #= d
      dut.clockDomain.waitSampling(2 * periods.head) // settle

      dut.io.op  #= QickCom.Op.sync
      dut.io.dt  #= 0
      dut.io.req #= true
      var g = 0
      while (!dut.io.ack.toBoolean && g < ackBudget) { dut.clockDomain.waitSampling(); g += 1 }
      assert(g < ackBudget, s"bDelay=$d: SYNC command never acknowledged")
      dut.io.req #= false
      dut.clockDomain.waitSampling(ackBudget - g)   // pad, so the trial length is constant

      var t = 0; var aAt = -1; var bAt = -1
      while (t < watchWindow) {                 // FIXED length — keeps every trial in phase
        dut.clockDomain.waitSampling(); t += 1
        if (aAt < 0 && dut.io.aStart.toBoolean) aAt = t
        if (bAt < 0 && dut.io.bStart.toBoolean) bAt = t
      }
      val skew = if (aAt >= 0 && bAt >= 0) bAt - aAt else Int.MinValue
      val cell = (v: Int) => if (v < 0) "  never" else f"$v%7d"
      println(f"[QickComSyncSim] $d%8d ${cell(aAt)} ${cell(bAt)} ${if (skew == Int.MinValue) "     --" else f"$skew%6d"}")

      dut.clockDomain.waitSampling(3 * periods.head)   // fixed drain
      (d, aAt, bAt, skew)
    }

    val fired = results.filter { case (_, a, b, _) => a >= 0 && b >= 0 }
    assert(fired.nonEmpty, "SYNC never fired on both boards at any tick skew")

    val period    = periods.head
    val sameEdge  = fired.filter { case (_, _, _, sk) => sk.abs < period / 2 }
    val otherEdge = fired.filter { case (_, _, _, sk) => sk.abs >= period / 2 }

    println()
    println(f"[QickComSyncSim] ── RESULT ──")
    println(f"[QickComSyncSim] same tick edge  (skew == bDelay, boards agree): bDelay = ${sameEdge.map(_._1).mkString(", ")}")
    println(f"[QickComSyncSim] DIFFERENT edge  (boards a full period apart)  : bDelay = ${otherEdge.map(_._1).mkString(", ")}")

    sameEdge.foreach { case (d, _, _, sk) =>
      assert(sk == d, f"bDelay=$d landed on the same edge but skew $sk != $d")
    }
    otherEdge.foreach { case (d, _, _, sk) =>
      assert(sk.abs > period / 2, f"bDelay=$d classified as a different edge but skew is only $sk")
    }

    if (otherEdge.nonEmpty) {
      val boundary = otherEdge.map(_._1).min
      println()
      println(f"[QickComSyncSim] *** QICK's SYNC has a RACE WINDOW. ***")
      println(f"[QickComSyncSim] Up to bDelay=${boundary - 1}%d the boards latch the SAME reference-tick edge and their")
      println(f"[QickComSyncSim] skew equals the tick skew exactly — the link adds no error of its own.")
      println(f"[QickComSyncSim] From bDelay=$boundary%d the receiver becomes ready on the far side of an edge and")
      println(f"[QickComSyncSim] latches a DIFFERENT one: the boards end up a full tick period ($period%d clocks) apart,")
      println(f"[QickComSyncSim] with no error reported anywhere.")
      println(f"[QickComSyncSim] => a RISC-Q sync protocol needs a guard band: the receiver must be ready well")
      println(f"[QickComSyncSim]    before the target edge, by more than the worst-case link latency spread.")
    }
    println(f"[QickComSyncSim] PASS — behaviour characterised across ${fired.size}/${skews.size} tick skews.")
  }
}

/**
 * Guard-band map for QICK's SYNC: how much reference-tick skew the link tolerates, as a function of
 * '''when''' the sync command is issued relative to a tick edge.
 *
 * [[QickComSyncSim]] showed the two boards either latch the same tick edge (and their skew equals
 * the tick skew exactly) or latch different ones (and end up a full tick period apart, silently).
 * The boundary it found was measured at a single command-to-edge phase, so it is not yet a budget.
 * This sweeps that phase across a whole tick period and reports, for every phase, the largest tick
 * skew that still keeps both boards on the same edge.
 *
 * The '''minimum''' of that curve is the real guard band: the tick skew a RISC-Q sync protocol can
 * tolerate no matter when the command happens to be issued.
 *
 * Run with `mill runMain riscq.soc.sim.QickComGuardSim`.
 */
object QickComGuardSim extends App {
  val tickCfg     = 8
  val period      = 600                      // shared-tick period, in core clocks
  val phases      = 0 until period by 50     // command issue point within the tick period
  val delays      = 0 to 28                  // tick skew applied to board B
  val watchWindow = 1400                     // > 2 tick periods: enough to see both boards fire
  val ackBudget   = 200

  val compiled = QickCom.rtlSources
    .foldLeft(SimConfig.addSimulatorFlag("-Wno-fatal"))((cfg, src) => cfg.addRtl(src))
    .compile(new QickComPair)

  compiled.doSim("qickcom_guard", seed = 42) { dut =>
    dut.clockDomain.forkStimulus(10)
    dut.io.cfg #= tickCfg; dut.io.req #= false; dut.io.op #= 0
    dut.io.dt  #= 0;       dut.io.pulse #= false; dut.io.bDelay #= 0

    // Deterministic reference tick: `tickPos` is the position within the period, so the main
    // thread can issue a command at an exact phase. Rising edge is at tickPos == 0.
    var tickPos = 0
    fork {
      while (true) {
        dut.clockDomain.waitSampling()
        tickPos = (tickPos + 1) % period
        dut.io.pulse #= tickPos < period / 2
      }
    }
    dut.clockDomain.waitSampling(2 * period)

    /** One trial: issue SYNC at `phase` with board B's tick `d` cycles late. True = same edge. */
    def trial(phase: Int, d: Int): Boolean = {
      dut.io.bDelay #= d
      while (tickPos != phase) dut.clockDomain.waitSampling()

      dut.io.op #= QickCom.Op.sync; dut.io.dt #= 0; dut.io.req #= true
      var g = 0
      while (!dut.io.ack.toBoolean && g < ackBudget) { dut.clockDomain.waitSampling(); g += 1 }
      dut.io.req #= false
      dut.clockDomain.waitSampling(ackBudget - g)

      var t = 0; var aAt = -1; var bAt = -1
      while (t < watchWindow) {
        dut.clockDomain.waitSampling(); t += 1
        if (aAt < 0 && dut.io.aStart.toBoolean) aAt = t
        if (bAt < 0 && dut.io.bStart.toBoolean) bAt = t
      }
      dut.clockDomain.waitSampling(2 * period) // drain
      aAt >= 0 && bAt >= 0 && (bAt - aAt) == d // same edge <=> board skew == tick skew, exactly
    }

    println(f"[QickComGuardSim] tick_cfg=$tickCfg%d, tick period=$period%d core clocks")
    println(f"[QickComGuardSim] sweeping ${phases.size}%d command phases x ${delays.size}%d tick skews")
    println("[QickComGuardSim]   phase   max safe tick skew")

    val perPhase = for (phase <- phases) yield {
      // largest d for which every skew 0..d stays on the same edge
      var safe = -1
      var d    = 0
      var ok   = true
      while (ok && d <= delays.last) {
        if (trial(phase, d)) { safe = d; d += 1 } else ok = false
      }
      val note = if (safe >= delays.last) s">= ${delays.last}" else s"$safe"
      println(f"[QickComGuardSim] $phase%7d   $note%18s")
      (phase, safe)
    }

    val worst      = perPhase.map(_._2).min
    val worstPhase = perPhase.filter(_._2 == worst).map(_._1)
    val best       = perPhase.map(_._2).max

    println()
    println(f"[QickComGuardSim] ── GUARD BAND ──")
    println(f"[QickComGuardSim] best  case: $best%d cycles of tick skew tolerated")
    println(f"[QickComGuardSim] WORST case: $worst%d cycles, at command phase(s) ${worstPhase.mkString(", ")}")
    println(f"[QickComGuardSim] => a sync issued at an ARBITRARY time is only safe if the reference tick")
    println(f"[QickComGuardSim]    is distributed to within $worst%d core clocks across boards.")
    if (worst < best)
      println(f"[QickComGuardSim] => issuing the sync at a CONTROLLED phase widens that to $best%d cycles — i.e. the")
    if (worst < best)
      println(f"[QickComGuardSim]    protocol should pick when to sync, not sync on demand.")
    assert(best >= 0, "no phase tolerated even a perfectly shared tick")
    println(f"[QickComGuardSim] PASS — guard band mapped across the full tick period.")
  }
}
