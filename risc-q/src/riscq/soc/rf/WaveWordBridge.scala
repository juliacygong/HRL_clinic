package riscq.soc.rf

import spinal.core._
import spinal.lib._
import riscq.soc.link.RfCmd
import riscq.dsp.pulse.TimedQueue

/**
 * WaveWordBridge turns the RISC-V RfCmd register writes into QICK's 168-bit
 * signal-generator command word and releases it at the scheduled cycle using TimedQueue.
 *
 * io.cmd is fed by using core→DSP: core `sw` → RfLinkBridge → link pipe → demux.
 *
 * Released words pass through a small output buffer, so a word released while the signal generator is busy
 * (io.wave.ready low) waits instead of being lost. Sticky flags report what can still go wrong: a word lost
 * because the buffer was full (dropOut), a fire lost because the TimedQueue was full (dropSched), and a word
 * that had to wait (late). Each flag stays set until its `clear` bit is pulsed.
 *
 * With `withParamPort`, the pulse fields come instead from an upstream register file that has already
 * decoded them (io.params, e.g. a PulseParamBuffer's fire): each io.params beat is packed with `conf`
 * and queued at its own startTime. The cmd-side fire is then disabled, so io.cmd only writes `conf`
 * and the trigger registers.
 */

/** One pulse's decoded fields, in QICK wave-word widths, plus its start time (io.params). */
case class WaveFields(timeWidth: Int) extends Bundle {
  val freq      = Bits(32 bits)
  val phase     = Bits(32 bits)
  val env       = Bits(24 bits)
  val gain      = Bits(32 bits)
  val nsamp     = Bits(32 bits)
  val startTime = UInt(timeWidth bits)
}
case class WaveWordBridgeParams(
    addrWidth: Int = 16,      // Address width of RfCmd
    timeWidth: Int = 32,      // Batch time counter width
    depth: Int = 8,           // TimedQueue FIFO depth: holds depth + 1 scheduled pulses (FIFO + registered head)
    waveBufDepth: Int = 4,    // Output buffer depth (released words waiting for io.wave.ready)
    leadTime: Int = 8,        // Pulse: cycles released early
    leadTrig: Int = 8,        // trigger: cycles released early
    widthBits: Int = 16,      // Trigger width counter size (max trigger hold = 2^widthBits - 1 cycles)
    // Byte addresses for waveword
    freqAddr: Int = 0x00,
    phaseAddr: Int = 0x04,
    envAddr: Int = 0x08,
    gainAddr: Int = 0x0c,
    nsampAddr: Int = 0x10,
    confAddr: Int = 0x14,
    startTimeAddr: Int = 0x18,
    fireAddr: Int = 0x1c,
    // trigger registers
    trigTimeAddr: Int = 0x20,
    widthAddr: Int = 0x24,
    fireTrigAddr: Int = 0x28,
    withParamPort: Boolean = false, // pulse fields from io.params (decoded upstream) instead of the cmd registers
    confInit: Int = 0               // reset value of conf
)

case class WaveWordBridge(p: WaveWordBridgeParams = WaveWordBridgeParams()) extends Component {
  import p._

  val io = new Bundle {
    val cmd  = slave  port Flow(RfCmd(addrWidth))   // Register writes stream from the core
    val time = in     port UInt(timeWidth bits)     // Shared batch time counter
    val wave = master port Stream(Bits(168 bits))   // 168-bit QICK wave word
    val trig = out    port Bool()                   // 1-bit readout trigger

    // Sticky status flags (stay set until cleared through `clear`; bit order matches `clear`)
    val dropOut   = out port Bool()                 // a released word was lost: output buffer full
    val dropSched = out port Bool()                 // a fire was lost: TimedQueue full (too many pulses scheduled)
    val late      = out port Bool()                 // a word could not leave on its release cycle (sent late)
    val clear     = in  port Bits(3 bits)           // one-cycle pulse per bit: 0 dropOut, 1 dropSched, 2 late
    val params    = withParamPort generate (slave port Flow(WaveFields(timeWidth)))  // decoded pulse fields at fire
  }

  // Registers hold each pulse field until fire
  val freq      = Reg(Bits(32 bits)) init 0
  val phase     = Reg(Bits(32 bits)) init 0
  val env       = Reg(Bits(24 bits)) init 0
  val gain      = Reg(Bits(32 bits)) init 0
  val nsamp     = Reg(Bits(32 bits)) init 0
  val conf      = Reg(Bits(16 bits)) init confInit
  val startTime = Reg(UInt(timeWidth bits)) init 0

  val cmd = io.cmd
  def hit(a: Int): Bool = cmd.valid && cmd.payload.address === a // True when a write targets address a

  when(hit(freqAddr))      { freq      := cmd.payload.data }
  when(hit(phaseAddr))     { phase     := cmd.payload.data }
  when(hit(envAddr))       { env       := cmd.payload.data(23 downto 0) }
  when(hit(gainAddr))      { gain      := cmd.payload.data }
  when(hit(nsampAddr))     { nsamp     := cmd.payload.data }
  when(hit(confAddr))      { conf      := cmd.payload.data(15 downto 0) }
  when(hit(startTimeAddr)) { startTime := cmd.payload.data(timeWidth - 1 downto 0).asUInt }

  // Fire strobe: Writing the fire address enqueues the current fields (the cmd path; off with io.params)
  val fire = if (withParamPort) False else hit(fireAddr)

  // Trigger registers. When to fire and how long to hold high
  val trigTime = Reg(UInt(timeWidth bits)) init 0
  val width    = Reg(UInt(widthBits bits)) init 0
  when(hit(trigTimeAddr)) { trigTime := cmd.payload.data(timeWidth - 1 downto 0).asUInt }
  when(hit(widthAddr))    { width    := cmd.payload.data(widthBits - 1 downto 0).asUInt }

  // Trigger fire strobe. Writing it enqueues a trigger at trigTime held for width cycles
  val fireTrig = hit(fireTrigAddr)

  // Packer: Concatenate the fields into the 168-bit sg_translator word
  // Bit layout: [167:152] conf(16) | [151:120] length(32) | [119:88] gain(32) | [87:64] env(24) | [63:32] phase(32) | [31:0] freq(32)
  val word = Bits(168 bits)
  word(31 downto 0)    := freq
  word(63 downto 32)   := phase
  word(87 downto 64)   := env
  word(119 downto 88)  := gain
  word(151 downto 120) := nsamp
  word(167 downto 152) := conf

  // Timed release. Fire the word when time equals startTime minus leadTime
  val q = TimedQueue(Bits(168 bits), timeWidth, depth, leadTime)
  q.io.time                   := io.time
  // Decoded-field input: pack each io.params beat (same layout as `word`) and queue it at its startTime
  val paramIn = withParamPort generate new Area {
    val f = io.params.payload
    val pword = Bits(168 bits)
    pword(31 downto 0)    := f.freq
    pword(63 downto 32)   := f.phase
    pword(87 downto 64)   := f.env
    pword(119 downto 88)  := f.gain
    pword(151 downto 120) := f.nsamp
    pword(167 downto 152) := conf
    q.io.push.valid             := io.params.valid
    q.io.push.payload.data      := pword
    q.io.push.payload.startTime := f.startTime
  }
  if (!withParamPort) {
    q.io.push.valid             := fire
    q.io.push.payload.data      := word
    q.io.push.payload.startTime := startTime
  }
  val push = q.io.push.valid      // a pulse entering the TimedQueue (cmd fire or io.params)

  // Output buffer: released words wait here while io.wave.ready is low (signal generator busy), and leave in
  // order. Zero latency when empty: if ready is high the word passes straight through on its release cycle,
  // so on-time pulses are still valid exactly at startTime minus leadTime.
  val buf = StreamFifo(Bits(168 bits), waveBufDepth, latency = 0)
  buf.io.push.valid   := q.io.pop.valid
  buf.io.push.payload := q.io.pop.payload
  io.wave << buf.io.pop

  // Status events (one cycle each)
  val dropOutEvt   = q.io.pop.valid && !buf.io.push.ready                           // released into a full buffer
  val dropSchedEvt = push && !q.io.push.ready                                        // fired into a full TimedQueue
  val lateEvt      = buf.io.push.fire && (buf.io.occupancy =/= 0 || !io.wave.ready) // queued instead of sent

  // Sticky flags: an event in the same cycle as a clear wins, so no event is ever missed
  def sticky(evt: Bool, clr: Bool): Bool = {
    val f = Reg(Bool()) init False
    when(clr) { f := False }
    when(evt) { f := True }
    f
  }
  io.dropOut   := sticky(dropOutEvt,   io.clear(0))
  io.dropSched := sticky(dropSchedEvt, io.clear(1))
  io.late      := sticky(lateEvt,      io.clear(2))

  // Readout trigger: Schedule with a TimedQueue and hold width cycles with a counter
  val tq = TimedQueue(UInt(widthBits bits), timeWidth, depth, leadTrig)  // Payload is the hold width
  tq.io.time                   := io.time
  tq.io.push.valid             := fireTrig
  tq.io.push.payload.data      := width
  tq.io.push.payload.startTime := trigTime

  val cnt  = Reg(UInt(widthBits bits)) init 0
  val trig = Reg(Bool()) init False
  when(tq.io.pop.valid) { trig := True; cnt := tq.io.pop.payload }  // Rise and load width at trigTime minus leadTrig
  when(cnt =/= 0)       { cnt := cnt - 1 }                          // Count down each cycle
  when(cnt === 1)       { trig := False }                          // Fall after width cycles
  io.trig := trig
}
