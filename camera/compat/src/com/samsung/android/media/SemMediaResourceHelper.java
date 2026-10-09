/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package com.samsung.android.media;

import com.samsung.android.os.PortDiagnostics;

/** No Samsung-specific video resource budget is advertised. */
public final class SemMediaResourceHelper {
    private SemMediaResourceHelper() {}
    public static SemMediaResourceHelper createInstance(int type, boolean excludeOwnEvents) {
        PortDiagnostics.unavailable("Samsung media resource accounting");
        return new SemMediaResourceHelper();
    }
    public int getRemainedVideoCapacity() { return 0; }
    public void release() {}
}
