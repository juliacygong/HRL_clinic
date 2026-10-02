# P8_T2: rerun after abort: pulses scheduled far ahead, reset re-asserted before they play
# generated from QICK T2 (two pulses, idle gap 0.5 us) by gen_riscq_programs.py
  .section .text.init, "ax"
  .globl _start
_start:
  li   t0, 0xbff8             # TimeMemMap batch time
  lw   a0, 0(t0)              
  li   t1, 2396               
  add  s0, a0, t1             # s0 = base = now + 2396 batches (QICK ref 1.0 us)
  # pulse 0: QICK t=0.5 us ch=0 -> startTime base+300, dur 60, amp 3277
  li   t0, 0x14100            
  li   t2, 300                
  add  t2, s0, t2             
  sw   t2, 0(t0)              # startTime
  li   t0, 0x10004            
  li   t2, 0x7080000          
  sw   t2, 0(t0)              # freq
  li   t0, 0x10010            
  li   t2, 0x0                
  sw   t2, 0(t0)              # phase
  li   t0, 0x10014            
  li   t2, 0xccd0000          
  sw   t2, 0(t0)              # amp (fingerprint)
  li   t0, 0x10018            
  li   t2, 0xa0000            
  sw   t2, 0(t0)              # env base
  li   t0, 0x1001c            
  li   t2, 0x3c0000           
  sw   t2, 0(t0)              # dur
  li   t0, 0x10000            
  li   t2, 0x0                
  sw   t2, 0(t0)              # fire table[0]
  # pulse 1: QICK t=1.0 us ch=0 -> startTime base+599, dur 60, amp 6553
  li   t0, 0x14100            
  li   t2, 599                
  add  t2, s0, t2             
  sw   t2, 0(t0)              # startTime
  li   t0, 0x10004            
  li   t2, 0x7080000          
  sw   t2, 0(t0)              # freq
  li   t0, 0x10020            
  li   t2, 0x0                
  sw   t2, 0(t0)              # phase
  li   t0, 0x10024            
  li   t2, 0x19990000         
  sw   t2, 0(t0)              # amp (fingerprint)
  li   t0, 0x10028            
  li   t2, 0xa0000            
  sw   t2, 0(t0)              # env base
  li   t0, 0x1002c            
  li   t2, 0x3c0000           
  sw   t2, 0(t0)              # dur
  li   t0, 0x10000            
  li   t2, 0x1                
  sw   t2, 0(t0)              # fire table[1]
1:
  j    1b                    # park
