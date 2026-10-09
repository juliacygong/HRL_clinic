//----------------------------------------------------
// Controller-level timing event monitors (always on), SG0 and SG1
//----------------------------------------------------
// Included inside QICKEmu_harness. Logs one CSV row per event for the tProc
// wave path to SG0 (see verification/timing/TIMING_PLAN.md):
//   E0i issue -> E0 schedule -> E1 on timeline -> E2 tProc release
//   -> E3 SGv6 accept -> E4 SGv6 load -> E5 en_o edges
// Every row carries time_ps and the cycle count in its own clock domain,
// counted from reset release. Samples are taken at posedge, i.e. the values
// the flops see on that edge (same convention as the tproc_ctrl.csv logger).
// All files are written into EMU_DIR.

`define TM_QPROC qick_dut.AXIS_QPROC.QPROC
`define TM_DISP  qick_dut.AXIS_QPROC.QPROC.DISPATCHER
`define TM_SGC   qick_dut.u_axis_signal_gen_v6_0.signal_gen_top_i.signal_gen_i.ctrl_i
`define TM_SGC1  qick_dut.u_axis_signal_gen_v6_1.signal_gen_top_i.signal_gen_i.ctrl_i

integer tm_e0i_fd, tm_e0_fd, tm_e1_fd, tm_e2_fd, tm_trace_fd;
integer tm_e3_fd, tm_e4_fd, tm_e5_fd, tm_flags_fd, tm_meta_fd;
// SG1 (tProc wave port 1): same event files with an ev_sg1_ prefix
integer tm1_e1_fd, tm1_e2_fd, tm1_e3_fd, tm1_e4_fd, tm1_e5_fd;
logic   tm_open = 1'b0;

longint unsigned tm_c_cyc  = 0;
longint unsigned tm_t_cyc  = 0;
longint unsigned tm_sg_cyc = 0;

function automatic real tm_ps();
   return $realtime / 1ps;
endfunction

initial begin
   #2ns;  // EMU_DIR plusarg is parsed at time 0
   tm_e0i_fd   = $fopen({EMU_DIR, "/ev_e0i_issue.csv"},         "w");
   tm_e0_fd    = $fopen({EMU_DIR, "/ev_e0_sched.csv"},          "w");
   tm_e1_fd    = $fopen({EMU_DIR, "/ev_e1_timeline.csv"},       "w");
   tm_e2_fd    = $fopen({EMU_DIR, "/ev_e2_tproc_out.csv"},      "w");
   tm_trace_fd = $fopen({EMU_DIR, "/ev_e2_dispatch_trace.csv"}, "w");
   tm_e3_fd    = $fopen({EMU_DIR, "/ev_e3_sg_in.csv"},          "w");
   tm_e4_fd    = $fopen({EMU_DIR, "/ev_e4_sg_load.csv"},        "w");
   tm_e5_fd    = $fopen({EMU_DIR, "/ev_e5_sg_en.csv"},          "w");
   tm_flags_fd = $fopen({EMU_DIR, "/ev_flags.csv"},             "w");
   tm_meta_fd  = $fopen({EMU_DIR, "/ev_meta.csv"},              "w");
   tm1_e1_fd   = $fopen({EMU_DIR, "/ev_sg1_e1_timeline.csv"},   "w");
   tm1_e2_fd   = $fopen({EMU_DIR, "/ev_sg1_e2_tproc_out.csv"},  "w");
   tm1_e3_fd   = $fopen({EMU_DIR, "/ev_sg1_e3_sg_in.csv"},      "w");
   tm1_e4_fd   = $fopen({EMU_DIR, "/ev_sg1_e4_sg_load.csv"},    "w");
   tm1_e5_fd   = $fopen({EMU_DIR, "/ev_sg1_e5_sg_en.csv"},      "w");

   $fdisplay(tm_e0i_fd,   "seq,time_ps,c_cyc,p_addr,p_time,c_time_ref,c_time_usr,conf,nsamp,gain,addr,phase,freq");
   $fdisplay(tm_e0_fd,    "seq,time_ps,c_cyc,port,due,conf,nsamp,gain,addr,phase,freq,raw168");
   $fdisplay(tm_e1_fd,    "seq,time_ps,t_cyc,t_time_abs,head_due");
   $fdisplay(tm_e2_fd,    "seq,time_ps,t_cyc,t_time_abs,head_due,gr_rise_t_cyc,pop_t_cyc,conf,nsamp,gain,addr,phase,freq");
   $fdisplay(tm_trace_fd, "time_ps,t_cyc,t_time_abs,wave_t_gr_r,wave_pop,wave_pop_r,not_empty_r,m_axis_tready");
   $fdisplay(tm_e3_fd,    "seq,time_ps,sg_cyc,conf,nsamp,gain,addr,phase,freq");
   $fdisplay(tm_e4_fd,    "seq,time_ps,sg_cyc,conf,nsamp,gain,addr,phase,freq");
   $fdisplay(tm_e5_fd,    "seq,time_ps,sg_cyc,edge");
   $fdisplay(tm_flags_fd, "time_ps,domain,cyc,kind");
   $fdisplay(tm1_e1_fd,   "seq,time_ps,t_cyc,t_time_abs,head_due");
   $fdisplay(tm1_e2_fd,   "seq,time_ps,t_cyc,t_time_abs,head_due,gr_rise_t_cyc,pop_t_cyc,conf,nsamp,gain,addr,phase,freq");
   $fdisplay(tm1_e3_fd,   "seq,time_ps,sg_cyc,conf,nsamp,gain,addr,phase,freq");
   $fdisplay(tm1_e4_fd,   "seq,time_ps,sg_cyc,conf,nsamp,gain,addr,phase,freq");
   $fdisplay(tm1_e5_fd,   "seq,time_ps,sg_cyc,edge");
   $fdisplay(tm_meta_fd,  "key,value");
   $fdisplay(tm_meta_fd,  "emu_dir,%s", EMU_DIR);
   $fdisplay(tm_meta_fd,  "pre_run_delay_ns,%0d", pre_run_delay_ns);
   $fdisplay(tm_meta_fd,  "test_run_time_ps,%0.3f", TEST_RUN_TIME / 1ps);
   $fflush(tm_meta_fd);
   tm_open = 1'b1;
end

//----------------------------------------------------
// c_clk domain: E0i issue, E0 schedule, acceptance-stall flags
//----------------------------------------------------
int   tm_e0i_seq = 0;
int   tm_e0_seq  = 0;
logic tm_sff_prev = 1'b0;
real  tm_c_prev_ps = 0.0;

always @(posedge c_clk) begin
   if (rst_ni && tm_open) begin
      if (tm_c_cyc == 1)
         $fdisplay(tm_meta_fd, "c_clk_period_ps,%0.3f", tm_ps() - tm_c_prev_ps);
      tm_c_prev_ps = tm_ps();

      // E0i: core emits a wave-port write (p_type 0 = WAVE)
      if (`TM_QPROC.port_we && (`TM_QPROC.out_port_data.p_type == 1'b0)) begin
         $fdisplay(tm_e0i_fd, "%0d,%0.3f,%0d,%0d,%0d,%0d,%0d,%04h,%0d,%04h,%06h,%08h,%08h",
            tm_e0i_seq, tm_ps(), tm_c_cyc,
            `TM_QPROC.out_port_data.p_addr,
            $signed(`TM_QPROC.out_port_data.p_time),
            `TM_QPROC.c_time_ref_dt,
            `TM_QPROC.c_time_usr,
            `TM_QPROC.out_port_data.p_data[167:152],
            `TM_QPROC.out_port_data.p_data[151:120],
            `TM_QPROC.out_port_data.p_data[119:88],
            `TM_QPROC.out_port_data.p_data[87:64],
            `TM_QPROC.out_port_data.p_data[63:32],
            `TM_QPROC.out_port_data.p_data[31:0]);
         $fflush(tm_e0i_fd);
         tm_e0i_seq++;
      end

      // E0: push into a wave FIFO; the due time is fixed here
      for (int p = 0; p < `OUT_WPORT_QTY; p++) begin
         if (`TM_DISP.c_fifo_wave_push_s[p]) begin
            $fdisplay(tm_e0_fd, "%0d,%0.3f,%0d,%0d,%0d,%04h,%0d,%04h,%06h,%08h,%08h,%042h",
               tm_e0_seq, tm_ps(), tm_c_cyc, p,
               `TM_DISP.c_fifo_time_in_r,
               `TM_DISP.c_fifo_data_in_r[167:152],
               `TM_DISP.c_fifo_data_in_r[151:120],
               `TM_DISP.c_fifo_data_in_r[119:88],
               `TM_DISP.c_fifo_data_in_r[87:64],
               `TM_DISP.c_fifo_data_in_r[63:32],
               `TM_DISP.c_fifo_data_in_r[31:0],
               `TM_DISP.c_fifo_data_in_r);
            $fflush(tm_e0_fd);
            tm_e0_seq++;
         end
      end

      // Acceptance stall: some dispatcher FIFO full (core_en forced low)
      if (`TM_QPROC.some_fifo_full != tm_sff_prev) begin
         $fdisplay(tm_flags_fd, "%0.3f,c_clk,%0d,%s", tm_ps(), tm_c_cyc,
            `TM_QPROC.some_fifo_full ? "some_fifo_full_rise" : "some_fifo_full_fall");
         $fflush(tm_flags_fd);
      end
      tm_sff_prev = `TM_QPROC.some_fifo_full;

      tm_c_cyc++;
   end
end

//----------------------------------------------------
// t_clk domain: E1 on timeline, E2 release, dispatcher trace, stall flags
//----------------------------------------------------
int              tm_e1_seq = 0;
int              tm_e2_seq = 0;
logic            tm_empty_prev = 1'b1;
logic            tm_gr_prev    = 1'b0;
logic [4:0]      tm_trace_prev = '0;
logic [4:0]      tm_trace_now;
longint signed   tm_gr_rise_cyc = -1;
longint signed   tm_pop_cyc     = -1;
logic            tm_proc_started = 1'b0;
int              tm1_e1_seq = 0;
int              tm1_e2_seq = 0;
logic            tm1_empty_prev = 1'b1;
logic            tm1_gr_prev    = 1'b0;
longint signed   tm1_gr_rise_cyc = -1;
longint signed   tm1_pop_cyc     = -1;
real             tm_t_prev_ps = 0.0;

always @(posedge t_clk) begin
   if (rst_ni && tm_open) begin
      if (tm_t_cyc == 1)
         $fdisplay(tm_meta_fd, "t_clk_period_ps,%0.3f", tm_ps() - tm_t_prev_ps);
      tm_t_prev_ps = tm_ps();

      if (!tm_proc_started && (t_time_abs_o != 0)) begin
         $fdisplay(tm_meta_fd, "proc_start_time_ps,%0.3f", tm_ps());
         $fdisplay(tm_meta_fd, "proc_start_t_cyc,%0d", tm_t_cyc);
         $fflush(tm_meta_fd);
         tm_proc_started = 1'b1;
      end

      // E1: wave FIFO 0 goes non-empty on the t_clk side
      if (tm_empty_prev && !`TM_DISP.t_fifo_wave_empty[0]) begin
         $fdisplay(tm_e1_fd, "%0d,%0.3f,%0d,%0d,%0d",
            tm_e1_seq, tm_ps(), tm_t_cyc, t_time_abs_o, `TM_DISP.t_fifo_wave_time[0]);
         $fflush(tm_e1_fd);
         tm_e1_seq++;
      end
      tm_empty_prev = `TM_DISP.t_fifo_wave_empty[0];

      // Dispatcher internals for the head of wave FIFO 0
      if (`TM_DISP.wave_t_gr_r[0] && !tm_gr_prev) tm_gr_rise_cyc = tm_t_cyc;
      tm_gr_prev = `TM_DISP.wave_t_gr_r[0];
      if (`TM_DISP.wave_pop[0]) tm_pop_cyc = tm_t_cyc;

      tm_trace_now = {`TM_DISP.wave_t_gr_r[0], `TM_DISP.wave_pop[0], `TM_DISP.wave_pop_r[0],
                      ~`TM_DISP.t_fifo_wave_empty_r[0], `TM_DISP.m_axis_tready[0]};
      if (tm_trace_now != tm_trace_prev) begin
         $fdisplay(tm_trace_fd, "%0.3f,%0d,%0d,%0d,%0d,%0d,%0d,%0d",
            tm_ps(), tm_t_cyc, t_time_abs_o,
            tm_trace_now[4], tm_trace_now[3], tm_trace_now[2], tm_trace_now[1], tm_trace_now[0]);
         $fflush(tm_trace_fd);
      end
      tm_trace_prev = tm_trace_now;

      // E2: tProc wave port 0 released and accepted by the SG CDC
      if (qick_dut.tproc_sg0cdc_axis_tvalid && qick_dut.tproc_sg0cdc_axis_tready) begin
         $fdisplay(tm_e2_fd, "%0d,%0.3f,%0d,%0d,%0d,%0d,%0d,%04h,%0d,%04h,%06h,%08h,%08h",
            tm_e2_seq, tm_ps(), tm_t_cyc, t_time_abs_o, `TM_DISP.t_fifo_wave_time[0],
            tm_gr_rise_cyc, tm_pop_cyc,
            qick_dut.tproc_sg0cdc_axis_tdata[167:152],
            qick_dut.tproc_sg0cdc_axis_tdata[151:120],
            qick_dut.tproc_sg0cdc_axis_tdata[119:88],
            qick_dut.tproc_sg0cdc_axis_tdata[87:64],
            qick_dut.tproc_sg0cdc_axis_tdata[63:32],
            qick_dut.tproc_sg0cdc_axis_tdata[31:0]);
         $fflush(tm_e2_fd);
         tm_e2_seq++;
      end

      // Stall: tProc offers a command but the CDC is not ready
      if (qick_dut.tproc_sg0cdc_axis_tvalid && !qick_dut.tproc_sg0cdc_axis_tready) begin
         $fdisplay(tm_flags_fd, "%0.3f,t_clk,%0d,tproc_m0_stall", tm_ps(), tm_t_cyc);
         $fflush(tm_flags_fd);
      end

      // ---- SG1 (wave port 1): E1, dispatcher internals, E2, stall ----
      if (tm1_empty_prev && !`TM_DISP.t_fifo_wave_empty[1]) begin
         $fdisplay(tm1_e1_fd, "%0d,%0.3f,%0d,%0d,%0d",
            tm1_e1_seq, tm_ps(), tm_t_cyc, t_time_abs_o, `TM_DISP.t_fifo_wave_time[1]);
         $fflush(tm1_e1_fd);
         tm1_e1_seq++;
      end
      tm1_empty_prev = `TM_DISP.t_fifo_wave_empty[1];
      if (`TM_DISP.wave_t_gr_r[1] && !tm1_gr_prev) tm1_gr_rise_cyc = tm_t_cyc;
      tm1_gr_prev = `TM_DISP.wave_t_gr_r[1];
      if (`TM_DISP.wave_pop[1]) tm1_pop_cyc = tm_t_cyc;
      if (qick_dut.tproc_sg1cdc_axis_tvalid && qick_dut.tproc_sg1cdc_axis_tready) begin
         $fdisplay(tm1_e2_fd, "%0d,%0.3f,%0d,%0d,%0d,%0d,%0d,%04h,%0d,%04h,%06h,%08h,%08h",
            tm1_e2_seq, tm_ps(), tm_t_cyc, t_time_abs_o, `TM_DISP.t_fifo_wave_time[1],
            tm1_gr_rise_cyc, tm1_pop_cyc,
            qick_dut.tproc_sg1cdc_axis_tdata[167:152],
            qick_dut.tproc_sg1cdc_axis_tdata[151:120],
            qick_dut.tproc_sg1cdc_axis_tdata[119:88],
            qick_dut.tproc_sg1cdc_axis_tdata[87:64],
            qick_dut.tproc_sg1cdc_axis_tdata[63:32],
            qick_dut.tproc_sg1cdc_axis_tdata[31:0]);
         $fflush(tm1_e2_fd);
         tm1_e2_seq++;
      end
      if (qick_dut.tproc_sg1cdc_axis_tvalid && !qick_dut.tproc_sg1cdc_axis_tready) begin
         $fdisplay(tm_flags_fd, "%0.3f,t_clk,%0d,tproc_m1_stall", tm_ps(), tm_t_cyc);
         $fflush(tm_flags_fd);
      end

      tm_t_cyc++;
   end
end

//----------------------------------------------------
// sg_clk domain: E3 SGv6 accept, E4 SGv6 load, E5 en_o edges, violations
//----------------------------------------------------
int   tm_e3_seq = 0;
int   tm_e4_seq = 0;
int   tm_e5_seq = 0;
logic tm_en_prev = 1'b0;
int   tm1_e3_seq = 0;
int   tm1_e4_seq = 0;
int   tm1_e5_seq = 0;
logic tm1_en_prev = 1'b0;
real  tm_sg_prev_ps = 0.0;

always @(posedge sg_clk) begin
   if (rst_ni && tm_open) begin
      if (tm_sg_cyc == 1)
         $fdisplay(tm_meta_fd, "sg_clk_period_ps,%0.3f", tm_ps() - tm_sg_prev_ps);
      tm_sg_prev_ps = tm_ps();

      // E3: command accepted at SGv6 s1_axis (after CDC + translator)
      if (qick_dut.sgt0_sg0_axis_tvalid && qick_dut.sgt0_sg0_axis_tready) begin
         $fdisplay(tm_e3_fd, "%0d,%0.3f,%0d,%02h,%0d,%04h,%04h,%08h,%08h",
            tm_e3_seq, tm_ps(), tm_sg_cyc,
            qick_dut.sgt0_sg0_axis_tdata[148:144],
            qick_dut.sgt0_sg0_axis_tdata[143:128],
            qick_dut.sgt0_sg0_axis_tdata[111:96],
            qick_dut.sgt0_sg0_axis_tdata[79:64],
            qick_dut.sgt0_sg0_axis_tdata[63:32],
            qick_dut.sgt0_sg0_axis_tdata[31:0]);
         $fflush(tm_e3_fd);
         tm_e3_seq++;
      end

      // Violation: SGv6 writes its FIFO on tvalid alone
      if (qick_dut.sgt0_sg0_axis_tvalid && !qick_dut.sgt0_sg0_axis_tready) begin
         $fdisplay(tm_flags_fd, "%0.3f,sg_clk,%0d,sg0_s1_tvalid_without_tready", tm_ps(), tm_sg_cyc);
         $fflush(tm_flags_fd);
      end

      // E4: SGv6 control FSM loads the next command (load_int = rd_en_int & ~fifo_empty_i)
      if (`TM_SGC.load_int) begin
         $fdisplay(tm_e4_fd, "%0d,%0.3f,%0d,%02h,%0d,%04h,%04h,%08h,%08h",
            tm_e4_seq, tm_ps(), tm_sg_cyc,
            `TM_SGC.fifo_dout_i[148:144],
            `TM_SGC.fifo_dout_i[143:128],
            `TM_SGC.fifo_dout_i[111:96],
            `TM_SGC.fifo_dout_i[79:64],
            `TM_SGC.fifo_dout_i[63:32],
            `TM_SGC.fifo_dout_i[31:0]);
         $fflush(tm_e4_fd);
         tm_e4_seq++;
      end

      // E5: output enable edges
      if (`TM_SGC.en_o != tm_en_prev) begin
         $fdisplay(tm_e5_fd, "%0d,%0.3f,%0d,%s", tm_e5_seq, tm_ps(), tm_sg_cyc,
            `TM_SGC.en_o ? "rise" : "fall");
         $fflush(tm_e5_fd);
         tm_e5_seq++;
      end
      tm_en_prev = `TM_SGC.en_o;

      // ---- SG1: E3, E4, E5, violation ----
      if (qick_dut.sgt1_sg1_axis_tvalid && qick_dut.sgt1_sg1_axis_tready) begin
         $fdisplay(tm1_e3_fd, "%0d,%0.3f,%0d,%02h,%0d,%04h,%04h,%08h,%08h",
            tm1_e3_seq, tm_ps(), tm_sg_cyc,
            qick_dut.sgt1_sg1_axis_tdata[148:144],
            qick_dut.sgt1_sg1_axis_tdata[143:128],
            qick_dut.sgt1_sg1_axis_tdata[111:96],
            qick_dut.sgt1_sg1_axis_tdata[79:64],
            qick_dut.sgt1_sg1_axis_tdata[63:32],
            qick_dut.sgt1_sg1_axis_tdata[31:0]);
         $fflush(tm1_e3_fd);
         tm1_e3_seq++;
      end
      if (qick_dut.sgt1_sg1_axis_tvalid && !qick_dut.sgt1_sg1_axis_tready) begin
         $fdisplay(tm_flags_fd, "%0.3f,sg_clk,%0d,sg1_s1_tvalid_without_tready", tm_ps(), tm_sg_cyc);
         $fflush(tm_flags_fd);
      end
      if (`TM_SGC1.load_int) begin
         $fdisplay(tm1_e4_fd, "%0d,%0.3f,%0d,%02h,%0d,%04h,%04h,%08h,%08h",
            tm1_e4_seq, tm_ps(), tm_sg_cyc,
            `TM_SGC1.fifo_dout_i[148:144],
            `TM_SGC1.fifo_dout_i[143:128],
            `TM_SGC1.fifo_dout_i[111:96],
            `TM_SGC1.fifo_dout_i[79:64],
            `TM_SGC1.fifo_dout_i[63:32],
            `TM_SGC1.fifo_dout_i[31:0]);
         $fflush(tm1_e4_fd);
         tm1_e4_seq++;
      end
      if (`TM_SGC1.en_o != tm1_en_prev) begin
         $fdisplay(tm1_e5_fd, "%0d,%0.3f,%0d,%s", tm1_e5_seq, tm_ps(), tm_sg_cyc,
            `TM_SGC1.en_o ? "rise" : "fall");
         $fflush(tm1_e5_fd);
         tm1_e5_seq++;
      end
      tm1_en_prev = `TM_SGC1.en_o;

      tm_sg_cyc++;
   end
end

`undef TM_QPROC
`undef TM_DISP
`undef TM_SGC
`undef TM_SGC1
