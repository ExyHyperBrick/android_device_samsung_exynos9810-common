// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.hardware.display;

import org.lineageos.camera.compat.OptionalSamsungServices;

public final class SemMdnieManager {
    public boolean setContentMode(int mode) {
        OptionalSamsungServices.unavailable("Samsung mDNIe content mode");
        return false;
    }
}
