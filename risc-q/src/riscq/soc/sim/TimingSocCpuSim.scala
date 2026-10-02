package riscq.soc.sim

import spinal.core._
import spinal.core.sim._
import spinal.lib._
import spinal.lib.misc.Elf
import spinal.lib.sim.SparseMemory
import spinal.lib.bus.amba4.axi.sim.Axi4Master
import riscq.soc.PulseTableSoc
import riscq.soc.rf.PulseDriveChannel
import riscq.dsp.pulse.PulseGenerator

import java.io.{File, PrintWriter}

/**
 * Controller-level timing event logger for native RISC-Q (CPU-in-the-loop), the RISC-Q side of the
 * QICK timing characterization in verification/timing/ (see timing_contract.txt there).
 *
 * Same boot flow as [[PulseTableSocCpuSim]] (program + gate envelope over AXI, reset release via the
 * host control block), but instead of asserting it logs one CSV row per event for each drive channel
 * of core 0 (gate = ch0, readout drive = ch1), in dspCd, with the batch `time` on every row:
 *
 *   E0i  CPU posted store of a channel's fire register      (riscvSoc.cmd, before linkPipe + demux)
 *   E0   fire decoded by the channel's PulseParamBuffer       (buf.outParamValid)
 *   E1   dur TimedQueue push; due = startTime captured         (buf.io.dur.valid, buf.io.startTime)
 *   E2   dur TimedQueue pop (+ pop cycle of every queue)       (pg.durQ.io.pop)
 *   E5   generator output valid rise / fall                    (pg.io.pulse.valid)
 * plus every RfCmd (ev_rfcmd.csv), queue push drops (push.valid && !push.ready) and reset phases.
 *
 * Every row has `rst` = riscqReset at that cycle. The cores can start before the host's reset pulse
 * (riscqResetHostCd has no init), and the channels live in dspCd so riscqReset does not clear them;
 * ev_meta.csv records the final release so the analysis can separate pre-release traffic.
 *
 * Env: RISCQ_ELF (program, default sw/pulse_sched.elf), RISCQ_OUT (output dir, required),
 *      RISCQ_CYCLES (dsp cycles to log after the analysis window starts, default 3000),
 *      RISCQ_MODE   powerup (default): load while the cores may already run (no host hold), then pulse reset
 *                   driver: follow risc-q/software/riscq/run.py -- assert reset, load, release
 *      RISCQ_ABORT  "a,b" (optional): after the release run a cycles, re-assert reset for b cycles, release
 *                   again without reloading (run.py rerun after an aborted run).
 * ev_meta.csv: every reset release (release_<i>_cyc) and window_start_cyc = first release after the
 * host's release write (the analysis window).
 * Run: cd risc-q && RISCQ_ELF=... RISCQ_OUT=... ~/projects/RISC-Q/mill runMain riscq.soc.sim.TimingSocCpuSim
 */
object TimingSocCpuSim extends App {
  val qubitNum = 2
  val dacMap   = Map((0, 0) -> 8, (0, 1) -> 8, (1, 0) -> 1, (1, 1) -> 1)
  val adcMap   = Map(0 -> 12, 1 -> 13)
  val N = 16; val w = 16; val maskW = BigInt(1) << w
  val gateInterp = 4
  val memOffset = 0x80000000L

  // gate-drive envelope content, same generator as PulseTableSocCpuSim (non-zero on [0,64)).
  def reK(a: Int, k: Int): BigInt = (if (k == 0) BigInt(a + 1) else BigInt(a * 5 + k * 11 + 17)) & (maskW - 1)
  def imK(a: Int, k: Int): BigInt = BigInt(a * 7 + k * 13 + 9) & (maskW - 1)
  def envWord(a: Int): BigInt = {
    var word = BigInt(0)
    for (k <- 0 until N / gateInterp) { word |= reK(a, k) << (2 * k * w); word |= imK(a, k) << ((2 * k + 1) * w) }
    word
  }

  val JAL_SELF = BigInt("6f", 16)
  val elfFile = new File(sys.env.getOrElse("RISCQ_ELF", "src/riscq/soc/sim/sw/pulse_sched.elf"))
  require(elfFile.exists(), s"missing ${elfFile.getPath}")
  val outDir = new File(sys.env.getOrElse("RISCQ_OUT", sys.error("set RISCQ_OUT to an output directory")))
  outDir.mkdirs()
  val postCycles = sys.env.getOrElse("RISCQ_CYCLES", "3000").toInt

  def pgOf(ch: PulseDriveChannel): PulseGenerator =
    ch.children.collectFirst { case p: PulseGenerator => p }.get

  SimConfig.addSimulatorFlag("-Wno-MULTIDRIVEN")
    .addSimulatorFlag("--x-initial 0")
    .compile {
      val dut = PulseTableSoc(qubitNum, dacMap, adcMap, withTest = false)
      dut.riscqArea.time.simPublic()
      dut.riscqReset.simPublic()
      val core = dut.riscqArea.riscqCores(0)
      core.riscvSoc.cmd.valid.simPublic()
      core.riscvSoc.cmd.payload.address.simPublic()
      core.riscvSoc.cmd.payload.data.simPublic()
      for (ch <- Seq(core.posted.gateChannel, core.posted.roChannel)) {
        ch.buf.outParamValid.simPublic()
        ch.buf.startTime.simPublic()
        ch.buf.io.startTime.simPublic()
        ch.buf.io.time.simPublic()
        ch.buf.io.dur.valid.simPublic(); ch.buf.io.dur.payload.simPublic()
        ch.buf.io.amp.payload.simPublic()
        val pg = pgOf(ch)
        for (q <- Seq(pg.ampQ, pg.phaseQ, pg.freqCQ, pg.freqPQ, pg.addrQ, pg.durQ)) {
          q.io.pop.valid.simPublic(); q.io.push.valid.simPublic(); q.io.push.ready.simPublic()
          q.io.pop.payload.simPublic(); q.io.push.payload.data.simPublic(); q.io.push.payload.startTime.simPublic()
        }
        pg.durQ.io.pop.payload.simPublic()
        pg.ampQ.io.pop.payload.simPublic()
        pg.freqCQ.io.pop.payload.simPublic()
        pg.io.pulse.valid.simPublic()
      }
      dut
    }.doSim("timingSocCpu", seed = 42) { dut =>
    val hostCd = dut.clockDomain
    val dspCd  = dut.dspCd
    dut.io.axi.ar.valid #= false; dut.io.axi.aw.valid #= false; dut.io.axi.w.valid #= false
    dut.io.axi.r.ready #= false;  dut.io.axi.b.ready #= false
    for (i <- 0 until dut.io.adc.length) { dut.io.adc(i).valid #= true; dut.io.adc(i).payload #= 0 }
    hostCd.forkStimulus(10)
    dspCd.forkStimulus(10)

    val core  = dut.riscqArea.riscqCores(0)
    val chans = Seq(core.posted.gateChannel, core.posted.roChannel)
    val chBase = Seq(0x00000, 0x10000)                       // RfCmd sub-window per channel
    val pgs   = chans.map(pgOf)
    val qNames = Seq("amp", "phase", "freqC", "freqP", "addr", "dur")
    def queues(i: Int) = Seq(pgs(i).ampQ, pgs(i).phaseQ, pgs(i).freqCQ, pgs(i).freqPQ, pgs(i).addrQ, pgs(i).durQ)

    def open(name: String, header: String): PrintWriter = {
      val pw = new PrintWriter(new File(outDir, name)); pw.println(header); pw
    }
    val fRf    = open("ev_rfcmd.csv",        "seq,sim_time,cyc,time,rst,addr,data")
    val fE0i   = open("ev_e0i_issue.csv",    "seq,sim_time,cyc,time,rst,ch,addr,data")
    // ch_time = the channel's local time copy (buf.io.time), the base its TimedQueues compare against.
    val fE0    = open("ev_e0_sched.csv",     "seq,sim_time,cyc,time,rst,ch,ch_time,start_time_reg")
    val fE1    = open("ev_e1_timeline.csv",  "seq,sim_time,cyc,time,rst,ch,ch_time,due,dur,amp")
    val fE2    = open("ev_e2_release.csv",   "seq,sim_time,cyc,time,rst,ch,ch_time,dur," +
      qNames.map(n => s"pop_${n}_cyc").mkString(",") + ",pop_amp_val,pop_freqC_val")
    val fE5    = open("ev_e5_out.csv",       "seq,sim_time,cyc,time,rst,ch,ch_time,edge")
    val fFlags = open("ev_flags.csv",        "sim_time,cyc,time,rst,kind")
    // every TimedQueue push / pop of every queue (FIFO order per queue), for pairing and lead checks
    val fPush  = open("ev_queue_push.csv",   "cyc,ch,ch_time,queue,start_time,value,accepted")
    val fPop   = open("ev_queue_pop.csv",    "cyc,ch,ch_time,queue,value")
    val fMeta  = open("ev_meta.csv",         "key,value")
    val all = Seq(fRf, fE0i, fE0, fE1, fE2, fE5, fFlags, fPush, fPop, fMeta)
    fMeta.println(s"elf,${elfFile.getPath}")
    fMeta.println("clock,dspCd period 10 sim units (arbitrary); time = batch counter, 1 per dsp cycle")

    // ── per-cycle event monitor (sampled mid-cycle on the falling edge, like the RfCmd logger) ──
    var cyc = 0L
    var releaseCyc = -1L; var releaseTime = -1L; var prevRst = true
    val seq = scala.collection.mutable.Map[String, Int]().withDefaultValue(0)
    def next(k: String): Int = { val s = seq(k); seq(k) = s + 1; s }
    val lastPop = Array.fill(2, 6)(-1L)
    val lastAmp = Array.fill(2)(0L); val lastFreq = Array.fill(2)(0L)
    val releases = scala.collection.mutable.ArrayBuffer[Long]()
    var hostReleaseWrite = Long.MaxValue
    val prevValid = Array.fill(2)(false)
    var stopAt = Long.MaxValue
    fork {
      while (true) {
        dspCd.waitFallingEdge()
        val t = dut.riscqArea.time.toLong
        val rst = if (dut.riscqReset.toBoolean) 1 else 0
        val st = simTime()
        if (prevRst && rst == 0) { releaseCyc = cyc; releaseTime = t; releases += cyc }
        prevRst = rst == 1
        val cmd = core.riscvSoc.cmd
        if (cmd.valid.toBoolean) {
          val a = cmd.payload.address.toLong; val d = cmd.payload.data.toLong
          fRf.println(s"${next("rf")},$st,$cyc,$t,$rst,0x${a.toHexString},0x${d.toHexString}")
          for (i <- chans.indices if a == chBase(i))
            fE0i.println(s"${next(s"e0i$i")},$st,$cyc,$t,$rst,$i,0x${a.toHexString},0x${d.toHexString}")
        }
        for (i <- chans.indices) {
          val ch = chans(i); val pg = pgs(i)
          val ct = ch.buf.io.time.toLong
          if (ch.buf.outParamValid.toBoolean)
            fE0.println(s"${next(s"e0$i")},$st,$cyc,$t,$rst,$i,$ct,${ch.buf.startTime.toLong}")
          if (ch.buf.io.dur.valid.toBoolean)
            fE1.println(s"${next(s"e1$i")},$st,$cyc,$t,$rst,$i,$ct,${ch.buf.io.startTime.toLong}," +
              s"${ch.buf.io.dur.payload.toLong},${ch.buf.io.amp.payload.toLong}")
          if (pg.ampQ.io.pop.valid.toBoolean) lastAmp(i) = pg.ampQ.io.pop.payload.toLong
          if (pg.freqCQ.io.pop.valid.toBoolean) lastFreq(i) = pg.freqCQ.io.pop.payload.toLong
          for ((q, j) <- queues(i).zipWithIndex) {
            def v(x: spinal.core.BaseType): Long = x match {
              case u: UInt => u.toLong
              case z: SInt => z.toLong
              case b: Bits => b.toLong
            }
            if (q.io.push.valid.toBoolean)
              fPush.println(s"$cyc,$i,$ct,${qNames(j)},${q.io.push.payload.startTime.toLong}," +
                s"${v(q.io.push.payload.data.asInstanceOf[spinal.core.BaseType])},${if (q.io.push.ready.toBoolean) 1 else 0}")
            if (q.io.pop.valid.toBoolean)
              fPop.println(s"$cyc,$i,$ct,${qNames(j)},${v(q.io.pop.payload.asInstanceOf[spinal.core.BaseType])}")
            if (q.io.pop.valid.toBoolean) lastPop(i)(j) = cyc
            if (q.io.push.valid.toBoolean && !q.io.push.ready.toBoolean)
              fFlags.println(s"$st,$cyc,$t,$rst,ch${i}_${qNames(j)}Q_push_dropped")
          }
          if (pg.durQ.io.pop.valid.toBoolean)
            fE2.println(s"${next(s"e2$i")},$st,$cyc,$t,$rst,$i,$ct,${pg.durQ.io.pop.payload.toLong}," +
              lastPop(i).mkString(",") + s",${lastAmp(i)},${lastFreq(i)}")
          val v = pg.io.pulse.valid.toBoolean
          if (v != prevValid(i))
            fE5.println(s"${next(s"e5$i")},$st,$cyc,$t,$rst,$i,$ct,${if (v) "rise" else "fall"}")
          prevValid(i) = v
        }
        cyc += 1
        if (cyc % 256 == 0) all.foreach(_.flush())
      }
    }

    // ── boot ──
    val mode = sys.env.getOrElse("RISCQ_MODE", "powerup")
    require(Seq("powerup", "driver").contains(mode), s"RISCQ_MODE must be powerup or driver, got $mode")
    val abort = sys.env.get("RISCQ_ABORT").map(_.split(",").map(_.trim.toInt))
    fMeta.println(s"mode,$mode")
    fMeta.println(s"abort,${abort.map(_.mkString(";")).getOrElse("none")}")
    val image = SparseMemory(seed = 0)
    new Elf(elfFile, 32).load(image, 0)
    hostCd.waitSampling(40)
    val axi = Axi4Master(dut.io.axi, hostCd)
    val hostCtrlAddr = BigInt(dut.map.hostCtrlBase)
    def hostReset(on: Boolean): Unit = axi.write(hostCtrlAddr, List(if (on) 0x01 else 0x00, 0x00, 0x00, 0x00).map(_.toByte))
    // driver flow (run.py setup): hold the cores before touching their memories.
    if (mode == "driver") { hostReset(true); fMeta.println(s"host_assert_before_load_cyc,$cyc") }
    def leBytes(v: BigInt, n: Int): List[Byte] = List.tabulate(n)(i => ((v >> (8 * i)) & 0xFF).toByte)
    def loadInstr(c: Int, word: Int, v: BigInt): Unit =
      axi.write(BigInt(dut.map.coreMemOffset(c)) + word.toLong * 4, leBytes(v, 4))
    val gateEnvBytes = (N / gateInterp) * 2 * w / 8
    def loadEnv(c: Int, a: Int, word: BigInt): Unit = {
      val wordAddr = BigInt(dut.map.pulseMemOffset(c)) + a.toLong * gateEnvBytes
      for (lane <- 0 until gateEnvBytes / 4) axi.write(wordAddr + lane * 4, leBytes(word >> (lane * 32), 4))
    }
    val progWords = sys.env.getOrElse("RISCQ_PROG_WORDS", "1024").toInt
    for (i <- 0 until progWords)
      loadInstr(0, i, BigInt(image.readInt(memOffset + 4L * i).toLong & 0xFFFFFFFFL))
    loadInstr(1, 0, JAL_SELF)
    for (a <- 0 until 64) loadEnv(0, a, envWord(a))

    // powerup flow (PulseTableSocCpuSim): assert-then-release pulse after the load; driver flow: release.
    if (mode == "powerup") { hostReset(true); hostCd.waitSampling(20) }
    hostReleaseWrite = cyc
    fMeta.println(s"host_release_write_cyc,$cyc")
    hostReset(false)

    // analysis window starts at the first reset release after the host's release write
    while (releases.forall(_ < hostReleaseWrite) || dut.riscqReset.toBoolean) dspCd.waitSampling()
    val windowStart = releases.find(_ >= hostReleaseWrite).get
    fMeta.println(s"window_start_cyc,$windowStart")
    abort.foreach { case Array(a, b) =>
      dspCd.waitSampling(a)
      fMeta.println(s"abort_assert_write_cyc,$cyc"); hostReset(true)
      dspCd.waitSampling(b)
      fMeta.println(s"rerun_release_write_cyc,$cyc"); hostReset(false)
    }
    dspCd.waitSampling(postCycles)
    releases.zipWithIndex.foreach { case (c, i) => fMeta.println(s"release_${i}_cyc,$c") }
    fMeta.println(s"final_release_cyc,$releaseCyc")
    fMeta.println(s"final_release_time,$releaseTime")
    fMeta.println(s"log_end_cyc,$cyc")
    fMeta.println(s"post_cycles,$postCycles")
    all.foreach { f => f.flush(); f.close() }
    println(s"[TimingSocCpuSim] release at cyc $releaseCyc time $releaseTime; logged to ${outDir.getPath}")
    simSuccess()
  }
}
