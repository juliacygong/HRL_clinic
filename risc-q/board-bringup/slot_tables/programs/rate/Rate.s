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
        li s5, RQ_CTRL_TIME_CMP
        la s6, __qick_ext+0
        li s7, 1
        la s1, __qick_ext+0
        lw s1, 0(s1)
    li t1, RF_CH0
    sw x0, 12(t1)
# slot 0 of gen 0 <- a_w0
    li a5, 53687040
    li a6, 0
    li a7, 0
    li t3, 32766
    li t4, 3
    li t5, 9
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
# slot 1 of gen 0 <- b_w0
    li t3, 13106
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
    li t1, RQ_CTRL_TIME
    lw s11, 0(t1)
    la t0, __qick_ext+0
    sw x0, 0(t0)
    mv s1, x0
    la t1, __qick_wmem+120
    lw a5, 0(t1)
    lw a6, 4(t1)
    li t1, RF_CH2
    sw a5, 4(t1)
    sw a6, 12(t1)
    li t2, 65536000    # PATCH readout window: RF_CH2 slot 0 dur = 1000 cycles (2.0 us)
    sw t2, 28(t1)
    addi s11, s11, 5
    li s0, 0
reps:
    addi t0, s11, 0
    sw t0, 0(s2)
    sw x0, 0(s3)
    sw t0, 0(s4)
    addi t0, s11, 3
    sw t0, 4(s4)
    addi t0, s11, 6
    sw t0, 0(s4)
    addi t0, s11, 9
    sw t0, 4(s4)
    addi t0, s11, 12
    sw t0, 0(s4)
    addi t0, s11, 15
    sw t0, 4(s4)
    addi t0, s11, 18
    sw t0, 0(s4)
    addi t0, s11, 21
    sw t0, 4(s4)
    addi t0, s11, 24
    sw t0, 0(s4)
    addi t0, s11, 27
    sw t0, 4(s4)
    addi t0, s11, 30
    sw t0, 0(s4)
    addi t0, s11, 33
    sw t0, 4(s4)
    addi t0, s11, 36
    sw t0, 0(s4)
    addi t0, s11, 39
    sw t0, 4(s4)
    addi t0, s11, 42
    sw t0, 0(s4)
    addi t0, s11, 45
    sw t0, 4(s4)
    addi t0, s11, 48
    sw t0, 0(s4)
    addi t0, s11, 51
    sw t0, 4(s4)
    addi t0, s11, 54
    sw t0, 0(s4)
    addi t0, s11, 57
    sw t0, 4(s4)
    addi t0, s11, 60
    sw t0, 0(s4)
    addi t0, s11, 63
    sw t0, 4(s4)
    addi t0, s11, 66
    sw t0, 0(s4)
    addi t0, s11, 69
    sw t0, 4(s4)
    addi t0, s11, 72
    sw t0, 0(s4)
    addi t0, s11, 75
    sw t0, 4(s4)
    addi t0, s11, 78
    sw t0, 0(s4)
    addi t0, s11, 81
    sw t0, 4(s4)
    addi t0, s11, 84
    sw t0, 0(s4)
    addi t0, s11, 87
    sw t0, 4(s4)
    addi t0, s11, 90
    sw t0, 0(s4)
    addi t0, s11, 93
    sw t0, 4(s4)
    addi t0, s11, 96
    sw t0, 0(s4)
    addi t0, s11, 99
    sw t0, 4(s4)
    addi t0, s11, 102
    sw t0, 0(s4)
    addi t0, s11, 105
    sw t0, 4(s4)
    addi t0, s11, 108
    sw t0, 0(s4)
    addi t0, s11, 111
    sw t0, 4(s4)
    addi t0, s11, 114
    sw t0, 0(s4)
    addi t0, s11, 117
    sw t0, 4(s4)
    addi t0, s11, 999
    sw t0, 0(s5)
    addi s11, s11, 999
    addi s1, s1, 1
    sw s1, 0(s6)
    addi s0, s0, 1
    lw x0, 8(s5)
    blt s0, s7, reps
    j __qick_exit
virt_z:
    la t1, __qick_wmem+48
    lw a6, 4(t1)
    li t2, 1073741824
    add a6, a6, t2
    sw a6, 4(t1)
    la t1, __qick_wmem+72
    lw a6, 4(t1)
    add a6, a6, t2
    sw a6, 4(t1)
    la t1, __qick_wmem+96
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
.word 53687040    # a_w0.freq
.word 0    # a_w0.phase
.word 0    # a_w0.env
.word 32766    # a_w0.gain
.word 3    # a_w0.length
.word 9    # a_w0.conf
.word 53687040    # b_w0.freq
.word 0    # b_w0.phase
.word 0    # b_w0.env
.word 13106    # b_w0.gain
.word 3    # b_w0.length
.word 9    # b_w0.conf
.word 53687040    # ft_w0.freq
.word 0    # ft_w0.phase
.word 0    # ft_w0.env
.word 32766    # ft_w0.gain
.word 3    # ft_w0.length
.word 8    # ft_w0.conf
.word 53687040    # ft_w1.freq
.word 0    # ft_w1.phase
.word 0    # ft_w1.env
.word 16383    # ft_w1.gain
.word 6    # ft_w1.length
.word 9    # ft_w1.conf
.word 53687040    # ft_w2.freq
.word 0    # ft_w2.phase
.word 3    # ft_w2.env
.word 32766    # ft_w2.gain
.word 3    # ft_w2.length
.word 8    # ft_w2.conf
.word -174762500    # ro_w0.freq
.word 0    # ro_w0.phase
.word 0    # ro_w0.env
.word 0    # ro_w0.gain
.word 3    # ro_w0.length
.word 8    # ro_w0.conf
.type __qick_ext, @object
.size __qick_ext, 8
__qick_ext:
.space 8
.type __qick_dmem, @object
.size __qick_dmem, 1024
__qick_dmem:
.space 1024
