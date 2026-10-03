package riscq.soc.sim

import spinal.core._
import spinal.core.sim._
import spinal.lib.bus.tilelink.DebugId
import spinal.lib.bus.tilelink.sim.{IdAllocator, IdCallback, MasterAgent}
import spinal.lib.bus.amba4.axi.sim.Axi4Master
import spinal.lib.bus.amba4.axilite.sim.AxiLite4Master
import riscq.soc.PulseTableSoc
import riscq.soc.qick.QickGenParams

/**
 * SoC-level check of the QICK drive path: a 1-qubit [[PulseTableSoc]] with `qickGen` set, so the gate
 * (CPU 0x10000) and readout-drive (CPU 0x20000) windows feed WaveWordBridge → the REAL `sg_translator.v`
 * → `axis_signal_gen_v6`. Verilator can't run the real gen (VHDL + DDS Compiler IP), so it binds to the
 * sim-only model `riscq/soc/qick/sim/axis_signal_gen_v6_model.v`: real s1 → m_axis timing (32 cycles,
 * nsamp-long pulses) and the gen_v6 datapath math (DDS × envelope, × gain >> 15).
 *
 * Checks:
 *   1. the gen host ports: AXI-Lite START_ADDR/WE write + read-back, an envelope word on s0_axis;
 *   2. CPU-window stores on the gate window play exactly one nsamp-long DDS-only pulse (outsel = 1) on
 *      DAC 0 whose peak equals the programmed gain, its first sample at the cycle the lead time predicts;
 *   3. the same on the readout-drive window → DAC 1.
 *
 * Run:  mill runMain riscq.soc.sim.PulseTableSocQickSim
 */
object PulseTableSocQickSim extends App {
  val qp    = QickGenParams()
  val bp    = qp.bridge
  val model = new java.io.File("src/riscq/soc/qick/sim/axis_signal_gen_v6_model.v").getCanonicalPath

  SimConfig.addSimulatorFlag("-Wno-MULTIDRIVEN")
    .addSimulatorFlag("--x-initial 0")
    .addSimulatorFlag("-Wno-IMPLICIT")   // sg_translator.v uses implicit nets
    .addSimulatorFlag("-Wno-WIDTH")      // sg_translator.v assigns 16-bit conf into a 24-bit wire
    .addRtl(model)
    .compile(PulseTableSoc(qubitNum = 1, dacMap = Map((0, 0) -> 0, (0, 1) -> 1), adcMap = Map(0 -> 0),
      withTest = true, qickGen = Some(qp)))
    .doSim("pulseTableSocQick", seed = 42) { dut =>
    val hostCd = dut.clockDomain
    val dspCd  = dut.dspCd
    val Seq(gateHost, roHost) = dut.qickHostPorts

    dut.io.axi.ar.valid #= false; dut.io.axi.aw.valid #= false; dut.io.axi.w.valid #= false
    dut.io.axi.r.ready #= false;  dut.io.axi.b.ready #= false
    dut.riscqArea.testMasters(0).node.bus.a.valid #= false
    for (a <- dut.io.adc) { a.valid #= true; a.payload #= 0 }
    for (h <- dut.qickHostPorts) {
      h.s_axi.aw.valid #= false; h.s_axi.w.valid #= false; h.s_axi.ar.valid #= false
      h.s_axi.b.ready #= true;   h.s_axi.r.ready #= true;  h.s0_axis.valid #= false
    }

    hostCd.forkStimulus(10)
    dspCd.forkStimulus(10)
    hostCd.waitSampling(40)

    def le(v: BigInt): List[Byte] = List.tabulate(4)(i => ((v >> (8 * i)) & 0xFF).toByte)
    def fromLe(b: List[Byte]): BigInt = b.zipWithIndex.map { case (x, i) => BigInt(x & 0xFF) << (8 * i) }.sum

    // ── 1. gen host side: START_ADDR / WE registers and one envelope word ──
    for ((h, name) <- List(gateHost -> "gate", roHost -> "ro")) {
      val axil = AxiLite4Master(h.s_axi, hostCd)
      axil.write(0x00, le(0x40))   // START_ADDR
      axil.write(0x04, le(1))      // WE = 1
      val sa = fromLe(axil.read(0x00, 4)); val we = fromLe(axil.read(0x04, 4))
      assert(sa == 0x40 && we == 1, s"[$name] gen regs read back START_ADDR=0x${sa.toString(16)} WE=$we")
      h.s0_axis.payload #= BigInt("7fff0000", 16); h.s0_axis.valid #= true
      hostCd.waitSamplingWhere(h.s0_axis.ready.toBoolean)
      h.s0_axis.valid #= false
      axil.write(0x04, le(0))      // WE = 0
      println(s"[PulseTableSocQickSim] $name gen host ports OK (START_ADDR/WE read back, envelope word accepted)")
    }

    // ── release the CPU (JAL-self loop) so the riscqCd test master can issue RF stores ──
    val axi = Axi4Master(dut.io.axi, hostCd)
    axi.write(BigInt(dut.map.coreMemOffset(0)), le(BigInt("6f", 16)))
    axi.write(BigInt(dut.map.hostCtrlBase), le(1))
    hostCd.waitSampling(20)
    axi.write(BigInt(dut.map.hostCtrlBase), le(0))
    hostCd.waitSampling(60)

    implicit val idAllocator = new IdAllocator(DebugId.width)
    implicit val idCallback  = new IdCallback
    val agent = new MasterAgent(dut.riscqArea.testMasters(0).node.bus, dspCd)
    def wr(addr: Int, v: BigInt): Unit = { agent.putInt(0, addr, v.toInt); dspCd.waitSampling(2) }

    /** Program and fire one pulse on the window at CPU `base`, then return (first DAC sample time, run
     *  length, lane values) observed on physical DAC `dacId`. */
    def playOn(base: Int, dacId: Int, gain: Int, nsamp: Int): (Long, Int, Set[BigInt], Long) = {
      val dac = dut.io.dac(dacId)
      var first = -1L; var run = 0; var lanes = Set.empty[BigInt]; var done = false
      val mon = fork {
        while (!done) {
          dspCd.waitSampling()
          val v = dac.payload.toBigInt
          if (v != 0) {
            if (first < 0) first = dut.riscqArea.time.toLong
            run += 1
            lanes ++= (0 until 16).map { k => val u = (v >> (16 * k)) & 0xFFFF; if (u >= 0x8000) u - 0x10000 else u }
          }
        }
      }
      val start = dut.riscqArea.time.toLong + 300
      wr(base + bp.freqAddr,  BigInt("01000000", 16))
      wr(base + bp.phaseAddr, 0)
      wr(base + bp.envAddr,   0)
      wr(base + bp.gainAddr,  gain)
      wr(base + bp.nsampAddr, nsamp)
      wr(base + bp.confAddr,  0x19)           // phrst = 1 (start at phase 0 ⇒ first sample is the peak), stdysel = 1, outsel = 1 (DDS only)
      wr(base + bp.startTimeAddr, start)
      wr(base + bp.fireAddr,  0)
      while (dut.riscqArea.time.toLong < start + nsamp + 60) dspCd.waitSampling()
      done = true; mon.join()
      (first, run, lanes, start)
    }

    // Expected first DAC sample, on the shared batch `time`: the bridge pops when its (1-cycle-late) time
    // copy hits start − leadTime, i.e. shared time start − leadTime + 1; the gen adds its 32-cycle latency
    // (= leadTime) and io.dac adds its one shared register stage.
    def expectedFirst(start: Long): Long = start - bp.leadTime + 1 + 32 + 1

    // ── 2. gate window → DAC 0 ──
    val (g0, gRun, gLanes, gStart) = playOn(0x10000, dacId = 0, gain = 0x1234, nsamp = 10)
    // outsel = 1 plays gain·cos(θ) (gen_v6: 32767·cos × gain >> 15), so the tone peaks just under gain.
    def peakOk(lanes: Set[BigInt], gain: Int) = { val pk = lanes.map(_.abs).max; pk <= gain && pk >= gain - 4 }
    println(s"[PulseTableSocQickSim] gate: start=$gStart first DAC0 sample at $g0 (expected ${expectedFirst(gStart)}), run=$gRun, peak=${gLanes.map(_.abs).max}")
    assert(gRun == 10, s"gate pulse ran $gRun cycles on DAC0, expected nsamp=10")
    assert(peakOk(gLanes, 0x1234), s"gate tone peak ${gLanes.map(_.abs).max}, expected ≈ gain 0x1234")
    assert(g0 == expectedFirst(gStart), s"gate first sample at $g0, expected ${expectedFirst(gStart)}")

    // ── 3. readout-drive window → DAC 1 ──
    val (r0, rRun, rLanes, rStart) = playOn(0x20000, dacId = 1, gain = 0x0777, nsamp = 5)
    println(s"[PulseTableSocQickSim] readout: start=$rStart first DAC1 sample at $r0 (expected ${expectedFirst(rStart)}), run=$rRun, peak=${rLanes.map(_.abs).max}")
    assert(rRun == 5, s"readout pulse ran $rRun cycles on DAC1, expected nsamp=5")
    assert(peakOk(rLanes, 0x0777), s"readout tone peak ${rLanes.map(_.abs).max}, expected ≈ gain 0x777")
    assert(r0 == expectedFirst(rStart), s"readout first sample at $r0, expected ${expectedFirst(rStart)}")

    println("[PulseTableSocQickSim] PASS — RISC-Q stores drive the QICK sg_translator + gen_v6 path onto DAC 0 / DAC 1")
  }
}
