# pulse_sched.S — M4 CPU-in-the-loop control program (docs/soc/PulseTableSoc.md §5).
#
# The RISC-V control core schedules one gate pulse by issuing the exact register writes the M3
# test-master harness performed (PulseTableSocSim Part 2), but now over the CPU's own dBus through the
# posted RF link (docs/soc/ARCH.md): the stores funnel through the RfLinkBridge onto one ordered
# Flow(RfCmd), demuxed to the gate buffer. startTime is per-buffer, so it lives in the gate window:
#     time     = *0xbff8                ; TimeMemMap current batch time
#     *0x14100 = time + LEAD            ; gate buffer startTime (RF window 0x10000 + 0x4100)
#     program gate-drive table[0] @ 0x10000 (freq/phase/amp/env/dur), then fire outId 0
#     spin forever                      ; no further dBus traffic
# startTime precedes the table writes and the fire on the same ordered posted path, so the fire enqueues
# table[0] with the just-written startTime (docs/soc/ARCH.md §5.1).
#
# Every RF field lives in bus bits [16,32) (posted RfCmd field bitOffset = 16) ⇒ the stored word is value<<16.
# Built for the riscq core (RV32I, reset vector 0x80000000). Rebuild with:
#   /config/build/riscv-install/bin/clang -target riscv32 -march=rv32i -mabi=ilp32 -mno-relax \
#     -nostdlib -static -Wl,-Ttext=0x80000000 -Wl,-e,_start \
#     src/riscq/soc/sim/sw/pulse_sched.S -o src/riscq/soc/sim/sw/pulse_sched.elf

  .section .text.init, "ax"
  .globl _start
_start:
    .section .text.init, "ax"
  .globl _start
_start:
  li   t0, 0xbff8
  lw   a0, 0(t0)
  addi a0, a0, 1024

  # CPU 0x34100 -> RfCmd 0x24100
  #                -> demod-local startTime 0x4100
  li   t0, 0x34100
  sw   a0, 0(t0)

  # CPU 0x30000 -> RfCmd 0x20000 = demod/readout channel
  li   t1, 0x30000

  # QICK readout golden freq = 0xf5955556.
  # RISC-Q has a 16-bit freq field, so use its upper 16 bits for now.
  li   t2, 0xf5950000
  sw   t2, 0x04(t1)

  # phase = 0
  sw   x0, 0x10(t1)

  # RISC-Q-specific demod carrier parameters.
  # These create the carrier but are NOT direct QICK readout fields.
  li   t2, 0x23280000
  sw   t2, 0x14(t1)       # amp

  li   t2, 0x000a0000
  sw   t2, 0x18(t1)       # envelope address

  # provisional duration = 3, matching QICK nsamp numerically.
  # We have NOT yet proven nsamp and RISC-Q dur have identical time units.
  li   t2, 0x00030000
  sw   t2, 0x1c(t1)

  sw   x0, 0x00(t1)       # fire demod pulse

1:
  j    1b