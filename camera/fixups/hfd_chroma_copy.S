/* SPDX-FileCopyrightText: 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
/*
 * Replace the copy loop at libhfd.so VA 0xa640 through 0xa665.
 * Input: r10 = interleaved source, r5 = plane byte count (r6 >> 1),
 *        r11 = first output plane, r8 = second output plane.
 * r4-r11, sp, lr and the following delete[](r10) are preserved.
 * The original NEON loop rounds each plane count up to sixteen.
 * This loop copies exactly r5 bytes to each plane.
 */
.syntax unified
.arch armv7-a
.thumb
.section .text.bounded_deinterleave,"ax",%progbits
.global bounded_deinterleave
.type bounded_deinterleave,%function
.thumb_func
bounded_deinterleave:
    movs r0, #0
    mov r1, r10
    mov r2, r8
    mov r3, r11
    cmp r0, r5
    bhs .Ldone
.Lcopy:
    ldrb r12, [r1], #1
    strb r12, [r3], #1
    ldrb r12, [r1], #1
    strb r12, [r2], #1
    adds r0, #1
    cmp r0, r5
    blo .Lcopy
    nop
    nop
.Ldone:
.size bounded_deinterleave, .-bounded_deinterleave
