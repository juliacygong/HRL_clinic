package riscq.soc.fabric

import spinal.core._
import spinal.lib._
import riscq.riscv.misc.{DataMemBus, DataMemBusParam, DataMemCmd}

/**
 * Data-bus **posted-store adapter** on the core's simplified [[DataMemBus]] — spliced between the
 * [[riscq.riscv.execute.LsuPlugin]] and the `DataMemBusToTilelink` bridge inside [[RiscqFiber]]. It
 * leaves the verified LSU untouched — the core keeps its plain blocking, single-outstanding contract
 * (send `cmd`, wait for `rsp`) — but satisfies a **store** locally so it retires fast, making writes
 * effectively non-blocking:
 *
 *  - A read (`cmd.write = False`) is forwarded transparently and returns the slave's real `rsp`.
 *  - A write is dropped into a small store buffer and **acked locally in one cycle**, so the CPU store
 *    commits next cycle while the write drains downstream in the background.
 *
 * Program order is preserved by the buffer: a read is held until the buffer is empty, so it can never
 * overtake a not-yet-written store (store→load RAW stays correct — the read is only forwarded after the
 * prior store's ack, i.e. after the slave committed the write). One transaction is kept outstanding
 * downstream, so a returning `rsp` belongs unambiguously to the last issued `cmd` (a reg remembers
 * read-vs-write).
 *
 * Because the upstream master is **blocking single-outstanding** (the LSU issues one access and halts
 * until its `rsp`), the local write-ack and a forwarded read response are never live in the same cycle
 * — the master is idle of writes whenever a read is in flight — so `up.rsp` stays a backpressure-free
 * [[Flow]] (no arbiter needed). A returning store ack from downstream is swallowed.
 *
 * Caveat: posted stores relax store→store ordering across *different* downstream slaves (the early ack
 * lets the CPU proceed before the write lands). Same-slave order and store→load RAW are preserved.
 *
 * '''Direct port''' (`directSize > 0`): stores to `[directBase, directBase + directSize)` skip the store
 * buffer and the bus entirely. They are acked locally like any store and leave on `io.direct`, a registered
 * Flow, one per cycle and in program order (the RF window: the downstream path is itself posted, so nothing
 * comes back). The store buffer drains one write per downstream round trip, which made the RF writes the
 * pulse-issue bottleneck; the direct port takes them at the LSU's full store rate. Direct stores may
 * overtake older buffered stores to other slaves, the same relaxation as above; the window is write-only,
 * so there is no read to order against.
 *
 * Standalone `Component` so it can be unit-tested in isolation (drive `io.up`, model `io.down` with a
 * golden memory — see `PostedStoreShimSim`).
 *
 * @param bufDepth   store-buffer depth — the number of posted stores in flight before the CPU
 *                   back-pressures.
 * '''RAM port''' (`ramSize > 0`): loads and stores to the CPU's own data RAM `[ramBase, ramBase + ramSize)` go
 * to `io.ram` (the RAM's read/write port) instead of the bus: the command is registered once, a store is acked
 * like any posted store, a load answers `ramLatency` cycles after the registered command. A RAM load does not
 * wait for the store buffer: RAM stores never enter it (they go straight to the port, in order), so the
 * buffer only ever holds stores to other slaves, which a RAM load cannot depend on.
 *
 * @param directBase / directSize  the direct-port address window (`directSize = 0`: no direct port).
 * @param ramBase / ramSize / ramLatency / ramAddrWidth  the data-RAM window, its read latency and word-address
 *                 width (`ramSize = 0`: RAM accesses go over the bus as before).
 */
case class PostedStoreShim(p: DataMemBusParam, bufDepth: Int = 4, directBase: BigInt = 0, directSize: BigInt = 0,
                           ramBase: BigInt = 0, ramSize: BigInt = 0, ramLatency: Int = 0, ramAddrWidth: Int = 0)
    extends Component {
  val withDirect = directSize > 0
  val withRam    = ramSize > 0
  require(!withRam || (ramLatency >= 1 && ramAddrWidth > 0 && (BigInt(1) << (ramAddrWidth + 2)) == ramSize &&
    ramBase % ramSize == 0), "RAM window: power-of-two size, base aligned to it, word address width and latency given")
  val io = new Bundle {
    val up     = slave(DataMemBus(p))
    val down   = master(DataMemBus(p))
    val direct = withDirect generate master(Flow(DataMemCmd(p)))   // stores to the direct window
    val ram    = withRam generate master(MemReadWritePort(Bits(p.dataWidth bits), ramAddrWidth, maskWidth = p.dataBytes))
  }

  val isWrite = io.up.cmd.write
  // a store to the direct window: never buffered, never sent downstream
  // Window decode on the address's upper bits only: base and size are multiples of a power-of-two granule, so
  // "in window" is "the granule number (address >> g) lies in a small constant range": a few LUTs on the top
  // bits instead of two full-width compares on the LSU address (which arrives late, out of the address adder).
  def inDirect(a: UInt): Bool = if (withDirect) {
    val g  = (directBase | directSize).lowestSetBit
    val hi = a >> g
    hi >= (directBase >> g) && hi < ((directBase + directSize) >> g)
  } else False
  // an access (load or store) to the CPU's data RAM: straight to the RAM port
  val isRam = if (withRam) (io.up.cmd.address >> log2Up(ramSize)) === (ramBase >> log2Up(ramSize)) else False

  // ── store buffer: the full cmd of each accepted write, drained downstream in order ──
  val sbuf = StreamFifo(DataMemCmd(p), bufDepth, forFMax = true)

  // ── one transaction outstanding downstream; `inflightIsRead` remembers its kind so the returning
  //    `rsp` is routed (read → forward to up.rsp, write → swallow). One `down.cmd` is issued at a time,
  //    so its single `down.rsp` is unambiguous. ──
  val busy           = RegInit(False)
  val inflightIsRead = RegInit(False)
  val canIssue       = !busy

  // ── store stage: every (non-RAM) store is registered here first, and the direct-or-buffer decision is made
  //    from this registered address. Deciding straight off the CPU's address put the window decode between the
  //    address adder and the buffer's write enable (and the CPU's stall logic), the failing timing path; from
  //    a register it is short. The stage empties every cycle (into the direct port, or the buffer when it has
  //    room), so stores still go through at one per cycle and are still acked the cycle after they issue. ──
  val stage = Reg(Flow(DataMemCmd(p)))
  stage.valid init False
  val stDirect   = inDirect(stage.payload.address)
  val stDrain    = stage.valid && (stDirect || sbuf.io.push.ready)
  val stageFree  = !stage.valid || stDrain
  when(stDrain) { stage.valid := False }
  when(io.up.cmd.fire && isWrite && !isRam) { stage.valid := True; stage.payload := io.up.cmd.payload }

  // reads keep program order: they wait until no store is staged, buffered or in flight. The buffer is counted
  // explicitly (push +1, pop -1): its pop side shows a fresh entry a cycle after the push, and a read must not
  // slip through that gap.
  val drainStore = sbuf.io.pop.valid                              // a buffered store is waiting to go out
  val buffered   = Reg(UInt(log2Up(bufDepth + 1) + 1 bits)) init 0
  buffered := buffered + U(sbuf.io.push.fire) - U(sbuf.io.pop.fire)
  val fwdRead    = !drainStore && buffered === 0 && !stage.valid && io.up.cmd.valid && !isWrite && !isRam

  io.down.cmd.valid   := canIssue && (drainStore || fwdRead)
  io.down.cmd.payload := drainStore ? sbuf.io.pop.payload | io.up.cmd.payload
  sbuf.io.pop.ready   := canIssue && drainStore && io.down.cmd.ready

  when(io.down.cmd.fire) { busy := True; inflightIsRead := !drainStore }
  when(io.down.rsp.valid) { busy := False }

  // ── push an accepted write into the buffer; ack it locally one cycle later (mirrors the slave's
  //    single-cycle response latency). The push back-pressures the CPU only when the buffer is full. ──
  sbuf.io.push.valid   := stage.valid && !stDirect
  sbuf.io.push.payload := stage.payload

  // up.cmd.ready: a store fires when the stage is free (or emptying this cycle); a read when forwarded
  // downstream. Both depend only on registered state, not on the incoming address.
  io.up.cmd.ready := isRam ? True | (isWrite ? stageFree | (canIssue && !drainStore && buffered === 0 && !stage.valid && io.down.cmd.ready))

  // direct port: straight from the store stage (a register)
  if (withDirect) {
    io.direct.valid   := stage.valid && stDirect
    io.direct.payload := stage.payload
  }

  // up.rsp: the synthetic write-ack (registered one cycle after accept) OR'd with the forwarded read
  // response — mutually exclusive by the blocking-master invariant above, so a plain OR is safe.
  val writeAck = RegNext(io.up.cmd.fire && isWrite) init (False)
  val readRsp  = io.down.rsp.valid && inflightIsRead

  // RAM port: one register stage (keeps the address decode and the RAM input pins apart), then the RAM's
  // fixed read latency for the response
  val ramRsp = if (withRam) {
    val cmd = Reg(Flow(DataMemCmd(p)))
    cmd.valid init False
    cmd.valid   := io.up.cmd.fire && isRam
    cmd.payload := io.up.cmd.payload
    io.ram.enable  := cmd.valid
    io.ram.write   := cmd.payload.write
    io.ram.address := (cmd.payload.address >> log2Up(p.dataBytes)).resize(ramAddrWidth)
    io.ram.wdata   := cmd.payload.data
    io.ram.mask    := cmd.payload.mask
    Delay(cmd.valid && !cmd.payload.write, ramLatency, init = False)
  } else False

  io.up.rsp.valid := writeAck || readRsp || ramRsp
  // meaningful only for a read; a write ignores rsp.data
  io.up.rsp.data  := (if (withRam) (ramRsp ? io.ram.rdata | io.down.rsp.data) else io.down.rsp.data)
}
