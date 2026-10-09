package riscq.soc.comm

import spinal.core._
import spinal.lib._
import spinal.lib.bus.tilelink
import spinal.lib.bus.misc.SingleMapping

/**
 * Result of an accelerator computation, carried '''upstream''' (accelerator -> core) on a narrow
 * posted `Flow`, mirroring [[riscq.soc.link.ReadoutResult]]. Deliberately generic: `data` is
 * whatever the tenant produces - a QEC correction, a classification, a schedule index. The socket
 * does not care, which is the point.
 */
case class AccelResult(dataWidth: Int) extends Bundle {
  val data = Bits(dataWidth bits)
}

object AccelLink {
  /** Accelerator-side source: forward a result with its valid. */
  def source(valid: Bool, data: Bits, dataWidth: Int): Flow[AccelResult] = {
    val out = Flow(AccelResult(dataWidth))
    out.valid       := valid
    out.payload.data := data
    out
  }
}

/**
 * Core-side accelerator result register - '''the accelerator socket'''. The CPU reads one address
 * and the load '''blocks in hardware''' until a result is available: no polling loop, no interrupt,
 * no timer. This is the same mechanism `ReadoutResultSink` uses for readout results, which is why
 * it is worth reusing rather than inventing.
 *
 * ==Why build this before the tenant is scoped==
 * Every candidate accelerator (QEC decoder, state discriminator, schedule generator) attaches the
 * same way: a result arrives from hardware, the CPU needs it, and the pulse that depends on it must
 * still land on an exact cycle. The socket is therefore tenant-agnostic, and building it first
 * retires all the integration risk - address decode, memory map, link pipelining, bus halting -
 * while the compute is still a placeholder.
 *
 * ==Freshness: consuming, not idempotent==
 * `ReadoutResultSink` is '''idempotent''' - re-reading returns the same value, and freshness is a
 * software timing contract. That is wrong for an accelerator in a feedback loop: reading too early
 * would silently return the PREVIOUS round's answer, and in QEC that is a wrong correction applied
 * to a real qubit, presenting as decoder inaccuracy rather than a timing bug.
 *
 * So this sink '''consumes''': a read clears `valid`, and the next read blocks until a fresh result
 * arrives. A premature read stalls instead of lying. The cost is that the read is no longer
 * idempotent - software must latch the value rather than re-read it.
 *
 * @param dataWidth  width of the accelerator's result
 * @param dataAddr   CPU address of the blocking result read
 * @param statusAddr CPU address of a non-blocking "is a result ready?" poll
 */
case class AccelResultSink(dataWidth: Int, dataAddr: Int, statusAddr: Int) extends Area {
  val resultIn = Flow(AccelResult(dataWidth))

  val valid = Reg(Bool()) init False
  val data  = Reg(Bits(dataWidth bits)) init 0
  val consumed = Bool()
  consumed := False                   // pulsed by the read primitive below

  when(resultIn.valid) {
    data  := resultIn.payload.data
    valid := True
  } elsewhen (consumed) {
    valid := False                      // a read consumes the result
  }

  /** Contribute this sink's registers to a core-local `MemMapFiber`. */
  def mapping(factory: tilelink.SlaveFactory): Unit = {
    factory.read(data, dataAddr)
    factory.onReadPrimitive(SingleMapping(dataAddr), haltSensitive = false, null) {
      when(!valid) {
        factory.readHalt()              // BLOCK until a result is available
      } otherwise {
        consumed := True                // ...then consume it, so the next read waits for a fresh one
      }
    }
    factory.read(valid.asBits.resize(32), statusAddr)  // non-blocking poll
  }
}
