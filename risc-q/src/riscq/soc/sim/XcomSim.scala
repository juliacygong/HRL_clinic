package riscq.soc.sim

import spinal.core._
import spinal.core.sim._
import riscq.soc.comm.Xcom

/**
 * Two [[Xcom]] boards wired as a 2-node full mesh — the simulation stand-in for the paper's fanout
 * hub. Each board drives one Tx pair; the hub copies every Tx to every board's Rx, so each board
 * listens on both channels including its own loopback.
 */
class XcomMesh extends Component {
  val nch = 1   // point-to-point: each board hears only the OTHER board (no self-loopback)
  val io = new Bundle {
    val en    = in Bool ()
    val op    = in Bits (5 bits)
    val dt1   = in Bits (32 bits)   // destination board id, for network sends
    val dt2   = in Bits (32 bits)   // payload
    val which = in Bool ()          // false = drive board A, true = drive board B
    val sync  = in Bool ()
    val rstn  = in Bool ()   // ACTIVE LOW, driven directly by the testbench
    // minimal AXI-Lite write port, driven to BOTH boards at once (they take identical config)
    val axiAddr  = in Bits (6 bits)
    val axiData  = in Bits (32 bits)
    val axiWrEn  = in Bool ()
    val axiReady = out Bool ()
    val axiBvalid = out Bool ()
    val aTxClk = out Bool (); val aTxData = out Bool ()   // the link wire, for Tx-vs-Rx triage

    val aReady = out Bool (); val bReady = out Bool ()
    val aDt1   = out Bits (32 bits); val aDt2 = out Bits (32 bits)
    val bDt1   = out Bits (32 bits); val bDt2 = out Bits (32 bits)
    val aVld   = out Bool (); val bVld  = out Bool ()
    val aFlag  = out Bool (); val bFlag = out Bool ()
    val aId    = out Bits (4 bits); val bId = out Bits (4 bits)

    // the control outputs RISC-Q would consume
    val aTimeRst = out Bool (); val bTimeRst = out Bool ()
    val aTimeUpd = out Bool (); val bTimeUpd = out Bool ()
    val aTimeDat = out Bits (32 bits); val bTimeDat = out Bits (32 bits)
    val aProcStart = out Bool (); val bProcStart = out Bool ()
  }

  val a = Xcom(nch)
  val b = Xcom(nch)
  // AXI-Lite writes go to both boards; reads are unused.
  for (x <- List(a, b)) {
    x.io.s_axi_awaddr := io.axiAddr; x.io.s_axi_awprot := 0; x.io.s_axi_awvalid := io.axiWrEn
    x.io.s_axi_wdata  := io.axiData; x.io.s_axi_wstrb  := B"1111"; x.io.s_axi_wvalid := io.axiWrEn
    x.io.s_axi_bready := True
    x.io.s_axi_araddr := 0; x.io.s_axi_arprot := 0; x.io.s_axi_arvalid := False
    x.io.s_axi_rready := False
  }
  io.axiReady  := a.io.s_axi_awready && a.io.s_axi_wready
  io.axiBvalid := a.io.s_axi_bvalid
  io.aTxClk := a.io.o_xcom_clk; io.aTxData := a.io.o_xcom_data
  // Drive clocks from the domain but resets from an explicit port: deriving the active-low resets
  // from `readResetWire` left XCOM's registers un-reset (board ids came up as garbage, differing
  // between two identically-configured instances - see the VCD).
  for (x <- List(a, b)) {
    x.io.i_ps_clk   := clockDomain.readClockWire; x.io.i_ps_rstn   := io.rstn
    x.io.i_core_clk := clockDomain.readClockWire; x.io.i_core_rstn := io.rstn
    x.io.i_time_clk := clockDomain.readClockWire; x.io.i_time_rstn := io.rstn
  }

  // point-to-point cross-wire. (The paper's hub also loops each board's Tx back to itself; that
  // variant is the nch=2 case and is worth re-testing once basic reception works.)
  a.io.i_xcom_clk  := b.io.o_xcom_clk.asBits
  a.io.i_xcom_data := b.io.o_xcom_data.asBits
  b.io.i_xcom_clk  := a.io.o_xcom_clk.asBits
  b.io.i_xcom_data := a.io.o_xcom_data.asBits
  a.io.i_sync := io.sync; b.io.i_sync := io.sync

  // one command port, switched between the two boards
  a.io.i_core_en := io.en && !io.which
  b.io.i_core_en := io.en && io.which
  for (x <- List(a, b)) {
    x.io.i_core_op    := io.op
    x.io.i_core_data1 := io.dt1
    x.io.i_core_data2 := io.dt2
  }

  io.aReady := a.io.o_core_ready; io.bReady := b.io.o_core_ready
  io.aDt1 := a.io.o_core_data1;   io.aDt2 := a.io.o_core_data2
  io.bDt1 := b.io.o_core_data1;   io.bDt2 := b.io.o_core_data2
  io.aVld := a.io.o_core_valid;   io.bVld := b.io.o_core_valid
  io.aFlag := a.io.o_core_flag;   io.bFlag := b.io.o_core_flag
  io.aId := a.io.o_xcom_id;       io.bId := b.io.o_xcom_id
  io.aTimeRst := a.io.o_time_rst; io.bTimeRst := b.io.o_time_rst
  io.aTimeUpd := a.io.o_time_update; io.bTimeUpd := b.io.o_time_update
  io.aTimeDat := a.io.o_time_update_data; io.bTimeDat := b.io.o_time_update_data
  io.aProcStart := a.io.o_proc_start; io.bProcStart := b.io.o_proc_start
}

/**
 * SMOKE TEST for XCOM inside RISC-Q. Verifies what has actually been established:
 *
 *  - the vendored IP (`firmware/ip/xcom/src`, 17 SystemVerilog files) elaborates and builds under
 *    Verilator, AXI-Lite slave included. No VHDL anywhere, unlike [[riscq.soc.comm.QickCom]],
 *    whose VHDL AXI wrapper forced us to wrap only its protocol core.
 *  - two instances wired as a 2-node mesh simulate together, and both respond to core commands
 *    by reaching distinct internal state.
 *
 * Two real bugs were found and fixed getting this far, both worth knowing:
 *
 *  - '''Resets must be driven explicitly.''' Deriving the active-low resets from the clock
 *    domain's `readResetWire` left XCOM un-reset: board ids came up as garbage and DIFFERED
 *    between two identically-configured instances. The testbench now drives `rstn` directly.
 *  - '''Verilator randomizes un-reset registers.''' XCOM's receive registers have no reset, so
 *    they powered up with noise that looked like received data. `--x-assign 0 --x-initial 0`
 *    makes them start at zero and the simulation deterministic.
 *
 * With those fixed, LOCAL commands work end to end: SET_ID assigns ids 1 and 2 as commanded.
 * Command drive is a ONE-CYCLE pulse on `i_core_en` - the AXI twin of that bit self-clears
 * (`xcom_axil_slv.sv:339`), so holding it high re-triggers.
 *
 * ==A bug in XCOM's RTL, found and patched here==
 * Upstream `xcom.sv` leaves the top-level `o_core_data1` / `o_core_data2` ports '''undriven'''.
 * A received word reaches `reg1_dt` inside `xcom_txrx` correctly and `o_core_valid` pulses (that
 * one IS wired through the CDC), but the data ports have no driver at all, so the core always
 * reads zero. `firmware/ip/xcom/src/xcom.sv` carries a clearly-marked LOCAL PATCH adding:
 * {{{
 *   assign o_core_data1 = s_core_data1;   // xcom_txrx's o_qp_data1 - the RECEIVED data
 *   assign o_core_data2 = s_core_data2;
 * }}}
 * Beware `s_core_data1_sync`: despite the name it is the synced module INPUT feeding the
 * transmit path, not the received data. Wiring the ports to it compiles and silently returns the
 * destination id instead of the payload. '''This should be reported upstream.'''
 *
 * ==The two synchronization mechanisms - they are NOT the same thing==
 * `xcom_qctrl.sv` has two distinct paths, and conflating them wastes a lot of time:
 *
 *  - '''QRST_SYNC''' (op 0x08) lands in EXEC_RST, which asserts ONLY `o_proc_start` - the
 *    "everyone start now" broadcast, aligned to the external reference tick (`i_sync`). It does
 *    not touch the time counter. Measured here: both boards fire on the SAME cycle, skew 0.
 *  - '''QCTRL''' (op 0x0b) lands in EXEC_CTRL, whose payload[2:0] selects the action:
 *    3'b010 = time_rst, 3'b011 = time_update, 3'b100/101 = core start/stop, 3'b110/111 =
 *    proc start/stop. This is the path that reaches the time counter.
 *
 * ==Committing a value into the time counter is TWO steps==
 * `o_time_update_data` is sourced from `reg1_dt` (xcom_txrx.sv:454), so a master must:
 * {{{
 *   1. send32Dt1  -> lands the value in the peer's reg1
 *   2. QCTRL/011  -> commits reg1 into the time counter, pulsing o_time_update
 * }}}
 * Both steps accept '''dst = 0 as a broadcast''' (`xcom_link_rx.sv:182`), which is how one master
 * aligns a whole network. Verified here point-to-point and broadcast.
 *
 * '''This is the hook to RISC-Q's `timeOffset`''' - the register behind `time = refTime +
 * timeOffset` that every `TimedQueue` compares against. Wiring `o_time_update` /
 * `o_time_update_data` to it is what makes a pulse scheduled for `startTime` land at the same
 * instant on every board.
 *
 * Run with `mill runMain riscq.soc.sim.XcomSim`.
 */
object XcomSim extends App {
  val maxWait = 20000

  val base = if (sys.env.contains("RISCQ_WAVES")) SimConfig.withWave else SimConfig
  val compiled = Xcom.rtlSources
    .foldLeft(base.addSimulatorFlag("-Wno-fatal").addSimulatorFlag("--x-assign").addSimulatorFlag("0")
      .addSimulatorFlag("--x-initial").addSimulatorFlag("0"))((cfg, src) => cfg.addRtl(src))
    .compile(new XcomMesh)

  compiled.doSim("xcom_mesh", seed = 42) { dut =>
    dut.clockDomain.forkStimulus(10)
    dut.io.en #= false; dut.io.op #= 0; dut.io.dt1 #= 0; dut.io.dt2 #= 0
    dut.io.which #= false; dut.io.sync #= false
    // XCOM's QRST_SYNC coordinates on an EXTERNAL shared reference tick (i_sync), exactly as the
    // older qick_com did with pulse_i. Both boards see the same tick here.
    fork {
      while (true) {
        dut.clockDomain.waitSampling(150); dut.io.sync #= true
        dut.clockDomain.waitSampling(150); dut.io.sync #= false
      }
    }
    dut.io.axiAddr #= 0; dut.io.axiData #= 0; dut.io.axiWrEn #= false
    dut.io.rstn #= false                       // hold XCOM in reset...
    dut.clockDomain.waitSampling(50)
    dut.io.rstn #= true                        // ...then release and let the CDC chains settle
    dut.clockDomain.waitSampling(100)
    assert(dut.io.aId.toInt == 0 && dut.io.bId.toInt == 0,
      s"board ids did not reset to 0 (A=${dut.io.aId.toInt} B=${dut.io.bId.toInt})")

    /** AXI-Lite write to BOTH boards (register index * 4 = byte offset). */
    def axiWrite(regIndex: Int, value: BigInt): Unit = {
      dut.io.axiAddr #= regIndex * 4; dut.io.axiData #= value
      dut.clockDomain.waitSampling(); dut.io.axiWrEn #= true
      var g = 0
      while (!dut.io.axiReady.toBoolean && g < 200) { dut.clockDomain.waitSampling(); g += 1 }
      assert(g < 200, s"AXI write to reg $regIndex never accepted")
      dut.clockDomain.waitSampling(); dut.io.axiWrEn #= false
      dut.clockDomain.waitSampling(20)
    }

    // The link bit-rate generator is driven by xcom_cfg (register 1) -> i_cfg_tick. It resets to 0,
    // which stops the serializer ticking - the same knob as qick_com's tick_cfg.
    axiWrite(1, 8)
    println("[XcomSim] link tick configured via AXI (xcom_cfg = 8)")

    /** Issue one command. The trigger is a ONE-SHOT: `xcom_axil_slv.sv:339` self-clears the AXI
     *  control bit after a single cycle, and `i_core_en` is its core-port twin, so the enable must
     *  be a single-cycle pulse with op/data stable around it. Holding it high re-triggers. */
    def cmd(onB: Boolean, op: Int, d1: BigInt, d2: BigInt): Unit = {
      dut.io.which #= onB; dut.io.op #= op; dut.io.dt1 #= d1; dut.io.dt2 #= d2
      dut.clockDomain.waitSampling(2)       // operands settled before the pulse
      dut.io.en #= true
      dut.clockDomain.waitSampling()        // exactly one cycle
      dut.io.en #= false
      dut.clockDomain.waitSampling(40)      // let the command drain
    }

    // ── assign network ids: A = 1, B = 2 ──
    cmd(false, Xcom.Op.setId, 1, 0)
    cmd(true,  Xcom.Op.setId, 2, 0)
    val idA = dut.io.aId.toInt; val idB = dut.io.bId.toInt
    println(f"[XcomSim] board ids assigned: A=$idA%d  B=$idB%d")
    assert(idA != idB, s"the two boards ended up with the same id ($idA) — they are not independent")

    assert(idA == 1 && idB == 2, s"SET_ID did not take: A=$idA B=$idB (expected 1, 2)")

    // --- A sends a 32-bit word to B (data1 = destination id, data2 = payload) ---
    // NB: poll the RECEIVE REGISTER, not o_core_valid. That valid is a level left high by the
    // board's previous command, so waiting on it exits immediately and samples a half-shifted word.
    val payload = BigInt("c0ffee01", 16)
    dut.io.which #= false; dut.io.op #= Xcom.Op.send32Dt1; dut.io.dt1 #= 2; dut.io.dt2 #= payload
    dut.clockDomain.waitSampling(2); dut.io.en #= true
    dut.clockDomain.waitSampling(); dut.io.en #= false

    var txEdges = 0; var lastClk = dut.io.aTxClk.toBoolean
    var cycles = 0
    while (dut.io.bDt1.toBigInt != payload && cycles < 20000) {
      dut.clockDomain.waitSampling(); cycles += 1
      val c = dut.io.aTxClk.toBoolean
      if (c != lastClk) { txEdges += 1; lastClk = c }
    }
    assert(dut.io.bDt1.toBigInt == payload,
      f"32-bit send: B holds 0x${dut.io.bDt1.toBigInt}%08x after $cycles cycles, expected 0x$payload%08x")
    println(f"[XcomSim] A -> B 32-bit : 0x$payload%08x received intact in $cycles core clocks ($txEdges strobe edges)")

    dut.clockDomain.waitSampling(200)

    // --- the headline: a broadcast sync drives time control on BOTH boards together ---
    var aAt = -1; var bAt = -1; var t = 0
    dut.io.which #= false; dut.io.op #= Xcom.Op.qrstSync; dut.io.dt1 #= 0; dut.io.dt2 #= 0
    dut.clockDomain.waitSampling(2); dut.io.en #= true
    dut.clockDomain.waitSampling(); dut.io.en #= false
    while (t < 20000 && (aAt < 0 || bAt < 0)) {
      dut.clockDomain.waitSampling(); t += 1
      // QRST_SYNC lands in the qctrl FSM's EXEC_RST state, which asserts o_proc_start - NOT
      // o_time_rst/o_time_update. Those two come from a separate XCOM_QCTRL command whose data
      // field selects the action (3'b010 = time_rst, 3'b011 = time_update). See xcom_qctrl.sv.
      if (aAt < 0 && dut.io.aProcStart.toBoolean) aAt = t
      if (bAt < 0 && dut.io.bProcStart.toBoolean) bAt = t
    }
    assert(aAt >= 0 && bAt >= 0, s"QRST_SYNC: proc_start not asserted on both boards (A=$aAt B=$bAt)")
    println(f"[XcomSim] QRST_SYNC    : A proc_start at cycle $aAt%d, B at $bAt%d  -> SKEW ${bAt - aAt}%d")
    assert(bAt == aAt, s"QRST_SYNC: boards fired ${bAt - aAt} cycles apart, expected the same cycle")

    dut.clockDomain.waitSampling(300)

    // --- QCTRL: commit a value into the peer's TIME COUNTER (the timeOffset hook) ---
    // Two steps, because `o_time_update_data` is sourced from reg1_dt (xcom_txrx.sv:454):
    //   1. a normal 32-bit send lands the value in the peer's reg1;
    //   2. XCOM_QCTRL carries an action code in its payload[2:0] - 3'b011 = time_update,
    //      3'b010 = time_rst (see the EXEC_CTRL case in xcom_qctrl.sv) - which commits it.
    val timeVal = BigInt("0000abcd", 16)

    // step 1 - land the value
    dut.io.which #= false; dut.io.op #= Xcom.Op.send32Dt1; dut.io.dt1 #= 2; dut.io.dt2 #= timeVal
    dut.clockDomain.waitSampling(2); dut.io.en #= true
    dut.clockDomain.waitSampling(); dut.io.en #= false
    var c1 = 0
    while (dut.io.bDt1.toBigInt != timeVal && c1 < 20000) { dut.clockDomain.waitSampling(); c1 += 1 }
    assert(dut.io.bDt1.toBigInt == timeVal,
      f"QCTRL step 1: value never landed in B's reg1 (holds 0x${dut.io.bDt1.toBigInt}%08x)")

    dut.clockDomain.waitSampling(100)

    // step 2 - commit it into the time counter
    var upd = -1; var updData = BigInt(-1); var c2 = 0
    dut.io.which #= false; dut.io.op #= Xcom.Op.qctrl; dut.io.dt1 #= 2; dut.io.dt2 #= 3 // 3'b011
    dut.clockDomain.waitSampling(2); dut.io.en #= true
    dut.clockDomain.waitSampling(); dut.io.en #= false
    while (upd < 0 && c2 < 20000) {
      dut.clockDomain.waitSampling(); c2 += 1
      if (dut.io.bTimeUpd.toBoolean) { upd = c2; updData = dut.io.bTimeDat.toBigInt }
    }
    assert(upd >= 0, s"QCTRL: o_time_update never asserted on board B within 20000 cycles")
    assert(updData == timeVal,
      f"QCTRL: time_update fired with 0x$updData%08x, expected 0x$timeVal%08x")
    println(f"[XcomSim] QCTRL/011    : B time_update fired at cycle $upd%d with 0x$updData%08x " +
            f"-> this is the timeOffset hook")

    dut.clockDomain.waitSampling(300)

    // --- the realistic form: BROADCAST (dst = 0) so a master aligns every board at once ---
    // xcom_link_rx.sv:182 - `s_broadcast = (header[3:0] == 4'd0)`, accepted by every board.
    val bcastVal = BigInt("00005a5a", 16)
    dut.io.which #= false; dut.io.op #= Xcom.Op.send32Dt1; dut.io.dt1 #= 0; dut.io.dt2 #= bcastVal
    dut.clockDomain.waitSampling(2); dut.io.en #= true
    dut.clockDomain.waitSampling(); dut.io.en #= false
    var c3 = 0
    while (dut.io.bDt1.toBigInt != bcastVal && c3 < 20000) { dut.clockDomain.waitSampling(); c3 += 1 }
    assert(dut.io.bDt1.toBigInt == bcastVal,
      f"broadcast send: B's reg1 holds 0x${dut.io.bDt1.toBigInt}%08x, expected 0x$bcastVal%08x")

    dut.clockDomain.waitSampling(100)
    var bUpd = -1; var bDat = BigInt(-1); var c4 = 0
    dut.io.which #= false; dut.io.op #= Xcom.Op.qctrl; dut.io.dt1 #= 0; dut.io.dt2 #= 3
    dut.clockDomain.waitSampling(2); dut.io.en #= true
    dut.clockDomain.waitSampling(); dut.io.en #= false
    while (bUpd < 0 && c4 < 20000) {
      dut.clockDomain.waitSampling(); c4 += 1
      if (dut.io.bTimeUpd.toBoolean) { bUpd = c4; bDat = dut.io.bTimeDat.toBigInt }
    }
    assert(bUpd >= 0 && bDat == bcastVal,
      f"broadcast QCTRL: fired=${bUpd >= 0} with 0x$bDat%08x, expected 0x$bcastVal%08x")
    println(f"[XcomSim] QCTRL bcast  : dst=0 reaches every board - B committed 0x$bDat%08x at cycle $bUpd%d")


    println("[XcomSim] PASS - ids, transfer, QRST_SYNC aligned start, QCTRL time commit (direct + broadcast).")
  }
}
