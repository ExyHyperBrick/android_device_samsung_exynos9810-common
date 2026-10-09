// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.location;

import org.lineageos.camera.compat.OptionalSamsungServices;

public class SemLocationManager {
    public static final int ERROR_NOT_SUPPORTED = -7;

    public int requestLocationUpdates(boolean highAccuracy, SemLocationListener listener) {
        OptionalSamsungServices.unavailable("Samsung location updates");
        return ERROR_NOT_SUPPORTED;
    }

    public int removeLocationUpdates(SemLocationListener listener) {
        OptionalSamsungServices.unavailable("Samsung location updates");
        return ERROR_NOT_SUPPORTED;
    }
}
