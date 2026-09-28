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
 */
case class WaveWordBridgeParams(
    addrWidth: Int = 16,      // Address width of RfCmd
    timeWidth: Int = 32,      // Batch time counter width
    depth: Int = 8,           // TimedQueue depth
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
    fireTrigAddr: Int = 0x28
)

case class WaveWordBridge(p: WaveWordBridgeParams = WaveWordBridgeParams()) extends Component {
  import p._

  val io = new Bundle {
    val cmd  = slave  port Flow(RfCmd(addrWidth))   // Register writes stream from the core
    val time = in     port UInt(timeWidth bits)     // Shared batch time counter
    val wave = master port Stream(Bits(168 bits))   // 168-bit QICK wave word
    val trig = out    port Bool()                   // 1-bit readout trigger
  }

  // Registers hold each pulse field until fire
  val freq      = Reg(Bits(32 bits)) init 0
  val phase     = Reg(Bits(32 bits)) init 0
  val env       = Reg(Bits(24 bits)) init 0
  val gain      = Reg(Bits(32 bits)) init 0
  val nsamp     = Reg(Bits(32 bits)) init 0
  val conf      = Reg(Bits(16 bits)) init 0
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

  // Fire strobe: Writing the fire address enqueues the current fields
  val fire = hit(fireAddr)

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
  q.io.push.valid             := fire
  q.io.push.payload.data      := word
  q.io.push.payload.startTime := startTime

  // AXIS output with no hand-off buffer. Drive straight from the fire-once pop
  io.wave.valid   := q.io.pop.valid
  io.wave.payload := q.io.pop.payload

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
