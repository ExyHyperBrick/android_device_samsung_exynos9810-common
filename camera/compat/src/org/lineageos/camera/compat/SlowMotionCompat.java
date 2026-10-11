/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.camera.compat;

import android.os.Build;
import android.util.Log;

import java.util.HashMap;
import java.util.Map;

public final class SlowMotionCompat {
    private static final int PHOTO = 0;
    private static final int SLOW_MOTION = 11;

    private SlowMotionCompat() {}

    public static boolean isSupported() {
        // star2lte and crownlte require their matching native buffer fixes.
        return "starlte".equals(Build.DEVICE) || "star2lte".equals(Build.DEVICE)
                || "crownlte".equals(Build.DEVICE)
                || AndroidCompat.hasSamsungStreamOptions();
    }

    public static void applyFeatures(Map<String, HashMap<String, String>> features) {
        HashMap<String, String> mode = features.get("SHOOTING_MODE_SLOW_MOTION");
        if (mode == null) return;
        boolean supported = isSupported();
        mode.put("enable", Boolean.toString(supported));
        mode.put("back", supported ? "SLOW_MOTION" : "");
        mode.put("front", "");
    }

    public static int normalizeShootingMode(int mode) {
        if (mode == SLOW_MOTION && !isSupported()) {
            Log.w("StockCameraCompat", "Slow Motion is unavailable; use Photo");
            return PHOTO;
        }
        return mode;
    }
}
