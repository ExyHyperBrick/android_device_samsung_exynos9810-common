// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package org.lineageos.camera.compat;

import android.util.Log;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

/** Diagnostics for Samsung services that this camera test port cannot supply. */
public final class OptionalSamsungServices {
    private static final Set<String> REPORTED =
            Collections.synchronizedSet(new HashSet<String>());

    private OptionalSamsungServices() {}

    public static void unavailable(String feature) {
        if (REPORTED.add(feature)) {
            Log.w("SamsungCameraCompat", feature + " unavailable on this test port");
        }
    }
}
