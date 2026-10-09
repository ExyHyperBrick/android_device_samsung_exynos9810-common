// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.desktopmode;

import org.lineageos.camera.compat.OptionalSamsungServices;

public final class SemDesktopModeManager {
    public SemDesktopModeState getDesktopModeState() {
        OptionalSamsungServices.unavailable("Samsung DeX service");
        return new SemDesktopModeState();
    }
}
