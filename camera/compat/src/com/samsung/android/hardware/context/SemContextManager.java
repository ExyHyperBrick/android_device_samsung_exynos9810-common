// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.hardware.context;

import org.lineageos.camera.compat.OptionalSamsungServices;

/** Keep the camera's existing Android OrientationEventListener fallback active. */
public class SemContextManager {
    public boolean isAvailableService(int service) {
        OptionalSamsungServices.unavailable("Samsung context service " + service);
        return false;
    }

    public boolean registerListener(SemContextListener listener, int service) {
        OptionalSamsungServices.unavailable("Samsung context listener " + service);
        return false;
    }

    public void unregisterListener(SemContextListener listener, int service) {
        // Nothing was registered with a Samsung service.
    }
}
