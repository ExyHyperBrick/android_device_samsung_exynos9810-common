// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.tsp;

import android.os.Bundle;
import android.view.View;
import org.lineageos.camera.compat.OptionalSamsungServices;

public final class SemTspStateManager {
    private SemTspStateManager() {}

    public static void setDeadZone(View view, Bundle deadZone) {
        OptionalSamsungServices.unavailable("Samsung touchscreen dead zones");
    }
}
