     NOP 
     REG_WR s12 imm #0 
     WPORT_WR p4 wmem [&2] @0 
     TIME #4 inc_ref 
     REG_WR r0 imm #0 
reps:
     TRIG p8 set @0 
     TRIG p11 set @0 
     TRIG p8 clr @10 
     TRIG p11 clr @10 
     REG_WR r1 imm #0 
l:
     WPORT_WR p3 wmem [&0] @0 
     REG_WR r_wave wmem [&0] 
     REG_WR w3 op -op(w3 + #-500) 
     WMEM_WR &0 
     TIME #2 inc_ref 
     REG_WR s15 label l 
     TEST -op(r1 - #39) 
     JUMP [s15] -if(NZ) -wr(r1 op) -op(r1 + #1) 
     REG_WR s15 label SKIP 
     WAIT [s15] @643 time 
     TIME #643 inc_ref 
     REG_WR s12 op -op(s12 + #1) 
     REG_WR s15 label reps 
     TEST -op(r0 - #0) 
     JUMP [s15] -if(NZ) -wr(r0 op) -op(r0 + #1) 
     REG_WR s15 label NEXT 
     JUMP [s15] 
