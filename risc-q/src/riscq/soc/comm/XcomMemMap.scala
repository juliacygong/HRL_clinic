package riscq.soc.comm

import spinal.core._
import spinal.lib._
import spinal.lib.bus.tilelink
import spinal.lib.bus.misc.SingleMapping

/**
 * CPU-facing register block for [[Xcom]] - the board-to-board link's side of the controller
 * interface. Contribute `mapping` to a core-local `MemMapFiber`, and wire `io` to an `Xcom`
 * instance.
 *
 * ==Deliberately not tied to a location==
 * There is '''one XCOM per chip''' but potentially many qubit cores, so where the `Xcom` instance
 * lives - owned by one designated core, shared with arbitration, or driven by the PS - is a team
 * decision, not this file's. This block is just the register interface; it works wherever the
 * instance ends up.
 *
 * ==Command issue==
 * A write to `ctrlAddr` issues a command, using the '''same encoding as XCOM's own AXI path''' so
 * there is one convention rather than two (see `QICK_Xcom` in the Python driver, and
 * `xcom_cmd.sv`'s `i_ps_ctrl`):
 * {{{
 *   ctrl = (op << 1) | 1        // bit 0 triggers; bits 5:1 are the opcode
 * }}}
 * `i_core_en` is pulsed for exactly '''one cycle''', because the trigger is a one-shot - its AXI
 * twin self-clears in `xcom_axil_slv.sv:339`, and holding it high re-issues the command.
 *
 * ==Receive==
 * `o_core_valid` out of XCOM is a '''level''' that stays high from a board's previous command, not a
 * per-packet pulse - waiting on it directly returns a half-shifted word. This block edge-detects it
 * into a sticky `fresh` bit, so:
 *   - a read of `rx1Addr` '''blocks''' until a genuinely new packet has arrived, then '''consumes'''
 *     it (same contract as [[AccelResultSink]], and for the same reason: in a feedback path,
 *     silently re-reading the previous message is worse than stalling);
 *   - `statusAddr` is the non-blocking poll for code that cannot stall.
 */
case class XcomMemMap(
    ctrlAddr:   Int = 0x4400,   // W: (op << 1) | 1  -> issue a command
    dt1Addr:    Int = 0x4404,   // W: operand 1 (destination board id for network sends)
    dt2Addr:    Int = 0x4408,   // W: operand 2 (payload)
    rx1Addr:    Int = 0x440c,   // R: received data 1 - BLOCKS until fresh, then consumes
    rx2Addr:    Int = 0x4410,   // R: received data 2 - non-blocking
    flagAddr:   Int = 0x4414,   // R: the peer-settable flag bit
    statusAddr: Int = 0x4418    // R: bit0 = a fresh packet is waiting, bit1 = link ready
) extends Area {

  // Plain signals, not a directioned io bundle: this is an `Area` contributed to an enclosing
  // component (like `ReadoutResultSink`), and `in`/`out` are only meaningful on a `Component`.
  // Driven by this block, consume in the parent:
  val coreEn    = Bool ()
  val coreOp    = Bits (5 bits)
  val coreData1 = Bits (32 bits)
  val coreData2 = Bits (32 bits)
  // Driven by the parent from the Xcom instance:
  val coreReady = Bool ()
  val coreValid = Bool ()
  val coreFlag  = Bool ()
  val rxData1   = Bits (32 bits)
  val rxData2   = Bits (32 bits)

  val op    = Reg(Bits(5 bits)) init 0
  val dt1   = Reg(Bits(32 bits)) init 0
  val dt2   = Reg(Bits(32 bits)) init 0
  val fire  = False.allowOverride

  // one-cycle enable pulse: the trigger is a one-shot (xcom_axil_slv.sv:339)
  coreEn    := RegNext(fire) init False
  coreOp    := op
  coreData1 := dt1
  coreData2 := dt2

  // `coreValid` is a LEVEL, not a per-packet pulse - edge-detect it into a sticky freshness bit
  val validPrev = RegNext(coreValid) init False
  val arrived   = coreValid && !validPrev
  val fresh     = Reg(Bool()) init False
  val consumed  = False.allowOverride
  when(arrived)        { fresh := True }
    .elsewhen(consumed) { fresh := False }

  def mapping(factory: tilelink.SlaveFactory): Unit = {
    // ── command issue ──
    factory.onWritePrimitive(SingleMapping(ctrlAddr), haltSensitive = false, null) { fire := True }
    factory.write(op, ctrlAddr, bitOffset = 1)   // ctrl[5:1] = opcode. ADDRESS-GATED: `nonStopWrite`
                                                 // would latch the opcode out of EVERY bus write,
                                                 // so writing dt1/dt2 would clobber it.
    factory.write(dt1, dt1Addr)
    factory.write(dt2, dt2Addr)

    // ── receive ──
    factory.read(rxData1, rx1Addr)
    factory.onReadPrimitive(SingleMapping(rx1Addr), haltSensitive = false, null) {
      when(!fresh) { factory.readHalt() }        // BLOCK until a genuinely new packet
        .otherwise { consumed := True }          // ...and consume it
    }
    factory.read(rxData2, rx2Addr)            // non-blocking companion
    factory.read(coreFlag.asBits.resize(32), flagAddr)
    factory.read((coreReady ## fresh).resize(32), statusAddr)  // bit0 fresh, bit1 ready
  }
}
