package riscq.soc.comm

import spinal.core._

/**
 * SpinalHDL blackbox over QICK's board-communication protocol core
 * (`firmware/ip/qick_com/src/qick_com.sv`) — the TX/RX state machines, the received-data
 * registers, and the multi-board sync logic, driving a 4-pin PMOD link through its internal
 * `qcom_link` PHY.
 *
 * '''This wraps `qick_com`, NOT `axi_qick_com`.''' The AXI wrapper exists so the ARM PS can reach
 * the module over AXI-Lite; RISC-Q drives it from its own side instead, so the wrapper is dead
 * weight — and skipping it also skips `axi_slv_qcom.vhd`, the one file in the IP that Verilator
 * cannot read. The remaining dependency set (`qick_com.sv`, `qcom_link.sv`, `_qcom_ips.sv`) is
 * pure SystemVerilog and simulates directly; see [[riscq.soc.sim.QickComSim]].
 *
 * ==Command encoding==
 * `cmd_op_i` is decoded inside the core as `{type, size[1:0], dst}`:
 * {{{
 *   cmd_op_i[3]   type — set-vs-clear for flags, data-vs-SYNC for the 8-bit size
 *   cmd_op_i[2:1] payload size — 00 flag (1 bit), 01 8-bit/SYNC, 10 16-bit, 11 32-bit
 *   cmd_op_i[0]   destination register on the FAR side — 0 => qcom_dt1_o, 1 => qcom_dt2_o
 * }}}
 * so e.g. `0x6` sends 32 bits to the peer's `dt1`, `0x7` to its `dt2`, `0x8` sets the peer's flag
 * and `0x0` clears it. See [[QickCom.Op]].
 *
 * ==Handshake==
 * Raise `cmd_req_i`; the core leaves its idle state and raises `cmd_ack_o` (which is simply
 * `!qcom_rdy_o`). Drop `cmd_req_i` once acknowledged. A 32-bit packet is 12 link symbols, each
 * lasting roughly `qcom_cfg_i` core clocks.
 *
 * ==Clocks==
 * Two domains: `c_clk_i` runs the protocol, `t_clk_i` the sync/restart handshake. Both may be
 * driven from one clock. Both resets are '''active low'''.
 *
 * ==Ports not used by RISC-Q==
 * `qproc_start_o` is QICK's multi-board sync output — it restarts the tProcessor on a shared tick.
 * RISC-Q has no processor to restart; the intended target is the SoC's `timeOffset` register, so
 * that a sync adjusts the shared `time` counter instead. Left exposed here, unconsumed.
 */
case class QickCom() extends BlackBox {
  setDefinitionName("qick_com")

  val io = new Bundle {
    // clocks / resets (both resets ACTIVE LOW)
    val c_clk_i  = in Bool ()
    val c_rst_ni = in Bool ()
    val t_clk_i  = in Bool ()
    val t_rst_ni = in Bool ()

    // external sync tick (SYNC commands wait for its rising edge) + link timing config
    val pulse_i    = in Bool ()
    val qcom_cfg_i = in Bits (4 bits) // tick_cfg: symbol period in c_clk cycles

    // command issue
    val cmd_req_i = in Bool ()
    val cmd_ack_o = out Bool ()
    val cmd_op_i  = in Bits (4 bits)
    val cmd_dt_i  = in Bits (32 bits)

    // received data
    val qcom_rdy_o  = out Bool ()      // high while idle / ready for a new command
    val qcom_dt1_o  = out Bits (32 bits)
    val qcom_dt2_o  = out Bits (32 bits)
    val qcom_vld_o  = out Bool ()      // ONE-CYCLE pulse when a register write lands
    val qcom_flag_o = out Bool ()      // sticky 1-bit flag, set/cleared by flag packets

    // multi-board sync output (see class doc — retarget at timeOffset)
    val qproc_start_o = out Bool ()

    // the 4-pin link: [3] = strobe (toggles per symbol), [2:0] = data
    val pmod_i = in Bits (4 bits)
    val pmod_o = out Bits (4 bits)

    // debug taps
    val qcom_tx_dt_do  = out Bits (32 bits)
    val qcom_rx_dt_do  = out Bits (32 bits)
    val qcom_status_do = out Bits (32 bits)
    val qcom_debug_do  = out Bits (16 bits)
    val qcom_do        = out Bits (32 bits)
  }
  noIoPrefix()

  /** Drive both clock/reset pairs from one SpinalHDL clock domain (resets inverted to active-low). */
  def driveClocksFrom(cd: ClockDomain): this.type = {
    io.c_clk_i  := cd.readClockWire
    io.t_clk_i  := cd.readClockWire
    io.c_rst_ni := !cd.readResetWire
    io.t_rst_ni := !cd.readResetWire
    this
  }
}

object QickCom {
  /** RTL sources this blackbox needs, relative to the repo root's `risc-q/` working directory. */
  val rtlSources: Seq[String] = Seq(
    "../firmware/ip/qick_com/src/qick_com.sv",
    "../firmware/ip/qick_com/src/qcom_link.sv",
    "../firmware/ip/qick_com/src/_qcom_ips.sv"
  )

  /** `cmd_op_i` encodings — see the class doc for the bit layout. */
  object Op {
    val clearFlag = 0x0 // size=00, type=0
    val setFlag   = 0x8 // size=00, type=1
    val send8Dt1  = 0x2 // size=01, type=0, dst=0
    val sync      = 0xa // size=01, type=1 — the multi-board SYNC command
    val send16Dt1 = 0x4 // size=10, type=0, dst=0
    val send32Dt1 = 0x6 // size=11, type=0, dst=0
    val send32Dt2 = 0x7 // size=11, type=0, dst=1
  }
}
