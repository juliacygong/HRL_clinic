     NOP 
     REG_WR s12 imm #0 
     WPORT_WR p4 wmem [&3] @0 
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
     WPORT_WR p3 wmem [&1] @0 
     WPORT_WR p3 wmem [&2] @0 
     REG_WR s15 label virt_z 
     CALL [s15] 
     TIME #11 inc_ref 
     REG_WR s15 label l 
     TEST -op(r1 - #39) 
     JUMP [s15] -if(NZ) -wr(r1 op) -op(r1 + #1) 
     REG_WR s15 label SKIP 
     WAIT [s15] @678 time 
     TIME #678 inc_ref 
     REG_WR s12 op -op(s12 + #1) 
     REG_WR s15 label reps 
     TEST -op(r0 - #0) 
     JUMP [s15] -if(NZ) -wr(r0 op) -op(r0 + #1) 
     REG_WR s15 label NEXT 
     JUMP [s15] 
virt_z:
     REG_WR r_wave wmem [&0] 
     REG_WR r2 imm #1073741824 
     REG_WR w1 op -op(w1 + r2) 
     WMEM_WR &0 
     REG_WR r_wave wmem [&1] 
     REG_WR r2 imm #1073741824 
     REG_WR w1 op -op(w1 + r2) 
     WMEM_WR &1 
     REG_WR r_wave wmem [&2] 
     REG_WR r2 imm #1073741824 
     REG_WR w1 op -op(w1 + r2) 
     WMEM_WR &2 
RET

