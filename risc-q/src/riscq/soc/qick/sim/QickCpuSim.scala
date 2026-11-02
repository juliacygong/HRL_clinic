package riscq.soc.qick.sim

import spinal.core._
import spinal.core.sim._
import spinal.lib.misc.Elf
import spinal.lib.sim.SparseMemory
import spinal.lib.bus.amba4.axi.sim.Axi4Master
import riscq.soc.PulseTableSoc
import riscq.soc.qick.{QickGenHost, QickGenParams}

import java.io.{File, PrintWriter}
import java.nio.{ByteBuffer, ByteOrder}
import java.nio.file.Files

/**
 * CPU-in-the-loop run of a compiled QICK program on the QICK build of PulseTableSoc: the RISC-V core runs the
 * ELF, both drive channels go through WaveWordBridge -> axis_cdcsync_v1 -> sg_translator -> axis_signal_gen_v6,
 * and every gen's samples are logged. The QICK blocks are the firmware RTL with EMULATOR = 1 (QickGenParams.
 * emulator), which selects the behavioural FIFO, BRAM and DDS models QICKEmu uses, so a run compares directly
 * with QICKEmu's dac_out_ch<N>.csv.
 *
 * Boot follows board-bringup/bringup.py: hold the core, load the program and each gen's envelope table
 * (START_ADDR = 0, WE = 1, stream the words, WE = 0), release.
 *
 * Env: RISCQ_ELF (program), RISCQ_OUT (output dir), RISCQ_ENV_GATE / RISCQ_ENV_RO (optional <prog>_gen<N>.env),
 *      RISCQ_CYCLES (dsp cycles to log after the release, default 4000).
 * Output: dac_out_ch0.csv (gate), dac_out_ch1.csv (readout drive): cycle (genClk cycles since the release), then
 *      s0..s15, one row per valid m_axis beat, the 16 samples in time order.
 * Run: cd risc-q && RISCQ_ELF=... RISCQ_OUT=... mill runMain riscq.soc.qick.sim.QickCpuSim
 */
object QickCpuSim extends App {
  val fw        = new File("../firmware/ip").getCanonicalPath
  val models    = new File("../emulator/models").getCanonicalPath
  val memOffset = 0x80000000L
  val elfFile   = new File(sys.env("RISCQ_ELF"))
  val outDir    = new File(sys.env("RISCQ_OUT"))
  val postCycles = sys.env.getOrElse("RISCQ_CYCLES", "4000").toInt
  val envFiles  = List("RISCQ_ENV_GATE", "RISCQ_ENV_RO").map(sys.env.get(_).map(new File(_)))
  outDir.mkdirs()

  val rtl = Seq(
    s"$fw/axis_cdcsync_v1/src/axis_cdcsync_v1.sv", s"$fw/axis_cdcsync_v1/src/cdcsync.sv",
    s"$fw/axis_signal_gen_v6/src/axis_signal_gen_v6.v", s"$fw/axis_signal_gen_v6/src/signal_gen_top.v",
    s"$fw/axis_signal_gen_v6/src/signal_gen.v", s"$fw/axis_signal_gen_v6/src/ctrl_sg_v6.sv",
    s"$fw/axis_signal_gen_v6/src/latency_reg.v", s"$fw/axis_signal_gen_v6/src/verilog/axi_slv_sg_v6_sv.sv",
    s"$fw/axis_signal_gen_v6/src/verilog/data_writer_sv.sv", s"$fw/axis_signal_gen_v6/src/verilog/synchronizer_n_sv.sv",
    s"$models/bram_dp/bram_dp_behav.sv", s"$models/fifo/fifo_behav.sv", s"$models/dds_model/src/dds_behavioral_model.sv"
  ) ++ new File(s"$fw/axis_dyn_readout_v1/src/fifo/verilog").listFiles.map(_.getPath).filter(_.endsWith(".sv"))

  val cfg = rtl.foldLeft(SimConfig.addSimulatorFlag("-Wno-fatal").addSimulatorFlag("-Wno-MULTIDRIVEN")
    .addSimulatorFlag("--x-initial 0").addSimulatorFlag("-Wno-lint"))((c, f) => c.addRtl(f))

  cfg.compile {
    PulseTableSoc(1, Map((0, 0) -> 14, (0, 1) -> 1), Map(0 -> 8),
      qickGen = Some(QickGenParams(emulator = true)))
  }.doSim("qickCpu", seed = 42) { dut =>
    val hostCd = dut.clockDomain
    val dspCd  = dut.dspCd
    val genCd  = dut.genCd
    dut.io.axi.ar.valid #= false; dut.io.axi.aw.valid #= false; dut.io.axi.w.valid #= false
    dut.io.axi.r.ready #= false;  dut.io.axi.b.ready #= false
    for (a <- dut.io.adc) { a.valid #= true; a.payload #= 0 }
    for (d <- dut.io.dac) d.ready #= true
    for (p <- dut.qickHostPorts) {
      p.s_axi.aw.valid #= false; p.s_axi.w.valid #= false; p.s_axi.ar.valid #= false
      p.s_axi.b.ready #= true;   p.s_axi.r.ready #= true
      p.s_axi.aw.payload.addr #= 0; p.s_axi.aw.payload.prot #= 0
      p.s_axi.ar.payload.addr #= 0; p.s_axi.ar.payload.prot #= 0
      p.s_axi.w.payload.data #= 0;  p.s_axi.w.payload.strb #= 0xF
      p.s0_axis.valid #= false;     p.s0_axis.payload #= 0
    }
    for (s <- dut.qickSamplePorts) s.ready #= true
    hostCd.forkStimulus(10000)      // 100 MHz
    dspCd.forkStimulus(2000)        // 500 MHz
    genCd.forkStimulus(2000)        // 500 MHz, asynchronous to dsp as on the board (RFDC clk_dac0)
    SimTimeout(sys.env.getOrElse("RISCQ_TIMEOUT_PS", "40000000000").toLong)

    // host side of one gen: AXI-Lite register write, envelope words on s0_axis
    def genWrite(p: QickGenHost, addr: Int, data: Long): Unit = {
      p.s_axi.aw.payload.addr #= addr; p.s_axi.w.payload.data #= data
      p.s_axi.aw.valid #= true; p.s_axi.w.valid #= true
      var awDone, wDone, bDone = false
      while (!(awDone && wDone && bDone)) {
        hostCd.waitSampling()
        if (p.s_axi.aw.valid.toBoolean && p.s_axi.aw.ready.toBoolean) { awDone = true; p.s_axi.aw.valid #= false }
        if (p.s_axi.w.valid.toBoolean && p.s_axi.w.ready.toBoolean)   { wDone = true;  p.s_axi.w.valid #= false }
        if (p.s_axi.b.valid.toBoolean) bDone = true
      }
    }
    def loadEnvelope(p: QickGenHost, f: File): Unit = {
      val b = ByteBuffer.wrap(Files.readAllBytes(f.toPath)).order(ByteOrder.LITTLE_ENDIAN).asIntBuffer
      genWrite(p, 0x00, 0)          // START_ADDR
      genWrite(p, 0x04, 1)          // WE
      hostCd.waitSampling(20)
      for (i <- 0 until b.limit()) {
        p.s0_axis.payload #= b.get(i).toLong & 0xFFFFFFFFL
        p.s0_axis.valid #= true
        hostCd.waitSamplingWhere(p.s0_axis.ready.toBoolean)
      }
      p.s0_axis.valid #= false
      hostCd.waitSampling(20)
      genWrite(p, 0x04, 0)
      println(s"[QickCpuSim] ${b.limit()} envelope words from ${f.getName}")
    }

    var genCyc = 0L
    var logging = false
    val logs = dut.qickSamplePorts.indices.map(c => new PrintWriter(new File(outDir, s"dac_out_ch$c.csv")))
    logs.foreach(_.println("cycle," + (0 until 16).map(k => s"s$k").mkString(",")))
    genCd.onSamplings {
      if (logging) {
        genCyc += 1
        for ((s, c) <- dut.qickSamplePorts.zipWithIndex if s.valid.toBoolean) {
          val v = s.payload.toBigInt
          val lanes = (0 until 16).map { k => val x = ((v >> (16 * k)) & 0xFFFF).toInt; if (x >= 32768) x - 65536 else x }
          logs(c).println(s"$genCyc," + lanes.mkString(","))
        }
      }
    }

    // the QICK IP resets synchronously and forkStimulus releases reset before the first clock edge: hold reset
    // over running clocks, as proc_sys_reset does on the board
    hostCd.waitSampling(4)
    hostCd.assertReset(); genCd.assertReset()
    hostCd.waitRisingEdge(16)
    hostCd.deassertReset(); genCd.deassertReset()

    val image = SparseMemory(seed = 0)
    new Elf(elfFile, 32).load(image, 0)
    hostCd.waitSampling(40)
    val axi = Axi4Master(dut.io.axi, hostCd)
    def leBytes(v: Long): List[Byte] = List.tabulate(4)(i => ((v >> (8 * i)) & 0xFF).toByte)
    def hostReset(on: Boolean): Unit = axi.write(BigInt(dut.map.hostCtrlBase), leBytes(if (on) 1 else 0))
    hostReset(true)
    for ((p, f) <- dut.qickHostPorts.zip(envFiles); file <- f) loadEnvelope(p, file)
    val progWords = (Files.size(elfFile.toPath.resolveSibling(elfFile.getName.stripSuffix(".elf") + ".bin")) + 3) / 4
    for (i <- 0L until progWords)
      axi.write(BigInt(dut.map.coreMemOffset(0)) + i * 4, leBytes(image.readInt(memOffset + 4 * i).toLong & 0xFFFFFFFFL))
    logging = true
    hostReset(false)
    dspCd.waitSampling(postCycles)
    logs.foreach { l => l.flush(); l.close() }
    println(s"[QickCpuSim] logged $genCyc gen cycles to ${outDir.getPath}")
    simSuccess()
  }
}
