// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.view;

import android.content.ComponentName;
import org.lineageos.camera.compat.OptionalSamsungServices;

public class SemWindowManager {
    private static final SemWindowManager INSTANCE = new SemWindowManager();

    private SemWindowManager() {}

    public static SemWindowManager getInstance() {
        return INSTANCE;
    }

    public boolean requestSystemKeyEvent(int keyCode, ComponentName component,
            boolean request) {
        OptionalSamsungServices.unavailable("Samsung system-key reservation");
        return false;
    }
}
