package riscq.soc.qick

import spinal.core._
import spinal.lib._
import spinal.lib.bus.amba4.axilite.{AxiLite4, AxiLite4Config}
import riscq.soc.link.RfCmd
import riscq.soc.rf.{WaveWordBridge, WaveWordBridgeParams}

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
class AxisSignalGenV6(n: Int, nDds: Int, genDds: Boolean, complexEnvelope: Boolean, hostCd: ClockDomain)
    extends BlackBox {
  addGeneric("N", n)
  addGeneric("N_DDS", nDds)
  addGeneric("GEN_DDS", if (genDds) "TRUE" else "FALSE")
  addGeneric("ENVELOPE_TYPE", if (complexEnvelope) "COMPLEX" else "REAL")
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

/** Host-side ports of one gen_v6 (both on hostCd): AXI-Lite registers (START_ADDR @0x00, WE @0x04)
 *  and the 32-bit envelope-sample stream (`{Q, I}` per word) that fills the table while WE = 1. */
case class QickGenHost() extends Bundle with IMasterSlave {
  val s_axi   = AxiLite4(AxiLite4Config(addressWidth = 6, dataWidth = 32))
  val s0_axis = Stream(Bits(32 bits))
  override def asMaster(): Unit = { master(s_axi); master(s0_axis) }
}

/**
 * @param bridge  WaveWordBridge config. `leadTime` = 32 is gen_v6's accept → first `m_axis_tvalid`
 *                latency (xsim-characterised, `firmware/formal/README.md` on `formal/sg-v6-tproc-v2`),
 *                so a pulse with startTime T leaves the gen at batch time T.
 * @param envN    log2 of the gen's envelope-table depth (QICK generic N).
 * @param nDds    samples per aclk (QICK N_DDS) = the DAC batch (16).
 */
case class QickGenParams(
    bridge: WaveWordBridgeParams = WaveWordBridgeParams(leadTime = 32),
    envN: Int = 12,
    nDds: Int = 16,
    genDds: Boolean = true,
    complexEnvelope: Boolean = true
)

/** One QICK drive channel, clocked by the current (dsp) domain: RfCmd window → bridge → translator → gen.
 *  `samples` carries the gen's `nDds` 16-bit real samples per cycle; `valid` = `m_axis_tvalid` (pulse on). */
case class QickGenChannel(p: QickGenParams, hostCd: ClockDomain) extends Component {
  val io = new Bundle {
    val cmd     = slave  port Flow(RfCmd(p.bridge.addrWidth))
    val time    = in     port UInt(p.bridge.timeWidth bits)
    val samples = master port Flow(Bits(p.nDds * 16 bits))
    val trig    = out    port Bool()
    val host    = slave  port QickGenHost()
  }

  val bridge = WaveWordBridge(p.bridge)
  bridge.io.cmd  << io.cmd
  bridge.io.time := io.time
  io.trig        := bridge.io.trig

  val translator = new SgTranslator(outType = 0)
  translator.io.s_axis_tdata  := bridge.io.wave.payload
  translator.io.s_axis_tvalid := bridge.io.wave.valid
  bridge.io.wave.ready        := translator.io.s_axis_tready
  translator.io.m_int4_axis_tready    := False
  translator.io.m_mux4_axis_tready    := False
  translator.io.m_readout_axis_tready := False

  val gen = new AxisSignalGenV6(p.envN, p.nDds, p.genDds, p.complexEnvelope, hostCd)
  gen.io.s1_axis_tdata  := translator.io.m_gen_v6_axis_tdata
  gen.io.s1_axis_tvalid := translator.io.m_gen_v6_axis_tvalid
  translator.io.m_gen_v6_axis_tready := gen.io.s1_axis_tready
  gen.io.m_axis_tready  := True                 // the DAC path always accepts
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
