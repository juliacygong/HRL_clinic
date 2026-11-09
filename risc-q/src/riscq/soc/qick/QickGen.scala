package riscq.soc.qick

import spinal.core._
import spinal.core.sim._
import spinal.lib._
import spinal.lib.bus.amba4.axilite.{AxiLite4, AxiLite4Config}
import riscq.soc.link.RfCmd
import riscq.soc.rf.{PulseParamBuffer, PulseParamBufferParams, WaveFields, WaveWordBridge, WaveWordBridgeParams}

/**
 * QICK signal-generator path for a RISC-Q drive channel: [[WaveWordBridge]] → QICK `sg_translator`
 * (OUT_TYPE 0) → QICK `axis_signal_gen_v6`, the two QICK modules instantiated as BlackBoxes of the IP in
 * `firmware/ip/{qick_sg_translator,axis_signal_gen_v6}`. In Vivado the BlackBoxes resolve to that IP (the
 * gen's DDS Compiler sub-core and XPM primitives come from there); in Verilator `sg_translator.v` is real
 * and `axis_signal_gen_v6` needs a sim model (see `riscq.soc.qick.sim`).
 */

/** BlackBox of `firmware/ip/qick_sg_translator/src/sg_translator.v` (combinational, `aclk` unused). */
class SgTranslator(outType: Int = 0) extends BlackBox {
  addGeneric("OUT_TYPE", outType)
  val io = new Bundle {
    val aresetn               = in  Bool()
    val aclk                  = in  Bool()
    val s_axis_tdata          = in  Bits(168 bits)
    val s_axis_tvalid         = in  Bool()
    val s_axis_tready         = out Bool()
    val m_gen_v6_axis_tdata   = out Bits(160 bits)
    val m_gen_v6_axis_tvalid  = out Bool()
    val m_gen_v6_axis_tready  = in  Bool()
    val m_int4_axis_tdata     = out Bits(88 bits)
    val m_int4_axis_tvalid    = out Bool()
    val m_int4_axis_tready    = in  Bool()
    val m_mux4_axis_tdata     = out Bits(40 bits)
    val m_mux4_axis_tvalid    = out Bool()
    val m_mux4_axis_tready    = in  Bool()
    val m_readout_axis_tdata  = out Bits(88 bits)
    val m_readout_axis_tvalid = out Bool()
    val m_readout_axis_tready = in  Bool()
  }
  noIoPrefix()
  setDefinitionName("sg_translator")
  mapCurrentClockDomain(io.aclk, io.aresetn, resetActiveLevel = LOW)
  // repo-relative (mill runs from risc-q/); used by SpinalSim, Vivado takes the packaged IP.
  addRTLPath(new java.io.File("../firmware/ip/qick_sg_translator/src/sg_translator.v").getCanonicalPath)
}

/** BlackBox of `firmware/ip/axis_signal_gen_v6/src/axis_signal_gen_v6.v`. `s_axi`/`s0_axis` run on
 *  `hostCd`, `s1_axis`/`m_axis` on the current (dsp) domain. Resets are active low. */
class AxisSignalGenV6(n: Int, nDds: Int, genDds: Boolean, complexEnvelope: Boolean, hostCd: ClockDomain,
    emulator: Boolean = false) extends BlackBox {
  addGeneric("N", n)
  addGeneric("N_DDS", nDds)
  addGeneric("GEN_DDS", if (genDds) "TRUE" else "FALSE")
  addGeneric("ENVELOPE_TYPE", if (complexEnvelope) "COMPLEX" else "REAL")
  if (emulator) addGeneric("EMULATOR", 1)
  val io = new Bundle {
    val s_axi_aclk      = in  Bool()
    val s_axi_aresetn   = in  Bool()
    val s_axi_awaddr    = in  Bits(6 bits)
    val s_axi_awprot    = in  Bits(3 bits)
    val s_axi_awvalid   = in  Bool()
    val s_axi_awready   = out Bool()
    val s_axi_wdata     = in  Bits(32 bits)
    val s_axi_wstrb     = in  Bits(4 bits)
    val s_axi_wvalid    = in  Bool()
    val s_axi_wready    = out Bool()
    val s_axi_bresp     = out Bits(2 bits)
    val s_axi_bvalid    = out Bool()
    val s_axi_bready    = in  Bool()
    val s_axi_araddr    = in  Bits(6 bits)
    val s_axi_arprot    = in  Bits(3 bits)
    val s_axi_arvalid   = in  Bool()
    val s_axi_arready   = out Bool()
    val s_axi_rdata     = out Bits(32 bits)
    val s_axi_rresp     = out Bits(2 bits)
    val s_axi_rvalid    = out Bool()
    val s_axi_rready    = in  Bool()
    val s0_axis_aclk    = in  Bool()
    val s0_axis_aresetn = in  Bool()
    val s0_axis_tdata   = in  Bits(32 bits)
    val s0_axis_tvalid  = in  Bool()
    val s0_axis_tready  = out Bool()
    val aclk            = in  Bool()
    val aresetn         = in  Bool()
    val s1_axis_tdata   = in  Bits(160 bits)
    val s1_axis_tvalid  = in  Bool()
    val s1_axis_tready  = out Bool()
    val m_axis_tready   = in  Bool()
    val m_axis_tvalid   = out Bool()
    val m_axis_tdata    = out Bits(nDds * 16 bits)
  }
  noIoPrefix()
  setDefinitionName("axis_signal_gen_v6")
  mapCurrentClockDomain(io.aclk, io.aresetn, resetActiveLevel = LOW)
  mapClockDomain(hostCd, io.s_axi_aclk, io.s_axi_aresetn, resetActiveLevel = LOW)
  mapClockDomain(hostCd, io.s0_axis_aclk, io.s0_axis_aresetn, resetActiveLevel = LOW)
}

/** BlackBox of `firmware/ip/axis_cdcsync_v1/src/axis_cdcsync_v1.sv` (xpm_fifo_async, FWFT, depth 16):
 *  QICK's tProc → generator clock crossing. Only channel 0 is used (N = 1); the unused s/m channels are
 *  tied off because the IP ORs every `sN_axis_tvalid` into its FIFO write enable. `s_axis` runs on the
 *  current (dsp) domain, `m_axis` on `mCd`. Resets are active low. */
class AxisCdcSync(b: Int, mCd: ClockDomain, emulator: Boolean = false) extends BlackBox {
  addGeneric("N", 1)
  addGeneric("B", b)
  if (emulator) addGeneric("EMULATOR", 1)
  val s_axis_aresetn = in Bool()
  val s_axis_aclk    = in Bool()
  val m_axis_aresetn = in Bool()
  val m_axis_aclk    = in Bool()
  val s_tready = (0 until 16).map(i => out(Bool()).setName(s"s${i}_axis_tready"))
  val s_tvalid = (0 until 16).map(i => in(Bool()).setName(s"s${i}_axis_tvalid"))
  val s_tdata  = (0 until 16).map(i => in(Bits(b bits)).setName(s"s${i}_axis_tdata"))
  val m_tready = (0 until 16).map(i => in(Bool()).setName(s"m${i}_axis_tready"))
  val m_tvalid = (0 until 16).map(i => out(Bool()).setName(s"m${i}_axis_tvalid"))
  val m_tdata  = (0 until 16).map(i => out(Bits(b bits)).setName(s"m${i}_axis_tdata"))
  setDefinitionName("axis_cdcsync_v1")
  mapCurrentClockDomain(s_axis_aclk, s_axis_aresetn, resetActiveLevel = LOW)
  mapClockDomain(mCd, m_axis_aclk, m_axis_aresetn, resetActiveLevel = LOW)
}

/** Host-side ports of one gen_v6 (both on hostCd): AXI-Lite registers (START_ADDR @0x00, WE @0x04)
 *  and the 32-bit envelope-sample stream (`{Q, I}` per word) that fills the table while WE = 1. */
case class QickGenHost() extends Bundle with IMasterSlave {
  val s_axi   = AxiLite4(AxiLite4Config(addressWidth = 6, dataWidth = 32))
  val s0_axis = Stream(Bits(32 bits))
  override def asMaster(): Unit = { master(s_axi); master(s0_axis) }
}

/**
 * @param bridge  WaveWordBridge config. `leadTime` = 32 is gen_v6's accept → first `m_axis_tvalid`
 *                latency (xsim-characterised, `firmware/formal/README.md` on `formal/sg-v6-tproc-v2`).
 *                That latency is 32 *genCd* cycles, and the CDC adds a few more, while `leadTime` counts
 *                dsp cycles — the same length at the default genFreqHz = dspFreqHz, an approximation
 *                otherwise.
 *                TODO: re-characterise against the real CDC + gen in xsim.
 *                The bridge takes its pulse fields from the channel's PulseParamBuffer (io.params); its
 *                own cmd registers only hold `conf` and the readout trigger, moved past the buffer's
 *                startTime (0x4100) so they never overlap the compiler's map. `conf` resets to 0x08:
 *                outsel = envelope × DDS, one-shot, output 0 when idle (stdysel = 1), no phase reset.
 * @param envN    log2 of the gen's envelope-table depth (QICK generic N).
 * @param nDds    samples per aclk (QICK N_DDS) = the DAC batch (16).
 * @param genFreqHz / dspFreqHz  gen (DAC fabric) and dsp clocks: `dur` counts dsp cycles (batches), gen_v6's
 *                `nsamp` counts gen cycles. By default both are 500 MHz (DACs at 8 GS/s), so nsamp = dur
 *                with no arithmetic; otherwise (e.g. QICK's 599.04 MHz) nsamp = round(dur × genFreqHz /
 *                dspFreqHz), a constant multiply on the fire path.
 * @param emulator  sim only: sets the QICK IP's EMULATOR generic (behavioural FIFO, BRAM and DDS models instead of
 *                the XPM and DDS Compiler primitives), the same models QICKEmu uses. See `riscq.soc.qick.sim`.
 */
case class QickGenParams(
    // depth 32: a program may queue many waveforms ahead (a flat-top is 3), and a full queue drops pulses
    bridge: WaveWordBridgeParams = WaveWordBridgeParams(leadTime = 32, depth = 32, withParamPort = true, confInit = 0x08,
      confAddr = 0x4104, trigTimeAddr = 0x4108, widthAddr = 0x410c, fireTrigAddr = 0x4110),
    envN: Int = 12,
    nDds: Int = 16,
    genDds: Boolean = true,
    complexEnvelope: Boolean = true,
    genFreqHz: Double = 500e6,
    dspFreqHz: Double = 500e6,
    emulator: Boolean = false
) {
  require(bridge.withParamPort, "QickGenChannel feeds the bridge from its PulseParamBuffer (withParamPort)")
}

/** One QICK drive channel, the same chain QICK builds after its tProc:
 *
 *    RfCmd window → PulseParamBuffer → WaveWordBridge ─(dsp)─► axis_cdcsync_v1 ─(gen)─► sg_translator → axis_signal_gen_v6
 *
 *  The window keeps the RISC-Q register map the compiler targets: a PulseParamBuffer (the same module as a
 *  native drive channel, with `buf` giving its widths) decodes it — slot table, fire by index, startTime
 *  with auto-advance, freq, phaseOffset. On each fire its decoded fields are packed into the QICK wave word
 *  by the bridge (io.params) and queued at the pulse's startTime:
 *    freq  = the freq register (latest write before the fire)    phase = table phase + phaseOffset
 *    gain  = amp (sign-extended)    env = addr    nsamp = dur (× genFreqHz / dspFreqHz, rounded, if they differ)
 *  dcOffset is accepted but unused (gen_v6 has no DC offset). The bridge's readout-trigger registers sit at
 *  0x4108.. on the same window.
 *
 *  freq and conf are kept per table slot, so a program can load every waveform of a channel once and then
 *  play one with only a startTime write and a fire:
 *    slotConf(i) @ confTableAddr + 4i (0x4200..)    slotFreq(i) @ freqTableAddr + 4i (0x4300..)
 *  The single-register forms still work and write every slot at once: freq @ 0x4 and conf @ 0x4104, each
 *  written before a fire, behave as before. With `buf.fireAtAddr` / `buf.fireSlotAddr` set (mkQickChannel:
 *  0x4400 / 0x4480), a pulse is one store: fireAt(i) = start time + fire slot i, fireSlot(i) = fire slot i next.
 *
 *  `status` is the bridge's sticky flags (bit 0 dropOut, 1 dropSched, 2 late), cleared by `clear`.
 *
 *  The buffer and bridge run on the current (dsp) domain; the CDC crosses into `genCd` (the DAC fabric
 *  clock, `genFreqHz`), where the translator and the gen run, as in QICK's block design.
 *  `samples` (genCd) carries the gen's `nDds` 16-bit real samples per cycle = gen `m_axis`, for the RFDC.
 *  `released` (dsp) pulses when the bridge hands a word to the CDC. */
case class QickGenChannel(p: QickGenParams, buf: PulseParamBufferParams, hostCd: ClockDomain, genCd: ClockDomain)
    extends Component {
  require(buf.addrWidth == p.bridge.addrWidth && buf.timeWidth == p.bridge.timeWidth,
    "PulseParamBuffer and bridge must share the window address width and time width")
  require(buf.fw == 32 && buf.pw == 32, "QICK channels take 32-bit freq/phase (QICK's DDS resolution)")
  val io = new Bundle {
    val cmd      = slave  port Flow(RfCmd(buf.addrWidth))
    val time     = in     port UInt(buf.timeWidth bits)   // shared time broadcast (the buffer keeps a local copy)
    val samples  = master port Stream(Bits(p.nDds * 16 bits))
    val released = out    port Bool()
    val trig     = out    port Bool()
    val host     = slave  port QickGenHost()
    val status   = out    port Bits(3 bits)               // sticky: 0 dropOut, 1 dropSched, 2 late
    val clear    = in     port Bits(3 bits)               // clear the matching status bit (level)
  }

  // the compiler-facing register file: same module and map as a native drive channel
  val params = PulseParamBuffer(buf)
  params.io.cmd << io.cmd
  params.io.timeBcast := io.time

  // per-slot freq and conf, read by the fired slot. A cmd write takes effect the next cycle; the fired entry
  // reaches `fields` 2 cycles after its fire beat, so any write posted before the fire is seen.
  //
  // Storage: one distributed-RAM word per slot (LUTRAM, which comes in 32-deep blocks, so up to 32 slots cost
  // the same as 8) plus a shared default. A single-register write (freq @ 0x4, conf @ 0x4104) sets the default
  // and clears every slot's "own value" bit, so all slots read the default, as when it wrote every slot; a
  // per-slot write stores that slot's word and sets its bit. Only the bit vector is flip-flops.
  require(buf.pulseNum <= 64, "slot conf / freq windows hold 64 words")
  val confTableAddr = 0x4200
  val freqTableAddr = 0x4300
  val slotBits = log2Up(buf.pulseNum)
  val c = io.cmd
  def hit(a: Int): Bool = c.valid && c.payload.address === a
  def window(base: Int): Bool = c.valid && (c.payload.address >> 8) === (base >> 8) &&
    c.payload.address(7 downto 2) < buf.pulseNum
  val wrIdx = c.payload.address(2, slotBits bits)
  case class SlotTable(width: Int, init: BigInt, base: Int, globalHit: Bool) extends Area {
    val mem   = Mem(Bits(width bits), buf.pulseNum)
    val dflt  = Reg(Bits(width bits)) init init
    val own   = Reg(Bits(buf.pulseNum bits)) init 0
    val wr    = window(base)
    mem.write(wrIdx, c.payload.data(width - 1 downto 0), wr)
    when(wr) { own(wrIdx) := True }
    when(globalHit) { dflt := c.payload.data(width - 1 downto 0); own := 0 }
    def read(i: UInt): Bits = own(i) ? mem.readAsync(i) | dflt
  }
  val confT = SlotTable(16, p.bridge.confInit, confTableAddr, hit(p.bridge.confAddr))
  // freq @ 0x4 is the buffer's freq register (it lands via params.io.freq one cycle later; the same value)
  val freqT = SlotTable(32, 0, freqTableAddr, hit(buf.freqAddr))
  // the fired slot: the buffer's latched index (any fire form) is one cycle ahead of its param flows, so one
  // register lines it up with params.io.amp.valid (back-to-back fires stay paired)
  val outSlot = RegNext(params.io.firedIndex) init 0

  // pack the fired entry into the bridge's fields. One register stage (Flow.stage) after the buffer's fire
  // output keeps the field packing (and any dur → nsamp multiply) off the TimedQueue push path; startTime
  // travels with it.
  val fields = Flow(WaveFields(buf.timeWidth))
  fields.valid             := params.io.amp.valid
  fields.payload.freq      := freqT.read(outSlot)
  fields.payload.conf      := confT.read(outSlot)
  fields.payload.phase     := (params.io.phase.payload + params.io.phaseOffset).asBits
  fields.payload.gain      := params.io.amp.payload.resize(32 bits).asBits
  fields.payload.env       := params.io.addr.payload.resize(24 bits).asBits
  if (p.genFreqHz == p.dspFreqHz) {
    // a gen cycle is a dsp batch: nsamp = dur, which fits gen_v6's nsamp[15:0]
    require(buf.durWidth <= 16, "nsamp = dur needs dur within gen_v6's 16-bit nsamp")
    fields.payload.nsamp   := params.io.dur.payload.resize(32 bits).asBits
  } else {
    // gen_v6 plays nsamp[15:0] only (sg_translator), so saturate instead of wrapping: at 599.04 MHz,
    // dur > ~54700 batches (~109 us) plays the 65535-cycle maximum
    val nsampScale = BigInt(scala.math.round(p.genFreqHz / p.dspFreqHz * (1 << 16)))
    val nsampFull  = (params.io.dur.payload * U(nsampScale) + (1 << 15)) >> 16
    fields.payload.nsamp   := (nsampFull > 0xFFFF) ? B(0xFFFF, 32 bits) | nsampFull.resize(32 bits).asBits
  }
  fields.payload.startTime := params.io.startTime

  val bridge = WaveWordBridge(p.bridge)
  bridge.io.cmd    << io.cmd        // conf + readout trigger registers at 0x4104..
  bridge.io.params << fields.stage()
  bridge.io.time   := params.io.time
  bridge.io.clear  := io.clear
  io.status        := bridge.io.late ## bridge.io.dropSched ## bridge.io.dropOut
  io.trig          := bridge.io.trig
  io.released      := bridge.io.wave.fire
  // sims log the words handed to the CDC (QickCpuSim RISCQ_WORDS)
  bridge.io.wave.valid.simPublic(); bridge.io.wave.ready.simPublic(); bridge.io.wave.payload.simPublic()
  params.io.time.simPublic()

  val cdc = new AxisCdcSync(168, genCd, p.emulator)
  cdc.s_tdata(0)       := bridge.io.wave.payload
  cdc.s_tvalid(0)      := bridge.io.wave.valid
  bridge.io.wave.ready := cdc.s_tready(0)
  for (i <- 1 until 16) { cdc.s_tvalid(i) := False; cdc.s_tdata(i) := 0; cdc.m_tready(i) := True } // unused channels

  val translator = genCd(new SgTranslator(outType = 0))
  translator.io.s_axis_tdata  := cdc.m_tdata(0)
  translator.io.s_axis_tvalid := cdc.m_tvalid(0)
  cdc.m_tready(0)             := translator.io.s_axis_tready
  translator.io.m_int4_axis_tready    := False
  translator.io.m_mux4_axis_tready    := False
  translator.io.m_readout_axis_tready := False

  val gen = genCd(new AxisSignalGenV6(p.envN, p.nDds, p.genDds, p.complexEnvelope, hostCd, p.emulator))
  gen.io.s1_axis_tdata  := translator.io.m_gen_v6_axis_tdata
  gen.io.s1_axis_tvalid := translator.io.m_gen_v6_axis_tvalid
  translator.io.m_gen_v6_axis_tready := gen.io.s1_axis_tready
  gen.io.m_axis_tready  := io.samples.ready
  io.samples.valid      := gen.io.m_axis_tvalid
  io.samples.payload    := gen.io.m_axis_tdata

  // host AXI-Lite + envelope stream straight through to the gen (gen-internal CDC to aclk)
  val h = io.host
  gen.io.s_axi_awaddr  := h.s_axi.aw.payload.addr.asBits
  gen.io.s_axi_awprot  := h.s_axi.aw.payload.prot
  gen.io.s_axi_awvalid := h.s_axi.aw.valid
  h.s_axi.aw.ready     := gen.io.s_axi_awready
  gen.io.s_axi_wdata   := h.s_axi.w.payload.data
  gen.io.s_axi_wstrb   := h.s_axi.w.payload.strb
  gen.io.s_axi_wvalid  := h.s_axi.w.valid
  h.s_axi.w.ready      := gen.io.s_axi_wready
  h.s_axi.b.payload.resp := gen.io.s_axi_bresp
  h.s_axi.b.valid      := gen.io.s_axi_bvalid
  gen.io.s_axi_bready  := h.s_axi.b.ready
  gen.io.s_axi_araddr  := h.s_axi.ar.payload.addr.asBits
  gen.io.s_axi_arprot  := h.s_axi.ar.payload.prot
  gen.io.s_axi_arvalid := h.s_axi.ar.valid
  h.s_axi.ar.ready     := gen.io.s_axi_arready
  h.s_axi.r.payload.data := gen.io.s_axi_rdata
  h.s_axi.r.payload.resp := gen.io.s_axi_rresp
  h.s_axi.r.valid      := gen.io.s_axi_rvalid
  gen.io.s_axi_rready  := h.s_axi.r.ready
  gen.io.s0_axis_tdata  := h.s0_axis.payload
  gen.io.s0_axis_tvalid := h.s0_axis.valid
  h.s0_axis.ready       := gen.io.s0_axis_tready
}
