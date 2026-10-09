package riscq.soc.sim

import spinal.core._
import spinal.core.sim._
import spinal.lib._
import spinal.lib.bus.tilelink
import spinal.lib.bus.tilelink.DebugId
import spinal.lib.bus.tilelink.fabric.MasterBus
import spinal.lib.bus.tilelink.sim.{IdAllocator, IdCallback, MasterAgent}
import spinal.lib.bus.misc.SizeMapping
import riscq.soc.fabric.MemMapFiber
import riscq.soc.rf.TimeMemMap
import riscq.soc.comm.{Xcom, XcomMemMap}

/**
 * '''CPU to CPU across the board link.''' Two boards, each with its own control block and its own
 * bus master standing in for a RISC-V core. A processor on board A issues a send by writing MMIO
 * registers; a processor on board B reads the payload back out of its own control block, with the
 * read blocking until the packet actually arrives.
 *
 * This is the piece [[XcomSim]] does not cover: that one drives XCOM's command port directly from
 * Scala. Here the only thing touching XCOM is the CPU, through [[XcomMemMap]], exactly as control
 * software would.
 *
 * Checks:
 *   1. the XCOM registers coexist with `TimeMemMap` on one control block without collision;
 *   2. CPU A assigns board ids over MMIO (local commands);
 *   3. a read of B's rx register with no packet pending '''halts''';
 *   4. CPU A sends, and B's blocked read completes with the exact payload;
 *   5. the read '''consumes''' - a second read halts again rather than returning it twice.
 *
 * Run with `mill runMain riscq.soc.sim.XcomMemMapSim`.
 */
object XcomMemMapSim extends App {
  val ctrlA = 0x4400; val dt1A = 0x4404; val dt2A = 0x4408
  val rx1A  = 0x440c; val statusA = 0x4418

  /** `ctrl` encoding, shared with XCOM's own AXI path: (op << 1) | 1. */
  def ctrlWord(op: Int): BigInt = BigInt((op << 1) | 1)

  case class Dut() extends Component {
    val rstn    = in Bool ()
    val cfgAddr = in Bits (6 bits); val cfgData = in Bits (32 bits); val cfgEn = in Bool ()
    val cfgRdy  = out Bool ()

    def bus() = new MasterBus(tilelink.M2sParameters(addressWidth = 24, dataWidth = 32,
      masters = List(tilelink.M2sAgent(name = this, mapping = List(tilelink.M2sSource(
        id = SizeMapping(0, 4), emits = tilelink.M2sTransfers(
          get = tilelink.SizeRange.upTo(0x40), putFull = tilelink.SizeRange.upTo(0x40),
          putPartial = tilelink.SizeRange.upTo(0x40))))))))

    val cpuA = bus(); val cpuB = bus()
    val xa = Xcom(1); val xb = Xcom(1)

    for (x <- List(xa, xb)) {
      x.io.i_ps_clk   := clockDomain.readClockWire; x.io.i_ps_rstn   := rstn
      x.io.i_core_clk := clockDomain.readClockWire; x.io.i_core_rstn := rstn
      x.io.i_time_clk := clockDomain.readClockWire; x.io.i_time_rstn := rstn
      x.io.i_sync := False
      // AXI-Lite: used only to program the link tick (xcom_cfg)
      x.io.s_axi_awaddr := cfgAddr; x.io.s_axi_awprot := 0; x.io.s_axi_awvalid := cfgEn
      x.io.s_axi_wdata  := cfgData; x.io.s_axi_wstrb  := B"1111"; x.io.s_axi_wvalid := cfgEn
      x.io.s_axi_bready := True
      x.io.s_axi_araddr := 0; x.io.s_axi_arprot := 0; x.io.s_axi_arvalid := False
      x.io.s_axi_rready := False
    }
    cfgRdy := xa.io.s_axi_awready && xa.io.s_axi_wready

    // point-to-point link
    xa.io.i_xcom_clk  := xb.io.o_xcom_clk.asBits;  xa.io.i_xcom_data := xb.io.o_xcom_data.asBits
    xb.io.i_xcom_clk  := xa.io.o_xcom_clk.asBits;  xb.io.i_xcom_data := xa.io.o_xcom_data.asBits

    val externalTime = in port UInt(32 bits)

    /** One board's control block: time registers + the XCOM register interface. */
    def board(x: Xcom, b: MasterBus) = new Area {
      val mm = MemMapFiber(addressWidth = 22, dataWidth = 32)
      mm.addMapping(TimeMemMap(externalTime).mapping)
      val xm = XcomMemMap()
      x.io.i_core_en    := xm.coreEn
      x.io.i_core_op    := xm.coreOp
      x.io.i_core_data1 := xm.coreData1
      x.io.i_core_data2 := xm.coreData2
      xm.coreReady := x.io.o_core_ready
      xm.coreValid := x.io.o_core_valid
      xm.coreFlag  := x.io.o_core_flag
      xm.rxData1   := x.io.o_core_data1
      xm.rxData2   := x.io.o_core_data2
      mm.addMapping(xm.mapping)
      mm.up at 0 of b.node
    }
    val ba = board(xa, cpuA)
    val bb = board(xb, cpuB)
    // BlackBox ports are not directly readable from SpinalSim - surface what the test observes.
    val idA = out Bits (4 bits); val idB = out Bits (4 bits)
    idA := xa.io.o_xcom_id; idB := xb.io.o_xcom_id
  }

  // RISCQ_WAVES=1 dumps a VCD (simWorkspace/Dut/xcomMemMap/wave.vcd)
  val base = if (sys.env.contains("RISCQ_WAVES")) SimConfig.withWave else SimConfig
  val compiled = Xcom.rtlSources
    .foldLeft(base
      .addSimulatorFlag("-Wno-fatal")
      .addSimulatorFlag("--x-assign").addSimulatorFlag("0")
      .addSimulatorFlag("--x-initial").addSimulatorFlag("0"))((c, src) => c.addRtl(src))
    .compile(Dut())

  compiled.doSim("xcomMemMap", seed = 42) { dut =>
    val cd = dut.clockDomain
    cd.forkStimulus(10)
    dut.externalTime #= 0
    dut.cfgAddr #= 0; dut.cfgData #= 0; dut.cfgEn #= false
    dut.rstn #= false; cd.waitSampling(50); dut.rstn #= true; cd.waitSampling(100)

    // Each CPU needs its OWN id allocator/callback. Sharing them means board B's blocked read
    // holds source id 0 while board A tries to issue with the same id, and the responses cross.
    val cpuA = { implicit val a = new IdAllocator(DebugId.width); implicit val c = new IdCallback
                 new MasterAgent(dut.cpuA.node.bus, cd) }
    val cpuB = { implicit val a = new IdAllocator(DebugId.width); implicit val c = new IdCallback
                 new MasterAgent(dut.cpuB.node.bus, cd) }

    // program the link tick (xcom_cfg = register 1) on both boards over AXI
    dut.cfgAddr #= 4; dut.cfgData #= 8; cd.waitSampling(); dut.cfgEn #= true
    var g = 0; while (!dut.cfgRdy.toBoolean && g < 200) { cd.waitSampling(); g += 1 }
    cd.waitSampling(); dut.cfgEn #= false; cd.waitSampling(20)

    // (1) the time register still works alongside the XCOM registers
    dut.externalTime #= 777; cd.waitSampling(4)
    assert(cpuA.getInt(0, 0xbff8) == 777, "time register collided with the XCOM mapping")

    /** issue an XCOM command from a CPU, the way control software would */
    def send(cpu: MasterAgent, op: Int, d1: BigInt, d2: BigInt): Unit = {
      cpu.putInt(0, dt1A, d1.toInt)
      cpu.putInt(0, dt2A, d2.toInt)
      cpu.putInt(0, ctrlA, ctrlWord(op).toInt)   // (op << 1) | 1 triggers
      cd.waitSampling(60)
    }

    // (2) assign board ids over MMIO - local commands
    send(cpuA, Xcom.Op.setId, 1, 0)
    send(cpuB, Xcom.Op.setId, 2, 0)
    val ia = dut.idA.toInt; val ib = dut.idB.toInt
    assert(ia == 1 && ib == 2, s"ids not assigned over MMIO (A=$ia B=$ib)")
    println(s"[XcomMemMapSim] ids assigned over MMIO: A=$ia B=$ib")

    // (3) board B's receive read must HALT with nothing pending
    var done = false; var value = BigInt(-1)
    fork { value = BigInt(cpuB.getInt(0, rx1A)) & BigInt("ffffffff", 16); done = true }
    cd.waitSampling(80)
    assert(!done, "B's receive read completed with no packet pending - it did NOT block")

    // (4) CPU A sends; B's blocked read completes with the payload
    val payload = BigInt("1234beef", 16)
    send(cpuA, Xcom.Op.send32Dt1, 2, payload)
    var w = 0
    while (!done && w < 4000) { cd.waitSampling(); w += 1 }
    assert(done, s"B's read never completed after A sent (waited $w cycles)")
    assert(value == payload, f"B's CPU read 0x$value%x, A sent 0x$payload%x")
    println(f"[XcomMemMapSim] CPU A -> CPU B : 0x$payload%08x crossed the link and was read over MMIO")

    // (5) the read consumed it
    var done2 = false
    fork { cpuB.getInt(0, rx1A); done2 = true }
    cd.waitSampling(80)
    assert(!done2, "a second read returned a STALE packet - the read did not consume")
    println("[XcomMemMapSim] PASS - a processor on one board sent, a processor on another read it.")
  }
}
