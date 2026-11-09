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
     WPORT_WR p3 wmem [&0] @0 
     WPORT_WR p3 wmem [&1] @2 
     WPORT_WR p3 wmem [&0] @4 
     WPORT_WR p3 wmem [&1] @6 
     WPORT_WR p3 wmem [&0] @9 
     WPORT_WR p3 wmem [&1] @11 
     WPORT_WR p3 wmem [&0] @13 
     WPORT_WR p3 wmem [&1] @15 
     WPORT_WR p3 wmem [&0] @17 
     WPORT_WR p3 wmem [&1] @19 
     WPORT_WR p3 wmem [&0] @22 
     WPORT_WR p3 wmem [&1] @24 
     WPORT_WR p3 wmem [&0] @26 
     WPORT_WR p3 wmem [&1] @28 
     WPORT_WR p3 wmem [&0] @30 
     WPORT_WR p3 wmem [&1] @32 
     WPORT_WR p3 wmem [&0] @34 
     WPORT_WR p3 wmem [&1] @37 
     WPORT_WR p3 wmem [&0] @39 
     WPORT_WR p3 wmem [&1] @41 
     WPORT_WR p3 wmem [&0] @43 
     WPORT_WR p3 wmem [&1] @45 
     WPORT_WR p3 wmem [&0] @47 
     WPORT_WR p3 wmem [&1] @50 
     WPORT_WR p3 wmem [&0] @52 
     WPORT_WR p3 wmem [&1] @54 
     WPORT_WR p3 wmem [&0] @56 
     WPORT_WR p3 wmem [&1] @58 
     WPORT_WR p3 wmem [&0] @60 
     WPORT_WR p3 wmem [&1] @62 
     WPORT_WR p3 wmem [&0] @65 
     WPORT_WR p3 wmem [&1] @67 
     WPORT_WR p3 wmem [&0] @69 
     WPORT_WR p3 wmem [&1] @71 
     WPORT_WR p3 wmem [&0] @73 
     WPORT_WR p3 wmem [&1] @75 
     WPORT_WR p3 wmem [&0] @78 
     WPORT_WR p3 wmem [&1] @80 
     WPORT_WR p3 wmem [&0] @82 
     WPORT_WR p3 wmem [&1] @84 
     REG_WR s15 label SKIP 
     WAIT [s15] @645 time 
     TIME #645 inc_ref 
     REG_WR s12 op -op(s12 + #1) 
     REG_WR s15 label reps 
     TEST -op(r0 - #0) 
     JUMP [s15] -if(NZ) -wr(r0 op) -op(r0 + #1) 
     REG_WR s15 label NEXT 
     JUMP [s15] 
