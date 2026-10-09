/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package com.samsung.android.os;

import android.util.Log;
import java.util.Collections;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/** Diagnostics for optional Samsung services absent from the host platform. */
public final class PortDiagnostics {
    private static final Set<String> REPORTED = Collections.newSetFromMap(
            new ConcurrentHashMap<String, Boolean>());
    private PortDiagnostics() {}
    public static void unavailable(String feature) {
        if (REPORTED.add(feature)) {
            Log.w("SamsungCameraCompat", feature + ": optional Samsung service unavailable");
        }
    }
    public static UnsupportedOperationException unsupported(String feature) {
        unavailable(feature);
        return new UnsupportedOperationException(feature + " is unavailable in this port");
    }
}
