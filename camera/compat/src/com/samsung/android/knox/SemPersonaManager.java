// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.knox;

import org.lineageos.camera.compat.OptionalSamsungServices;

public class SemPersonaManager {
    public int getCurrentContainerType() {
        OptionalSamsungServices.unavailable("Samsung Knox container classification");
        return 0;
    }

    public static boolean isKnoxId(int userId) {
        OptionalSamsungServices.unavailable("Samsung Knox user classification");
        return false;
    }
}
