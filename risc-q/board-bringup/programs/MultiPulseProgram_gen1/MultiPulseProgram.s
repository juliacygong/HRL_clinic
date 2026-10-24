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
.equ RQ_GATE_PULSE_NUM, 0x8
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
    li t1, RQ_CTRL_TIME
    lw s11, 0(t1)
    li t1, RF_CH1
    sw x0, 12(t1)
    la t0, __qick_ext+0
    sw x0, 0(t0)
    la t1, __qick_wmem+192
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    li t1, RF_CH2
    sw a5, 4(t1)
    sw a6, 12(t1)
    addi s11, s11, 500
    li s0, 0
reps:
    addi t0, s11, 150
    li t2, RF_CH2+16640
    sw t0, 0(t2)
    li t1, RF_CH2
    sw x0, 0(t1)
    addi t0, s11, 0
    la t1, __qick_wmem+0
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    li t1, RF_CH1
    sw a5, 4(t1)
    sw a6, 16(t1)
    slli t2, t3, 16
    sw t2, 20(t1)
    slli t2, a7, 16
    sw t2, 24(t1)
    slli t2, t4, 16
    sw t2, 28(t1)
    li t2, RF_CH1+16644
    sw t5, 0(t2)
    li t2, RF_CH1+16640
    sw t0, 0(t2)
    li t1, RF_CH1
    sw x0, 0(t1)
    add t0, t0, t4
    la t1, __qick_wmem+24
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    li t1, RF_CH1
    sw a5, 4(t1)
    sw a6, 32(t1)
    slli t2, t3, 16
    sw t2, 36(t1)
    slli t2, a7, 16
    sw t2, 40(t1)
    slli t2, t4, 16
    sw t2, 44(t1)
    li t2, RF_CH1+16644
    sw t5, 0(t2)
    li t2, RF_CH1+16640
    sw t0, 0(t2)
    li t1, RF_CH1
    li t2, 1
    sw t2, 0(t1)
    add t0, t0, t4
    la t1, __qick_wmem+48
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    li t1, RF_CH1
    sw a5, 4(t1)
    sw a6, 48(t1)
    slli t2, t3, 16
    sw t2, 52(t1)
    slli t2, a7, 16
    sw t2, 56(t1)
    slli t2, t4, 16
    sw t2, 60(t1)
    li t2, RF_CH1+16644
    sw t5, 0(t2)
    li t2, RF_CH1+16640
    sw t0, 0(t2)
    li t1, RF_CH1
    li t2, 2
    sw t2, 0(t1)
    addi t0, s11, 200
    la t1, __qick_wmem+72
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    li t1, RF_CH1
    sw a5, 4(t1)
    sw a6, 16(t1)
    slli t2, t3, 16
    sw t2, 20(t1)
    slli t2, a7, 16
    sw t2, 24(t1)
    slli t2, t4, 16
    sw t2, 28(t1)
    li t2, RF_CH1+16644
    sw t5, 0(t2)
    li t2, RF_CH1+16640
    sw t0, 0(t2)
    li t1, RF_CH1
    sw x0, 0(t1)
    addi t0, s11, 400
    la t1, __qick_wmem+96
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    li t1, RF_CH1
    sw a5, 4(t1)
    sw a6, 16(t1)
    slli t2, t3, 16
    sw t2, 20(t1)
    slli t2, a7, 16
    sw t2, 24(t1)
    slli t2, t4, 16
    sw t2, 28(t1)
    li t2, RF_CH1+16644
    sw t5, 0(t2)
    li t2, RF_CH1+16640
    sw t0, 0(t2)
    li t1, RF_CH1
    sw x0, 0(t1)
    addi t0, s11, 600
    la t1, __qick_wmem+120
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    li t1, RF_CH1
    sw a5, 4(t1)
    sw a6, 16(t1)
    slli t2, t3, 16
    sw t2, 20(t1)
    slli t2, a7, 16
    sw t2, 24(t1)
    slli t2, t4, 16
    sw t2, 28(t1)
    li t2, RF_CH1+16644
    sw t5, 0(t2)
    li t2, RF_CH1+16640
    sw t0, 0(t2)
    li t1, RF_CH1
    sw x0, 0(t1)
    add t0, t0, t4
    la t1, __qick_wmem+144
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    li t1, RF_CH1
    sw a5, 4(t1)
    sw a6, 32(t1)
    slli t2, t3, 16
    sw t2, 36(t1)
    slli t2, a7, 16
    sw t2, 40(t1)
    slli t2, t4, 16
    sw t2, 44(t1)
    li t2, RF_CH1+16644
    sw t5, 0(t2)
    li t2, RF_CH1+16640
    sw t0, 0(t2)
    li t1, RF_CH1
    li t2, 1
    sw t2, 0(t1)
    add t0, t0, t4
    la t1, __qick_wmem+168
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    li t1, RF_CH1
    sw a5, 4(t1)
    sw a6, 48(t1)
    slli t2, t3, 16
    sw t2, 52(t1)
    slli t2, a7, 16
    sw t2, 56(t1)
    slli t2, t4, 16
    sw t2, 60(t1)
    li t2, RF_CH1+16644
    sw t5, 0(t2)
    li t2, RF_CH1+16640
    sw t0, 0(t2)
    li t1, RF_CH1
    li t2, 2
    sw t2, 0(t1)
    addi t0, s11, 800
    la t1, __qick_wmem+72
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    li t1, RF_CH1
    sw a5, 4(t1)
    sw a6, 16(t1)
    slli t2, t3, 16
    sw t2, 20(t1)
    slli t2, a7, 16
    sw t2, 24(t1)
    slli t2, t4, 16
    sw t2, 28(t1)
    li t2, RF_CH1+16644
    sw t5, 0(t2)
    li t2, RF_CH1+16640
    sw t0, 0(t2)
    li t1, RF_CH1
    sw x0, 0(t1)
    addi t0, s11, 1101
    li t1, RQ_CTRL_TIME_CMP
    sw t0, 0(t1)
    lw x0, 8(t1)
    addi s11, s11, 1351
    la t0, __qick_ext+0
    lw t1, 0(t0)
    addi t1, t1, 1
    sw t1, 0(t0)
    addi s0, s0, 1
    li t0, 1
    blt s0, t0, reps
    j __qick_exit
__qick_exit:
    lw ra, 12(sp)
    addi sp, sp, 16
    li a0, 0
    ret
.section .data
.align 2
__qick_wmem:
.word 268435392    # myflattop_w0.freq
.word 0    # myflattop_w0.phase
.word 0    # myflattop_w0.env
.word 32766    # myflattop_w0.gain
.word 50    # myflattop_w0.length
.word 8    # myflattop_w0.conf
.word 268435392    # myflattop_w1.freq
.word 0    # myflattop_w1.phase
.word 0    # myflattop_w1.env
.word 16383    # myflattop_w1.gain
.word 50    # myflattop_w1.length
.word 9    # myflattop_w1.conf
.word 268435392    # myflattop_w2.freq
.word 0    # myflattop_w2.phase
.word 50    # myflattop_w2.env
.word 32766    # myflattop_w2.gain
.word 50    # myflattop_w2.length
.word 8    # myflattop_w2.conf
.word 268435392    # mygaus_w0.freq
.word 0    # mygaus_w0.phase
.word 0    # mygaus_w0.env
.word 32766    # mygaus_w0.gain
.word 100    # mygaus_w0.length
.word 8    # mygaus_w0.conf
.word 268435392    # myconst_w0.freq
.word 0    # myconst_w0.phase
.word 0    # myconst_w0.env
.word 32766    # myconst_w0.gain
.word 100    # myconst_w0.length
.word 9    # myconst_w0.conf
.word 268435392    # myflattop2_w0.freq
.word 1073741824    # myflattop2_w0.phase
.word 0    # myflattop2_w0.env
.word 32766    # myflattop2_w0.gain
.word 50    # myflattop2_w0.length
.word 8    # myflattop2_w0.conf
.word 268435392    # myflattop2_w1.freq
.word 1073741824    # myflattop2_w1.phase
.word 0    # myflattop2_w1.env
.word 16383    # myflattop2_w1.gain
.word 50    # myflattop2_w1.length
.word 9    # myflattop2_w1.conf
.word 268435392    # myflattop2_w2.freq
.word 1073741824    # myflattop2_w2.phase
.word 50    # myflattop2_w2.env
.word 32766    # myflattop2_w2.gain
.word 50    # myflattop2_w2.length
.word 8    # myflattop2_w2.conf
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
