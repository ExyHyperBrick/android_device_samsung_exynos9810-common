// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.voip;

import org.lineageos.camera.compat.OptionalSamsungServices;

public class SemVoipInterfaceManager {
    public SemVoipInterfaceManager() {}

    public boolean isVoipIdle() {
        OptionalSamsungServices.unavailable("Samsung VoIP call-state service");
        // No Samsung VoIP service exists. This does not detect third-party calls.
        return true;
    }
}
