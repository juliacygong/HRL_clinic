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
import riscq.soc.comm.{AccelResult, AccelResultSink}

/**
 * The accelerator socket '''sharing the qubit core's real control block''' with the existing time
 * registers - the integration [[AccelLinkSim]] does not cover.
 *
 * [[AccelLinkSim]] proves the sink works as a unit, on its own bus. This proves it coexists on one
 * `MemMapFiber` with `TimeMemMap`, is reachable at its production CPU address (`RQ_CTRL_ACCEL`,
 * 0x4300), and that neither mapping disturbs the other - which is the thing that actually breaks
 * when two people add registers to the same control block independently.
 *
 * Mirrors [[ControlMapFiberSim]]'s harness, with the accelerator sink added as a third contributor.
 *
 * Checks:
 *   1. the time registers still behave with the accelerator mapping present (no collision);
 *   2. the status poll at 0x4304 never blocks and reports "not ready";
 *   3. a read of 0x4300 with nothing pending '''halts''', then completes with the pushed value;
 *   4. the read '''consumes''' - a second read halts again rather than returning it twice.
 *
 * Run with `mill runMain riscq.soc.sim.AccelInSocSim`.
 */
object AccelInSocSim extends App {
  val accelAddr  = 0x4300
  val statusAddr = 0x4304
  val dataWidth  = 32

  case class Dut() extends Component {
    val tlBus = new MasterBus(tilelink.M2sParameters(addressWidth = 24, dataWidth = 32,
      masters = List(tilelink.M2sAgent(name = this, mapping = List(tilelink.M2sSource(
        id = SizeMapping(0, 4), emits = tilelink.M2sTransfers(
          get = tilelink.SizeRange.upTo(0x40), putFull = tilelink.SizeRange.upTo(0x40),
          putPartial = tilelink.SizeRange.upTo(0x40))))))))
    val externalTime = in port UInt(32 bits)
    val accelIn      = slave port Flow(AccelResult(dataWidth))

    val mm = MemMapFiber(addressWidth = 22, dataWidth = 32)
    // contributor 1: the existing time/control registers
    val timeMemMap = TimeMemMap(externalTime); mm.addMapping(timeMemMap.mapping)
    // contributor 2: the accelerator socket, at its production address
    val accel = AccelResultSink(dataWidth, dataAddr = accelAddr, statusAddr = statusAddr)
    accel.resultIn << accelIn
    mm.addMapping(accel.mapping)
    mm.up at 0 of tlBus.node
  }

  SimConfig.compile(Dut()).doSim("accelInSoc", seed = 42) { dut =>
    val cd = dut.clockDomain
    cd.forkStimulus(10)
    dut.externalTime #= 0
    dut.accelIn.valid #= false
    dut.accelIn.payload.data #= 0
    implicit val idAllocator = new IdAllocator(DebugId.width)
    implicit val idCallback  = new IdCallback
    val cpu = new MasterAgent(dut.tlBus.node.bus, cd)
    cd.waitSampling(10)

    // (1) the time register still works with the accelerator mapping present
    dut.externalTime #= 12345
    cd.waitSampling(4)
    val t = cpu.getInt(0, 0xbff8)
    assert(t == 12345, s"time register read $t with the accel mapping present, expected 12345 - COLLISION")

    // (2) the status poll must never block, and should say "not ready"
    val st0 = cpu.getInt(0, statusAddr)
    assert((st0 & 1) == 0, s"status reported ready before anything was pushed (got $st0)")

    // (3) a read with nothing pending must HALT
    var done = false; var value = BigInt(-1)
    fork {
      value = BigInt(cpu.getInt(0, accelAddr)) & BigInt("ffffffff", 16)
      done = true
    }
    cd.waitSampling(80)
    assert(!done, "the accelerator read completed with no result pending - it did NOT block")

    val payload = BigInt("5eed1234", 16)
    dut.accelIn.payload.data #= payload
    dut.accelIn.valid #= true
    cd.waitSampling(); dut.accelIn.valid #= false
    var w = 0
    while (!done && w < 500) { cd.waitSampling(); w += 1 }
    assert(done, "the read never completed after a result arrived")
    assert(value == payload, f"CPU read 0x$value%x from 0x$accelAddr%04x, expected 0x$payload%x")

    // (4) the read CONSUMED it
    var done2 = false
    fork { cpu.getInt(0, accelAddr); done2 = true }
    cd.waitSampling(80)
    assert(!done2, "a second read returned a STALE result - the read did not consume")

    dut.accelIn.payload.data #= BigInt("c0de0001", 16)
    dut.accelIn.valid #= true
    cd.waitSampling(); dut.accelIn.valid #= false
    w = 0
    while (!done2 && w < 500) { cd.waitSampling(); w += 1 }
    assert(done2, "the second read never completed")

    // and the time register is still fine afterwards
    dut.externalTime #= 999
    cd.waitSampling(4)
    assert(cpu.getInt(0, 0xbff8) == 999, "time register disturbed by accelerator traffic")

    println(f"[AccelInSocSim] PASS - accelerator sink shares the control block with TimeMemMap:")
    println(f"                 0x$accelAddr%04x blocks, returns 0x$payload%08x, consumes; time regs unaffected.")
  }
}
