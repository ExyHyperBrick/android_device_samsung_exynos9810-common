// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.app;

import org.lineageos.camera.compat.OptionalSamsungServices;

public class SemMultiWindowManager {
    public SemMultiWindowManager() {}

    public int getMode() {
        OptionalSamsungServices.unavailable("Samsung multi-window mode");
        return 0;
    }
}
