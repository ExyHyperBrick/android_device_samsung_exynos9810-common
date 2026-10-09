/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package com.samsung.android.camera.mic;

import com.samsung.android.os.PortDiagnostics;

/** The ordinary microphone path remains available without Samsung audio zoom. */
public final class SemMultiMicManager {
    private static final SemMultiMicManager INSTANCE = new SemMultiMicManager();
    private SemMultiMicManager() {}
    public static SemMultiMicManager getInstance() { return INSTANCE; }
    public static boolean isSupported() { return false; }
    public void initialize(int facing, int orientation, float zoom, float maximumZoom) {
        PortDiagnostics.unavailable("Samsung multi-microphone audio zoom");
    }
    public void release() {}
    public void setAudioZoomLevel(float zoom) {
        PortDiagnostics.unavailable("Samsung multi-microphone audio zoom");
    }
    public void setEnabled(boolean enabled) {
        if (enabled) PortDiagnostics.unavailable("Samsung multi-microphone audio zoom");
    }
    public boolean setMicSensitivity(int microphone, int sensitivity) { return false; }
    public boolean setMode(int mode) { return false; }
    public boolean setSoundLocation(int location) { return false; }
}
