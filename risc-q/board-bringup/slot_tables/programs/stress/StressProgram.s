.equ RQ_MEM_BASE, 0x80000000
.equ RQ_MEM_BYTES, 0x4000
.equ RQ_CTRL_FROM_HOST, 0x2000
.equ RQ_CTRL_TIME_CMP, 0x4000
.equ RQ_CTRL_WAIT_TIME_CMP, 0x4008
.equ RQ_CTRL_RES, 0x4200
.equ RQ_CTRL_REAL, 0x4204
.equ RQ_CTRL_IMAG, 0x4208
.equ RQ_CTRL_TIME, 0xbff8
.equ RQ_GATE, 0x10000
.equ RQ_READOUT, 0x20000
.equ RQ_DEMOD, 0x30000
.equ RQ_FIRE, 0x0
.equ RQ_FREQ, 0x4
.equ RQ_DC_OFFSET, 0x8
.equ RQ_PHASE_OFFSET, 0xc
.equ RQ_SLOT_STRIDE, 0x10
.equ RQ_START_TIME, 0x4100
.equ RQ_SLOT_CONF, 0x4200
.equ RQ_SLOT_FREQ, 0x4300
.equ RQ_FIRE_AT, 0x4400
.equ RQ_FIRE_SLOT, 0x4480
.equ RQ_GATE_PULSE_NUM, 0x20
.equ RQ_ENV_DEPTH, 0x400
.equ RQ_LEAD, 0x60
.equ RQ_RO_LEAD, 0x30
.equ RQ_RO_MAX_WIN, 0x4000
.equ RF_CH0, 0x10000
.equ RF_CH1, 0x20000
.equ RF_CH2, 0x30000
.text
.globl main
main:
    addi sp, sp, -16
    sw ra, 12(sp)
        li s2, RF_CH2+16640
        li s3, RF_CH2
        li s4, RF_CH0+RQ_FIRE_AT
        li s5, RF_CH1+RQ_FIRE_AT
        li s6, RQ_CTRL_TIME_CMP
        la s7, __qick_ext+0
        li s8, 3
        la s1, __qick_ext+0
        lw s1, 0(s1)
    li t1, RF_CH0
    sw x0, 12(t1)
    li t1, RF_CH1
    sw x0, 12(t1)
# slot 0 of gen 0 <- g0_w0
    li a5, 268435392
    li a6, 0
    li a7, 0
    li t3, 4095
    li t4, 20
    li t5, 8
    li t1, RF_CH0
    li t2, RF_CH0+RQ_SLOT_FREQ+0
    sw a5, 0(t2)
    sw a6, 16(t1)
    slli t2, a7, 16
    sw t2, 24(t1)
    slli t2, t3, 16
    sw t2, 20(t1)
    slli t2, t4, 16
    sw t2, 28(t1)
    li t2, RF_CH0+RQ_SLOT_CONF+0
    sw t5, 0(t2)
# slot 1 of gen 0 <- g1_w0
    li a6, 536870912
    li t3, 8191
    li t2, RF_CH0+RQ_SLOT_FREQ+4
    sw a5, 0(t2)
    sw a6, 32(t1)
    slli t2, a7, 16
    sw t2, 40(t1)
    slli t2, t3, 16
    sw t2, 36(t1)
    slli t2, t4, 16
    sw t2, 44(t1)
    li t2, RF_CH0+RQ_SLOT_CONF+4
    sw t5, 0(t2)
# slot 2 of gen 0 <- g2_w0
    li a6, 1073741824
    li t3, 12287
    li t2, RF_CH0+RQ_SLOT_FREQ+8
    sw a5, 0(t2)
    sw a6, 48(t1)
    slli t2, a7, 16
    sw t2, 56(t1)
    slli t2, t3, 16
    sw t2, 52(t1)
    slli t2, t4, 16
    sw t2, 60(t1)
    li t2, RF_CH0+RQ_SLOT_CONF+8
    sw t5, 0(t2)
# slot 3 of gen 0 <- g3_w0
    li a6, 1610612736
    li t3, 16383
    li t2, RF_CH0+RQ_SLOT_FREQ+12
    sw a5, 0(t2)
    sw a6, 64(t1)
    slli t2, a7, 16
    sw t2, 72(t1)
    slli t2, t3, 16
    sw t2, 68(t1)
    slli t2, t4, 16
    sw t2, 76(t1)
    li t2, RF_CH0+RQ_SLOT_CONF+12
    sw t5, 0(t2)
# slot 4 of gen 0 <- g4_w0
    li a6, -2147483648
    li t3, 20478
    li t2, RF_CH0+RQ_SLOT_FREQ+16
    sw a5, 0(t2)
    sw a6, 80(t1)
    slli t2, a7, 16
    sw t2, 88(t1)
    slli t2, t3, 16
    sw t2, 84(t1)
    slli t2, t4, 16
    sw t2, 92(t1)
    li t2, RF_CH0+RQ_SLOT_CONF+16
    sw t5, 0(t2)
# slot 5 of gen 0 <- g5_w0
    li a6, -1610612736
    li t3, 24574
    li t2, RF_CH0+RQ_SLOT_FREQ+20
    sw a5, 0(t2)
    sw a6, 96(t1)
    slli t2, a7, 16
    sw t2, 104(t1)
    slli t2, t3, 16
    sw t2, 100(t1)
    slli t2, t4, 16
    sw t2, 108(t1)
    li t2, RF_CH0+RQ_SLOT_CONF+20
    sw t5, 0(t2)
# slot 6 of gen 0 <- g6_w0
    li a6, -1073741824
    li t3, 28670
    li t2, RF_CH0+RQ_SLOT_FREQ+24
    sw a5, 0(t2)
    sw a6, 112(t1)
    slli t2, a7, 16
    sw t2, 120(t1)
    slli t2, t3, 16
    sw t2, 116(t1)
    slli t2, t4, 16
    sw t2, 124(t1)
    li t2, RF_CH0+RQ_SLOT_CONF+24
    sw t5, 0(t2)
# slot 7 of gen 0 <- g7_w0
    li a6, -536870912
    li t3, 32766
    li t2, RF_CH0+RQ_SLOT_FREQ+28
    sw a5, 0(t2)
    sw a6, 128(t1)
    slli t2, a7, 16
    sw t2, 136(t1)
    slli t2, t3, 16
    sw t2, 132(t1)
    slli t2, t4, 16
    sw t2, 140(t1)
    li t2, RF_CH0+RQ_SLOT_CONF+28
    sw t5, 0(t2)
# slot 0 of gen 1 <- h0_w0
    li a5, 53687040
    li a6, 0
    li t3, 26212
    li t4, 40
    li t5, 9
    li t1, RF_CH1
    li t2, RF_CH1+RQ_SLOT_FREQ+0
    sw a5, 0(t2)
    sw a6, 16(t1)
    slli t2, a7, 16
    sw t2, 24(t1)
    slli t2, t3, 16
    sw t2, 20(t1)
    slli t2, t4, 16
    sw t2, 28(t1)
    li t2, RF_CH1+RQ_SLOT_CONF+0
    sw t5, 0(t2)
# slot 1 of gen 1 <- h1_w0
    li a5, 107374272
    li t2, RF_CH1+RQ_SLOT_FREQ+4
    sw a5, 0(t2)
    sw a6, 32(t1)
    slli t2, a7, 16
    sw t2, 40(t1)
    slli t2, t3, 16
    sw t2, 36(t1)
    slli t2, t4, 16
    sw t2, 44(t1)
    li t2, RF_CH1+RQ_SLOT_CONF+4
    sw t5, 0(t2)
# slot 2 of gen 1 <- h2_w0
    li a5, 161061312
    li t2, RF_CH1+RQ_SLOT_FREQ+8
    sw a5, 0(t2)
    sw a6, 48(t1)
    slli t2, a7, 16
    sw t2, 56(t1)
    slli t2, t3, 16
    sw t2, 52(t1)
    slli t2, t4, 16
    sw t2, 60(t1)
    li t2, RF_CH1+RQ_SLOT_CONF+8
    sw t5, 0(t2)
# slot 3 of gen 1 <- h3_w0
    li a5, 214748352
    li t2, RF_CH1+RQ_SLOT_FREQ+12
    sw a5, 0(t2)
    sw a6, 64(t1)
    slli t2, a7, 16
    sw t2, 72(t1)
    slli t2, t3, 16
    sw t2, 68(t1)
    slli t2, t4, 16
    sw t2, 76(t1)
    li t2, RF_CH1+RQ_SLOT_CONF+12
    sw t5, 0(t2)
    li t1, RQ_CTRL_TIME
    lw s11, 0(t1)
    la t0, __qick_ext+0
    sw x0, 0(t0)
    mv s1, x0
    la t1, __qick_wmem+288
    lw a5, 0(t1)
    lw a6, 4(t1)
    li t1, RF_CH2
    sw a5, 4(t1)
    sw a6, 12(t1)
    li t2, 65536000    # PATCH readout window: RF_CH2 slot 0 dur = 1000 cycles (2.0 us)
    sw t2, 28(t1)
    addi s11, s11, 500
    li s0, 0
reps:
    addi t0, s11, 0
    sw t0, 0(s2)
    sw x0, 0(s3)
    sw t0, 0(s4)
    addi t0, s11, 10
    sw t0, 0(s5)
    addi t0, s11, 25
    sw t0, 4(s4)
    addi t0, s11, 50
    sw t0, 8(s4)
    addi t0, s11, 60
    sw t0, 4(s5)
    addi t0, s11, 75
    sw t0, 12(s4)
    addi t0, s11, 100
    sw t0, 16(s4)
    addi t0, s11, 110
    sw t0, 8(s5)
    addi t0, s11, 125
    sw t0, 20(s4)
    addi t0, s11, 150
    sw t0, 24(s4)
    addi t0, s11, 160
    sw t0, 12(s5)
    addi t0, s11, 175
    sw t0, 28(s4)
    addi t0, s11, 200
    sw t0, 0(s4)
    addi t0, s11, 210
    sw t0, 0(s5)
    addi t0, s11, 225
    sw t0, 4(s4)
    addi t0, s11, 250
    sw t0, 8(s4)
    addi t0, s11, 260
    sw t0, 4(s5)
    addi t0, s11, 275
    sw t0, 12(s4)
    addi t0, s11, 300
    sw t0, 16(s4)
    addi t0, s11, 310
    sw t0, 8(s5)
    addi t0, s11, 325
    sw t0, 20(s4)
    addi t0, s11, 350
    sw t0, 24(s4)
    addi t0, s11, 360
    sw t0, 12(s5)
    addi t0, s11, 375
    sw t0, 28(s4)
    addi t0, s11, 400
    sw t0, 0(s4)
    addi t0, s11, 410
    sw t0, 0(s5)
    addi t0, s11, 425
    sw t0, 4(s4)
    addi t0, s11, 450
    sw t0, 8(s4)
    addi t0, s11, 460
    sw t0, 4(s5)
    addi t0, s11, 475
    sw t0, 12(s4)
    addi t0, s11, 500
    sw t0, 16(s4)
    addi t0, s11, 510
    sw t0, 8(s5)
    addi t0, s11, 525
    sw t0, 20(s4)
    addi t0, s11, 550
    sw t0, 24(s4)
    addi t0, s11, 560
    sw t0, 12(s5)
    addi t0, s11, 575
    sw t0, 28(s4)
    addi t0, s11, 600
    sw t0, 0(s4)
    addi t0, s11, 610
    sw t0, 0(s5)
    addi t0, s11, 625
    sw t0, 4(s4)
    addi t0, s11, 650
    sw t0, 8(s4)
    addi t0, s11, 660
    sw t0, 4(s5)
    addi t0, s11, 675
    sw t0, 12(s4)
    addi t0, s11, 700
    sw t0, 16(s4)
    addi t0, s11, 710
    sw t0, 8(s5)
    addi t0, s11, 725
    sw t0, 20(s4)
    addi t0, s11, 999
    sw t0, 0(s6)
    addi s11, s11, 1249
    addi s1, s1, 1
    sw s1, 0(s7)
    addi s0, s0, 1
    lw x0, 8(s6)
    blt s0, s8, reps
    j __qick_exit
__qick_exit:
    lw ra, 12(sp)
    addi sp, sp, 16
    li a0, 0
    ret
.section .data
.align 2
__qick_wmem:
.word 268435392    # g0_w0.freq
.word 0    # g0_w0.phase
.word 0    # g0_w0.env
.word 4095    # g0_w0.gain
.word 20    # g0_w0.length
.word 8    # g0_w0.conf
.word 268435392    # g1_w0.freq
.word 536870912    # g1_w0.phase
.word 0    # g1_w0.env
.word 8191    # g1_w0.gain
.word 20    # g1_w0.length
.word 8    # g1_w0.conf
.word 268435392    # g2_w0.freq
.word 1073741824    # g2_w0.phase
.word 0    # g2_w0.env
.word 12287    # g2_w0.gain
.word 20    # g2_w0.length
.word 8    # g2_w0.conf
.word 268435392    # g3_w0.freq
.word 1610612736    # g3_w0.phase
.word 0    # g3_w0.env
.word 16383    # g3_w0.gain
.word 20    # g3_w0.length
.word 8    # g3_w0.conf
.word 268435392    # g4_w0.freq
.word -2147483648    # g4_w0.phase
.word 0    # g4_w0.env
.word 20478    # g4_w0.gain
.word 20    # g4_w0.length
.word 8    # g4_w0.conf
.word 268435392    # g5_w0.freq
.word -1610612736    # g5_w0.phase
.word 0    # g5_w0.env
.word 24574    # g5_w0.gain
.word 20    # g5_w0.length
.word 8    # g5_w0.conf
.word 268435392    # g6_w0.freq
.word -1073741824    # g6_w0.phase
.word 0    # g6_w0.env
.word 28670    # g6_w0.gain
.word 20    # g6_w0.length
.word 8    # g6_w0.conf
.word 268435392    # g7_w0.freq
.word -536870912    # g7_w0.phase
.word 0    # g7_w0.env
.word 32766    # g7_w0.gain
.word 20    # g7_w0.length
.word 8    # g7_w0.conf
.word 53687040    # h0_w0.freq
.word 0    # h0_w0.phase
.word 0    # h0_w0.env
.word 26212    # h0_w0.gain
.word 40    # h0_w0.length
.word 9    # h0_w0.conf
.word 107374272    # h1_w0.freq
.word 0    # h1_w0.phase
.word 0    # h1_w0.env
.word 26212    # h1_w0.gain
.word 40    # h1_w0.length
.word 9    # h1_w0.conf
.word 161061312    # h2_w0.freq
.word 0    # h2_w0.phase
.word 0    # h2_w0.env
.word 26212    # h2_w0.gain
.word 40    # h2_w0.length
.word 9    # h2_w0.conf
.word 214748352    # h3_w0.freq
.word 0    # h3_w0.phase
.word 0    # h3_w0.env
.word 26212    # h3_w0.gain
.word 40    # h3_w0.length
.word 9    # h3_w0.conf
.word -873813125    # myro_w0.freq
.word 0    # myro_w0.phase
.word 0    # myro_w0.env
.word 0    # myro_w0.gain
.word 3    # myro_w0.length
.word 8    # myro_w0.conf
.type __qick_ext, @object
.size __qick_ext, 8
__qick_ext:
.space 8
.type __qick_dmem, @object
.size __qick_dmem, 1024
__qick_dmem:
.space 1024
