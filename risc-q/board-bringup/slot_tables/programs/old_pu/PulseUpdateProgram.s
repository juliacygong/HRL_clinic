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
        li s10, RF_CH2+16640
        li a1, RF_CH2
        li a2, RF_CH0
        li a3, RF_CH0+16644
        li a4, RF_CH0+16640
        la s9, __qick_ext+0
        lw s9, 0(s9)
        la s1, __qick_wmem+0
        lw s1, 0(s1)
        la s2, __qick_wmem+4
        lw s2, 0(s2)
        la s3, __qick_wmem+8
        lw s3, 0(s3)
        la s4, __qick_wmem+12
        lw s4, 0(s4)
        la s5, __qick_wmem+16
        lw s5, 0(s5)
        la s6, __qick_wmem+20
        lw s6, 0(s6)
        la s7, __qick_wmem+24
        lw s7, 0(s7)
        la s8, __qick_wmem+28
        lw s8, 0(s8)
    li t1, RF_CH0
    sw x0, 12(t1)
    li t1, RQ_CTRL_TIME
    lw s11, 0(t1)
    la t0, __qick_ext+0
    sw x0, 0(t0)
    mv s9, x0
    la t1, __qick_wmem+72
    lw a5, 0(t1)
    lw a6, 4(t1)
    li t1, RF_CH2
    sw a5, 4(t1)
    sw a6, 12(t1)
    li t2, 29491200    # PATCH readout window: RF_CH2 slot 0 dur = 450 cycles (0.9 us)
    sw t2, 28(t1)
    addi s11, s11, 500
    li s0, 0
reps:
    addi t0, s11, 0
    sw t0, 0(s10)
    sw x0, 0(a1)
    mv a5, s1
    mv a6, s2
    mv a7, s3
    mv t3, s4
    mv t4, s5
    mv t5, s6
    sw a5, 4(a2)
    sw a6, 16(a2)
    slli t2, t3, 16
    sw t2, 20(a2)
    slli t2, a7, 16
    sw t2, 24(a2)
    slli t2, t4, 16
    sw t2, 28(a2)
    sw t5, 0(a3)
    sw t0, 0(a4)
    sw x0, 0(a2)
    add t0, t0, t4
    la t1, __qick_wmem+24
    mv a5, s7
    mv a6, s8
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    sw a5, 4(a2)
    sw a6, 32(a2)
    slli t2, t3, 16
    sw t2, 36(a2)
    slli t2, a7, 16
    sw t2, 40(a2)
    slli t2, t4, 16
    sw t2, 44(a2)
    sw t5, 0(a3)
    sw t0, 0(a4)
    li t2, 1
    sw t2, 0(a2)
    add t0, t0, t4
    la t1, __qick_wmem+48
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    sw a5, 4(a2)
    sw a6, 48(a2)
    slli t2, t3, 16
    sw t2, 52(a2)
    slli t2, a7, 16
    sw t2, 56(a2)
    slli t2, t4, 16
    sw t2, 60(a2)
    sw t5, 0(a3)
    sw t0, 0(a4)
    li t2, 2
    sw t2, 0(a2)
    la t1, __qick_wmem+0
    li t2, 1073741824
    add s2, s2, t2
    sw s2, 4(t1)
    la t1, __qick_wmem+24
    add s8, s8, t2
    sw s8, 4(t1)
    la t1, __qick_wmem+48
    lw a6, 4(t1)
    add a6, a6, t2
    sw a6, 4(t1)
    addi t0, s11, 100
    mv a5, s1
    mv a6, s2
    mv a7, s3
    mv t3, s4
    mv t4, s5
    mv t5, s6
    sw a5, 4(a2)
    sw a6, 16(a2)
    slli t2, t3, 16
    sw t2, 20(a2)
    slli t2, a7, 16
    sw t2, 24(a2)
    slli t2, t4, 16
    sw t2, 28(a2)
    sw t5, 0(a3)
    sw t0, 0(a4)
    sw x0, 0(a2)
    add t0, t0, t4
    la t1, __qick_wmem+24
    mv a5, s7
    mv a6, s8
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    sw a5, 4(a2)
    sw a6, 32(a2)
    slli t2, t3, 16
    sw t2, 36(a2)
    slli t2, a7, 16
    sw t2, 40(a2)
    slli t2, t4, 16
    sw t2, 44(a2)
    sw t5, 0(a3)
    sw t0, 0(a4)
    li t2, 1
    sw t2, 0(a2)
    add t0, t0, t4
    la t1, __qick_wmem+48
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    sw a5, 4(a2)
    sw a6, 48(a2)
    slli t2, t3, 16
    sw t2, 52(a2)
    slli t2, a7, 16
    sw t2, 56(a2)
    slli t2, t4, 16
    sw t2, 60(a2)
    sw t5, 0(a3)
    sw t0, 0(a4)
    li t2, 2
    sw t2, 0(a2)
    addi t0, s11, 200
    mv a5, s1
    mv a6, s2
    mv a7, s3
    mv t3, s4
    mv t4, s5
    mv t5, s6
    sw a5, 4(a2)
    sw a6, 16(a2)
    slli t2, t3, 16
    sw t2, 20(a2)
    slli t2, a7, 16
    sw t2, 24(a2)
    slli t2, t4, 16
    sw t2, 28(a2)
    sw t5, 0(a3)
    sw t0, 0(a4)
    sw x0, 0(a2)
    add t0, t0, t4
    la t1, __qick_wmem+24
    mv a5, s7
    mv a6, s8
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    sw a5, 4(a2)
    sw a6, 32(a2)
    slli t2, t3, 16
    sw t2, 36(a2)
    slli t2, a7, 16
    sw t2, 40(a2)
    slli t2, t4, 16
    sw t2, 44(a2)
    sw t5, 0(a3)
    sw t0, 0(a4)
    li t2, 1
    sw t2, 0(a2)
    add t0, t0, t4
    la t1, __qick_wmem+48
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    sw a5, 4(a2)
    sw a6, 48(a2)
    slli t2, t3, 16
    sw t2, 52(a2)
    slli t2, a7, 16
    sw t2, 56(a2)
    slli t2, t4, 16
    sw t2, 60(a2)
    sw t5, 0(a3)
    sw t0, 0(a4)
    li t2, 2
    sw t2, 0(a2)
    la t1, __qick_wmem+0
    li t2, 1073741824
    add s2, s2, t2
    sw s2, 4(t1)
    la t1, __qick_wmem+24
    add s8, s8, t2
    sw s8, 4(t1)
    la t1, __qick_wmem+48
    lw a6, 4(t1)
    add a6, a6, t2
    sw a6, 4(t1)
    addi t0, s11, 300
    mv a5, s1
    mv a6, s2
    mv a7, s3
    mv t3, s4
    mv t4, s5
    mv t5, s6
    sw a5, 4(a2)
    sw a6, 16(a2)
    slli t2, t3, 16
    sw t2, 20(a2)
    slli t2, a7, 16
    sw t2, 24(a2)
    slli t2, t4, 16
    sw t2, 28(a2)
    sw t5, 0(a3)
    sw t0, 0(a4)
    sw x0, 0(a2)
    add t0, t0, t4
    la t1, __qick_wmem+24
    mv a5, s7
    mv a6, s8
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    sw a5, 4(a2)
    sw a6, 32(a2)
    slli t2, t3, 16
    sw t2, 36(a2)
    slli t2, a7, 16
    sw t2, 40(a2)
    slli t2, t4, 16
    sw t2, 44(a2)
    sw t5, 0(a3)
    sw t0, 0(a4)
    li t2, 1
    sw t2, 0(a2)
    add t0, t0, t4
    la t1, __qick_wmem+48
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    sw a5, 4(a2)
    sw a6, 48(a2)
    slli t2, t3, 16
    sw t2, 52(a2)
    slli t2, a7, 16
    sw t2, 56(a2)
    slli t2, t4, 16
    sw t2, 60(a2)
    sw t5, 0(a3)
    sw t0, 0(a4)
    li t2, 2
    sw t2, 0(a2)
    addi t0, s11, 449
    li t1, RQ_CTRL_TIME_CMP
    sw t0, 0(t1)
    lw x0, 8(t1)
    addi s11, s11, 699
    addi s9, s9, 1
    la t0, __qick_ext+0
    sw s9, 0(t0)
    addi s0, s0, 1
    li t0, 2
    blt s0, t0, reps
    j __qick_exit
virt_z:
    la t1, __qick_wmem+0
    li t2, 1073741824
    add s2, s2, t2
    sw s2, 4(t1)
    la t1, __qick_wmem+24
    add s8, s8, t2
    sw s8, 4(t1)
    la t1, __qick_wmem+48
    lw a5, 0(t1)
    lw a6, 4(t1)
    lw a7, 8(t1)
    lw t3, 12(t1)
    lw t4, 16(t1)
    lw t5, 20(t1)
    add a6, a6, t2
    sw a6, 4(t1)
    ret
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
.word 25    # myflattop_w0.length
.word 8    # myflattop_w0.conf
.word 268435392    # myflattop_w1.freq
.word 0    # myflattop_w1.phase
.word 0    # myflattop_w1.env
.word 16383    # myflattop_w1.gain
.word 25    # myflattop_w1.length
.word 9    # myflattop_w1.conf
.word 268435392    # myflattop_w2.freq
.word 0    # myflattop_w2.phase
.word 25    # myflattop_w2.env
.word 32766    # myflattop_w2.gain
.word 25    # myflattop_w2.length
.word 8    # myflattop_w2.conf
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
