/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package com.samsung.android.media.vidsol.simgp;

import com.samsung.android.os.PortDiagnostics;

/** Cleanup for optional Samsung image conversion; no converter is advertised. */
public final class ImgConverter {
    public ImgConverter() {
        PortDiagnostics.unavailable("Samsung image converter");
    }
    public void release() {}
}
