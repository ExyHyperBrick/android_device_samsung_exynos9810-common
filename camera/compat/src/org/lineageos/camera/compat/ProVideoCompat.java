/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.camera.compat;

import android.util.Range;

/** Public Camera2 exposure limits for Samsung's rear Pro Video controls. */
public final class ProVideoCompat {
    private ProVideoCompat() {}

    public static long frameDuration(int fps) {
        if (fps <= 0 || fps > 240) {
            return 0;
        }
        return (1_000_000_000L + fps - 1) / fps;
    }

    public static Range<Long> exposureRange(Range<Long> physical, int fps) {
        long frame = frameDuration(fps);
        if (physical == null || physical.getLower() <= 0 || frame == 0) {
            return null;
        }
        long upper = Math.min(physical.getUpper(), frame);
        if (physical.getLower() > upper) {
            return null;
        }
        return upper == physical.getUpper()
                ? physical : new Range<>(physical.getLower(), upper);
    }

    /** ISO, exposure and frame duration for one atomic manual request. */
    public static long[] manualExposure(Range<Integer> sensitivity,
            Range<Long> physicalExposure, int iso, long exposure, int fps) {
        Range<Long> available = exposureRange(physicalExposure, fps);
        if (sensitivity == null || sensitivity.getLower() <= 0
                || available == null || iso <= 0 || exposure <= 0) {
            return null;
        }
        return new long[] { sensitivity.clamp(iso), available.clamp(exposure),
                frameDuration(fps) };
    }
}
