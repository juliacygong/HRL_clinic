package riscq.soc.sim

import spinal.core._
import spinal.core.sim._
import spinal.lib._
import spinal.lib.bus.tilelink
import spinal.lib.bus.tilelink.DebugId
import spinal.lib.bus.tilelink.fabric.MasterBus
import spinal.lib.bus.tilelink.sim.{IdAllocator, IdCallback, MasterAgent}
import spinal.lib.bus.misc.SizeMapping
import riscq.soc.comm.{AccelLink, AccelResult, AccelResultSink}
import riscq.soc.fabric.MemMapFiber

/**
 * The accelerator socket on a bus, with an '''identity tenant''' - the "decoder" returns whatever it
 * is given. Deliberately trivial: this test is about the plumbing, not the compute.
 */
class AccelSocket(dataWidth: Int = 32, linkPipe: Int = 4) extends Component {
  val io = new Bundle {
    val push     = in Bool ()                  // stand-in for "the accelerator produced a result"
    val pushData = in Bits (dataWidth bits)
  }
  val fiber = MemMapFiber(addressWidth = 16, dataWidth = 32)
  val sink  = AccelResultSink(dataWidth, dataAddr = 0x4300, statusAddr = 0x4304)

  // identity tenant, pushed up the posted link with `linkPipe` plain register stages
  val up = AccelLink.source(io.push, io.pushData, dataWidth)
  sink.resultIn << (0 until linkPipe).foldLeft(up)((f, _) => f.stage())
  fiber.addMapping(sink.mapping)

  val cpu = new MasterBus(tilelink.M2sParameters(
    addressWidth = 16, dataWidth = 32,
    masters = List(tilelink.M2sAgent(name = null, mapping = List(tilelink.M2sSource(
      id = SizeMapping(0, 4), emits = tilelink.M2sTransfers(
        get = tilelink.SizeRange(4), putFull = tilelink.SizeRange(4))))))))
  fiber.up at SizeMapping(0, 1 << 16) of cpu.node
}

/**
 * Milestone 1 of the accelerator track: the socket works, and the blocking read really blocks.
 *
 * The tenant is an identity function on purpose. Every candidate accelerator attaches the same way,
 * so this retires the integration risk - address decode, memory map, posted link, bus halting -
 * before any compute exists. Swapping in a real decoder later changes only the inside of one
 * component.
 *
 * Checks:
 *   1. a read issued with NO result pending HALTS, and completes only once one arrives;
 *   2. the value read back is the value pushed, through `linkPipe` register stages;
 *   3. the read CONSUMES - a second read blocks again rather than returning the stale value.
 *
 * Point 3 is the deliberate departure from `ReadoutResultSink`, which is idempotent. For a feedback
 * loop, silently returning the previous round's answer is worse than stalling.
 *
 * Run with `mill runMain riscq.soc.sim.AccelLinkSim`.
 */
object AccelLinkSim extends App {
  val dataWidth = 32

  for (linkPipe <- List(0, 4, 16)) {
    SimConfig.compile(new AccelSocket(dataWidth, linkPipe)).doSim(s"accel_pipe$linkPipe", seed = 42) { dut =>
      dut.clockDomain.forkStimulus(10)
      dut.io.push #= false; dut.io.pushData #= 0
      dut.clockDomain.waitSampling(10)

      implicit val idAllocator = new IdAllocator(DebugId.width)
      implicit val idCallback  = new IdCallback
      val agent = new MasterAgent(dut.cpu.node.bus, dut.cpu.node.clockDomain)

      // (1) a read with nothing pending must HALT
      var done = false; var value = BigInt(-1)
      fork {
        value = BigInt(agent.getInt(0, 0x4300)) & BigInt("ffffffff", 16)
        done = true
      }
      dut.clockDomain.waitSampling(60)
      assert(!done, s"linkPipe=$linkPipe: the read completed with no result pending - it did NOT block")

      // ...and completes once a result arrives
      val payload = BigInt("a5a5f00d", 16)
      dut.io.pushData #= payload; dut.io.push #= true
      dut.clockDomain.waitSampling(); dut.io.push #= false
      var w = 0
      while (!done && w < 400) { dut.clockDomain.waitSampling(); w += 1 }
      assert(done, s"linkPipe=$linkPipe: the read never completed after a result arrived")
      assert(value == payload, f"linkPipe=$linkPipe: read 0x$value%x, pushed 0x$payload%x")

      // (3) the read CONSUMED it: a second read must block again
      var done2 = false
      fork { agent.getInt(0, 0x4300); done2 = true }
      dut.clockDomain.waitSampling(60)
      assert(!done2, s"linkPipe=$linkPipe: a second read returned a STALE result - it did not consume")

      dut.io.pushData #= BigInt("deadbeef", 16); dut.io.push #= true
      dut.clockDomain.waitSampling(); dut.io.push #= false
      w = 0
      while (!done2 && w < 400) { dut.clockDomain.waitSampling(); w += 1 }
      assert(done2, s"linkPipe=$linkPipe: the second read never completed")

      println(f"[AccelLinkSim] PASS linkPipe=$linkPipe%2d: read blocks until a result arrives, returns " +
              f"0x$payload%08x intact, and CONSUMES it (the next read blocks again).")
    }
  }
  println("[AccelLinkSim] accelerator socket verified at pipe depths 0 / 4 / 16 - distance tolerant.")
}
