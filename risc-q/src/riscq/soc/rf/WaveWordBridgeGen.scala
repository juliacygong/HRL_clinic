package riscq.soc.rf

import spinal.core._

// Generates WaveWordBridge Verilog for formal verification.
//   mill runMain riscq.soc.rf.WaveWordBridgeGen [leadTime]
// leadTime defaults to 32, the value QickGenParams uses on branch claude-newdesign
// (gen_v6 accept -> first m_axis_tvalid latency).
object WaveWordBridgeGen extends App {
  val lead = if (args.nonEmpty) args(0).toInt else 32
  SpinalConfig(targetDirectory = s"gen/wwb_lead$lead")
    .generateVerilog(WaveWordBridge(WaveWordBridgeParams(leadTime = lead)))
}
