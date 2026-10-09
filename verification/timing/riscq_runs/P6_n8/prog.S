# P6_n8: capacity: 8 pending pulses
# generated from QICK T9a (acceptance stall: 300 pulses due 10 us + k*0.05 us (fills 256-entry dispatcher FIFO, no SG backpressure)) by gen_riscq_programs.py
  .section .text.init, "ax"
  .globl _start
_start:
  li   t0, 0xbff8             # TimeMemMap batch time
  lw   a0, 0(t0)              
  li   t1, 599                
  add  s0, a0, t1             # s0 = base = now + 599 batches (QICK ref 1.0 us)
  # pulse 0: QICK t=10.0 us ch=0 -> startTime base+5990, dur 12, amp 33
  li   t0, 0x14100            
  li   t2, 5990               
  add  t2, s0, t2             
  sw   t2, 0(t0)              # startTime
  li   t0, 0x10004            
  li   t2, 0x7080000          
  sw   t2, 0(t0)              # freq
  li   t0, 0x10010            
  li   t2, 0x0                
  sw   t2, 0(t0)              # phase
  li   t0, 0x10014            
  li   t2, 0x210000           
  sw   t2, 0(t0)              # amp (fingerprint)
  li   t0, 0x10018            
  li   t2, 0xa0000            
  sw   t2, 0(t0)              # env base
  li   t0, 0x1001c            
  li   t2, 0xc0000            
  sw   t2, 0(t0)              # dur
  li   t0, 0x10000            
  li   t2, 0x0                
  sw   t2, 0(t0)              # fire table[0]
  # pulse 1: QICK t=10.05 us ch=0 -> startTime base+6020, dur 12, amp 66
  li   t0, 0x14100            
  li   t2, 6020               
  add  t2, s0, t2             
  sw   t2, 0(t0)              # startTime
  li   t0, 0x10004            
  li   t2, 0x7080000          
  sw   t2, 0(t0)              # freq
  li   t0, 0x10020            
  li   t2, 0x0                
  sw   t2, 0(t0)              # phase
  li   t0, 0x10024            
  li   t2, 0x420000           
  sw   t2, 0(t0)              # amp (fingerprint)
  li   t0, 0x10028            
  li   t2, 0xa0000            
  sw   t2, 0(t0)              # env base
  li   t0, 0x1002c            
  li   t2, 0xc0000            
  sw   t2, 0(t0)              # dur
  li   t0, 0x10000            
  li   t2, 0x1                
  sw   t2, 0(t0)              # fire table[1]
  # pulse 2: QICK t=10.1 us ch=0 -> startTime base+6050, dur 12, amp 98
  li   t0, 0x14100            
  li   t2, 6050               
  add  t2, s0, t2             
  sw   t2, 0(t0)              # startTime
  li   t0, 0x10004            
  li   t2, 0x7080000          
  sw   t2, 0(t0)              # freq
  li   t0, 0x10030            
  li   t2, 0x0                
  sw   t2, 0(t0)              # phase
  li   t0, 0x10034            
  li   t2, 0x620000           
  sw   t2, 0(t0)              # amp (fingerprint)
  li   t0, 0x10038            
  li   t2, 0xa0000            
  sw   t2, 0(t0)              # env base
  li   t0, 0x1003c            
  li   t2, 0xc0000            
  sw   t2, 0(t0)              # dur
  li   t0, 0x10000            
  li   t2, 0x2                
  sw   t2, 0(t0)              # fire table[2]
  # pulse 3: QICK t=10.15 us ch=0 -> startTime base+6080, dur 12, amp 131
  li   t0, 0x14100            
  li   t2, 6080               
  add  t2, s0, t2             
  sw   t2, 0(t0)              # startTime
  li   t0, 0x10004            
  li   t2, 0x7080000          
  sw   t2, 0(t0)              # freq
  li   t0, 0x10040            
  li   t2, 0x0                
  sw   t2, 0(t0)              # phase
  li   t0, 0x10044            
  li   t2, 0x830000           
  sw   t2, 0(t0)              # amp (fingerprint)
  li   t0, 0x10048            
  li   t2, 0xa0000            
  sw   t2, 0(t0)              # env base
  li   t0, 0x1004c            
  li   t2, 0xc0000            
  sw   t2, 0(t0)              # dur
  li   t0, 0x10000            
  li   t2, 0x3                
  sw   t2, 0(t0)              # fire table[3]
  # pulse 4: QICK t=10.2 us ch=0 -> startTime base+6110, dur 12, amp 164
  li   t0, 0x14100            
  li   t2, 6110               
  add  t2, s0, t2             
  sw   t2, 0(t0)              # startTime
  li   t0, 0x10004            
  li   t2, 0x7080000          
  sw   t2, 0(t0)              # freq
  li   t0, 0x10050            
  li   t2, 0x0                
  sw   t2, 0(t0)              # phase
  li   t0, 0x10054            
  li   t2, 0xa40000           
  sw   t2, 0(t0)              # amp (fingerprint)
  li   t0, 0x10058            
  li   t2, 0xa0000            
  sw   t2, 0(t0)              # env base
  li   t0, 0x1005c            
  li   t2, 0xc0000            
  sw   t2, 0(t0)              # dur
  li   t0, 0x10000            
  li   t2, 0x4                
  sw   t2, 0(t0)              # fire table[4]
  # pulse 5: QICK t=10.25 us ch=0 -> startTime base+6140, dur 12, amp 197
  li   t0, 0x14100            
  li   t2, 6140               
  add  t2, s0, t2             
  sw   t2, 0(t0)              # startTime
  li   t0, 0x10004            
  li   t2, 0x7080000          
  sw   t2, 0(t0)              # freq
  li   t0, 0x10060            
  li   t2, 0x0                
  sw   t2, 0(t0)              # phase
  li   t0, 0x10064            
  li   t2, 0xc50000           
  sw   t2, 0(t0)              # amp (fingerprint)
  li   t0, 0x10068            
  li   t2, 0xa0000            
  sw   t2, 0(t0)              # env base
  li   t0, 0x1006c            
  li   t2, 0xc0000            
  sw   t2, 0(t0)              # dur
  li   t0, 0x10000            
  li   t2, 0x5                
  sw   t2, 0(t0)              # fire table[5]
  # pulse 6: QICK t=10.3 us ch=0 -> startTime base+6170, dur 12, amp 229
  li   t0, 0x14100            
  li   t2, 6170               
  add  t2, s0, t2             
  sw   t2, 0(t0)              # startTime
  li   t0, 0x10004            
  li   t2, 0x7080000          
  sw   t2, 0(t0)              # freq
  li   t0, 0x10070            
  li   t2, 0x0                
  sw   t2, 0(t0)              # phase
  li   t0, 0x10074            
  li   t2, 0xe50000           
  sw   t2, 0(t0)              # amp (fingerprint)
  li   t0, 0x10078            
  li   t2, 0xa0000            
  sw   t2, 0(t0)              # env base
  li   t0, 0x1007c            
  li   t2, 0xc0000            
  sw   t2, 0(t0)              # dur
  li   t0, 0x10000            
  li   t2, 0x6                
  sw   t2, 0(t0)              # fire table[6]
  # pulse 7: QICK t=10.35 us ch=0 -> startTime base+6200, dur 12, amp 262
  li   t0, 0x14100            
  li   t2, 6200               
  add  t2, s0, t2             
  sw   t2, 0(t0)              # startTime
  li   t0, 0x10004            
  li   t2, 0x7080000          
  sw   t2, 0(t0)              # freq
  li   t0, 0x10080            
  li   t2, 0x0                
  sw   t2, 0(t0)              # phase
  li   t0, 0x10084            
  li   t2, 0x1060000          
  sw   t2, 0(t0)              # amp (fingerprint)
  li   t0, 0x10088            
  li   t2, 0xa0000            
  sw   t2, 0(t0)              # env base
  li   t0, 0x1008c            
  li   t2, 0xc0000            
  sw   t2, 0(t0)              # dur
  li   t0, 0x10000            
  li   t2, 0x7                
  sw   t2, 0(t0)              # fire table[7]
1:
  j    1b                    # park
