package riscq.soc.comm

import spinal.core._
import spinal.lib._
import spinal.lib.bus.tilelink
import spinal.lib.bus.tilelink.fabric.MasterBus
import spinal.lib.bus.misc.SizeMapping
import riscq.soc.fabric.MemMapFiber
import riscq.soc.rf.TimeMemMap

/**
 * Standalone wrappers for out-of-context resource/timing of the comm-side CPU blocks. Each is a
 * core control block (MemMapFiber + TimeMemMap, as in AccelInSocSim / XcomMemMapSim) with zero or
 * one extra contributor; subtracting `CtrlBase` isolates that contributor's cost.
 *
 *   mill runMain riscq.soc.comm.GenCommStats <outDir>
 */
object GenCommStats extends App {
  val dir = if (args.nonEmpty) args(0) else "build/comm-stats/rtl"

  def cpuBus(owner: Nameable) = new MasterBus(tilelink.M2sParameters(addressWidth = 24, dataWidth = 32,
    masters = List(tilelink.M2sAgent(name = owner, mapping = List(tilelink.M2sSource(
      id = SizeMapping(0, 4), emits = tilelink.M2sTransfers(
        get = tilelink.SizeRange.upTo(0x40), putFull = tilelink.SizeRange.upTo(0x40),
        putPartial = tilelink.SizeRange.upTo(0x40))))))))

  /** Control block with only the time registers: the baseline. */
  case class CtrlBase() extends Component {
    val cpu  = cpuBus(this)
    val time = in port UInt(32 bits)
    val mm   = MemMapFiber(addressWidth = 22, dataWidth = 32)
    mm.addMapping(TimeMemMap(time).mapping)
    mm.up at 0 of cpu.node
  }

  /** Baseline + the accelerator result socket at its production addresses. */
  case class CtrlAccel() extends Component {
    val cpu     = cpuBus(this)
    val time    = in port UInt(32 bits)
    val accelIn = slave port Flow(AccelResult(32))
    val mm      = MemMapFiber(addressWidth = 22, dataWidth = 32)
    mm.addMapping(TimeMemMap(time).mapping)
    val accel = AccelResultSink(32, dataAddr = 0x4300, statusAddr = 0x4304)
    accel.resultIn << accelIn
    mm.addMapping(accel.mapping)
    mm.up at 0 of cpu.node
  }

  /** Baseline + XcomMemMap, with xcom's command port as top-level IO (the IP is measured separately). */
  case class CtrlXcom() extends Component {
    val cpu  = cpuBus(this)
    val time = in port UInt(32 bits)
    val coreEn    = out port Bool()
    val coreOp    = out port Bits(5 bits)
    val coreData1 = out port Bits(32 bits)
    val coreData2 = out port Bits(32 bits)
    val coreReady = in port Bool()
    val coreValid = in port Bool()
    val coreFlag  = in port Bool()
    val rxData1   = in port Bits(32 bits)
    val rxData2   = in port Bits(32 bits)
    val mm = MemMapFiber(addressWidth = 22, dataWidth = 32)
    mm.addMapping(TimeMemMap(time).mapping)
    val xm = XcomMemMap()
    coreEn := xm.coreEn; coreOp := xm.coreOp; coreData1 := xm.coreData1; coreData2 := xm.coreData2
    xm.coreReady := coreReady; xm.coreValid := coreValid; xm.coreFlag := coreFlag
    xm.rxData1 := rxData1; xm.rxData2 := rxData2
    mm.addMapping(xm.mapping)
    mm.up at 0 of cpu.node
  }

  val cfg = SpinalConfig(mode = Verilog, targetDirectory = dir)
  cfg.generate(CtrlBase())
  cfg.generate(CtrlAccel())
  cfg.generate(CtrlXcom())
}
