package riscq.soc.comm

import spinal.core._

/**
 * SpinalHDL blackbox over QICK's '''XCOM''' IP (`firmware/ip/xcom/src/xcom.sv`) — the full-mesh
 * board-to-board synchronization and message bus described in Martin et al., *XCOM: Full Mesh
 * Network Synchronization and Low-Latency Communication for QICK* (arXiv:2603.18977).
 *
 * XCOM supersedes the older PMOD-based [[QickCom]]. Three differences matter to RISC-Q:
 *
 *  1. '''It is entirely SystemVerilog''', AXI-Lite slave included — so the whole IP simulates under
 *     Verilator. [[QickCom]]'s AXI wrapper is VHDL, which forced us to wrap only its protocol core.
 *  2. '''It exposes the time counter directly.''' `o_time_update` + `o_time_update_data` load a new
 *     absolute-time value; `o_time_rst` zeroes it. In RISC-Q that is exactly the `timeOffset`
 *     register behind `time = refTime + timeOffset` — the value every `TimedQueue` compares
 *     against. QickCom offered only "restart the processor", which has no RISC-V analogue.
 *  3. '''Full mesh.''' Each board drives one Tx pair and listens on `NCH` Rx pairs (one per board in
 *     the network, including its own loopback through the fanout hub). Boards carry a 4-bit network
 *     ID; one board is designated master and broadcasts the clock-alignment commands.
 *
 * Per the paper, network synchronization happens '''once''', when the network is configured or a
 * node joins — not during a running experiment. That removes the "is a mid-run resync safe?"
 * problem the older link would have posed.
 *
 * ==Command interface (`i_core_clk` domain)==
 * Raise `i_core_en` with an opcode on `i_core_op` and operands on `i_core_data1`/`i_core_data2`.
 * `o_core_ready` falls while the command is in flight. For network sends, `data1` carries the
 * destination board id and `data2` the payload (see the `QICK_Xcom` Python driver). Opcodes are
 * 5 bits: bit 4 selects a '''local''' command (configure this board) over a '''network''' command;
 * bits 3:0 are the operation — see [[Xcom.Op]].
 *
 * ==Clock domains==
 * Three: `i_ps_clk` (AXI), `i_core_clk` (protocol + command), `i_time_clk` (the absolute-time
 * counter). All may be driven from one clock in simulation.
 *
 * @param nch number of receive channels — one per board in the mesh.
 */
case class Xcom(nch: Int = 2) extends BlackBox {
  setDefinitionName("xcom")
  addGeneric("NCH", nch)
  addGeneric("SYNC", 1)
  addGeneric("DEBUG", 1)

  val io = new Bundle {
    // clocks / resets (all resets ACTIVE LOW)
    val i_ps_clk    = in Bool (); val i_ps_rstn   = in Bool ()
    val i_core_clk  = in Bool (); val i_core_rstn = in Bool ()
    val i_time_clk  = in Bool (); val i_time_rstn = in Bool ()

    // command interface from the processor
    val i_core_en    = in Bool ()
    val i_core_op    = in Bits (5 bits)
    val i_core_data1 = in Bits (32 bits)   // network sends: destination board id
    val i_core_data2 = in Bits (32 bits)   // network sends: payload
    val o_core_ready = out Bool ()
    val o_core_data1 = out Bits (32 bits)
    val o_core_data2 = out Bits (32 bits)
    val o_core_valid = out Bool ()
    val o_core_flag  = out Bool ()

    // external sync input + the control outputs RISC-Q cares about
    val i_sync             = in Bool ()
    val o_proc_start       = out Bool ()
    val o_proc_stop        = out Bool ()
    val o_time_rst         = out Bool ()        // zero the absolute-time counter
    val o_time_update      = out Bool ()        // load it with...
    val o_time_update_data = out Bits (32 bits) // ...this value   <- wire to timeOffset
    val o_core_start       = out Bool ()
    val o_core_stop        = out Bool ()
    val o_xcom_id          = out Bits (4 bits)  // this board's network id

    // the mesh: listen on nch channels, speak on one
    val i_xcom_clk  = in Bits (nch bits)
    val i_xcom_data = in Bits (nch bits)
    val o_xcom_clk  = out Bool ()
    val o_xcom_data = out Bool ()

    // AXI4-Lite control (6-bit address)
    val s_axi_awaddr  = in Bits (6 bits);   val s_axi_awprot  = in Bits (3 bits)
    val s_axi_awvalid = in Bool ();         val s_axi_awready = out Bool ()
    val s_axi_wdata   = in Bits (32 bits);  val s_axi_wstrb   = in Bits (4 bits)
    val s_axi_wvalid  = in Bool ();         val s_axi_wready  = out Bool ()
    val s_axi_bresp   = out Bits (2 bits);  val s_axi_bvalid  = out Bool ()
    val s_axi_bready  = in Bool ()
    val s_axi_araddr  = in Bits (6 bits);   val s_axi_arprot  = in Bits (3 bits)
    val s_axi_arvalid = in Bool ();         val s_axi_arready = out Bool ()
    val s_axi_rdata   = out Bits (32 bits); val s_axi_rresp   = out Bits (2 bits)
    val s_axi_rvalid  = out Bool ();        val s_axi_rready  = in Bool ()
  }
  noIoPrefix()

  /** Drive all three clock/reset pairs from one SpinalHDL domain (resets inverted to active-low). */
  def driveClocksFrom(cd: ClockDomain): this.type = {
    io.i_ps_clk   := cd.readClockWire; io.i_ps_rstn   := !cd.readResetWire
    io.i_core_clk := cd.readClockWire; io.i_core_rstn := !cd.readResetWire
    io.i_time_clk := cd.readClockWire; io.i_time_rstn := !cd.readResetWire
    this
  }

  /** Tie off the AXI-Lite slave — RISC-Q drives XCOM through the core command port, not AXI. */
  def idleAxi(): this.type = {
    io.s_axi_awaddr := 0; io.s_axi_awprot := 0; io.s_axi_awvalid := False
    io.s_axi_wdata  := 0; io.s_axi_wstrb  := 0; io.s_axi_wvalid  := False
    io.s_axi_bready := False
    io.s_axi_araddr := 0; io.s_axi_arprot := 0; io.s_axi_arvalid := False
    io.s_axi_rready := False
    this
  }
}

object Xcom {
  /** RTL sources, in dependency order — `fxp_pkg` MUST precede `qick_pkg`. Paths are relative to
   *  the `risc-q/` working directory. */
  val rtlSources: Seq[String] = Seq(
    "fxp_pkg", "qick_pkg", "xcom", "xcom_axil_slv", "xcom_txrx", "xcom_cmd",
    "xcom_link_tx", "xcom_link_rx", "xcom_qctrl", "xcom_cdc", "req_ack_cmd",
    "rx_cmd", "tx_cmd", "synchronizer", "rising_edge_det",
    "narrow_en_signal", "wide_en_signal"
  ).map(f => s"../firmware/ip/xcom/src/$f.sv")

  /** `i_core_op` encodings. Bit 4 selects a LOCAL command (configure this board) over a NETWORK
   *  command; bits 3:0 are the operation. Mirrors `QICK_Xcom.opcodes` in the Python driver. */
  object Op {
    // network commands — data1 = destination board id, data2 = payload
    val clearFlag  = 0x00
    val setFlag    = 0x01
    val send8Dt1   = 0x02; val send8Dt2  = 0x03
    val send16Dt1  = 0x04; val send16Dt2 = 0x05
    val send32Dt1  = 0x06; val send32Dt2 = 0x07
    val qrstSync   = 0x08   // broadcast: align every board's absolute time counter
    val autoId     = 0x09
    val updateDt8  = 0x0a; val updateDt16 = 0x0c; val updateDt32 = 0x0e
    val qctrl      = 0x0b
    // local commands (bit 4 set) — configure this board
    val setId      = 0x10
    val writeFlag  = 0x11
    val writeReg   = 0x12
    val writeMem   = 0x13
    val reset      = 0x1f
  }
}
