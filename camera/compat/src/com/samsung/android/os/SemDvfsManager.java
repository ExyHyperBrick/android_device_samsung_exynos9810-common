/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package com.samsung.android.os;

import android.content.Context;

/** Inert optional boosts; Android's power and thermal policy remain active. */
public abstract class SemDvfsManager {
    private static final SemDvfsManager UNAVAILABLE = new SemDvfsManager() {};
    public static SemDvfsManager createInstance(Context context, int type) {
        PortDiagnostics.unavailable("Samsung DVFS boosts");
        return UNAVAILABLE;
    }
    public static SemDvfsManager createInstance(Context context, String name, int type) {
        return createInstance(context, type);
    }
    public int[] getSupportedFrequency() {
        // Camera checks only null before indexing element zero. An empty array
        // would crash; null is its explicit unsupported-frequency branch.
        return null;
    }
    public void setDvfsValue(int value) {}
    public void acquire() {}
    public void acquire(int duration) {}
    public void release() {}
}
