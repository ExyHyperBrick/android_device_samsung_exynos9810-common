/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package com.samsung.android.media.heif;

import com.samsung.android.os.PortDiagnostics;
import java.nio.ByteBuffer;

/** No input buffer is accepted for the absent proprietary HEIF converter. */
public final class SemInputImage {
    public SemInputImage(ByteBuffer pixels, int width, int height, int format) {
        throw PortDiagnostics.unsupported("Samsung HEIF conversion");
    }
    public void setRotationDegree(int rotation) {
        throw PortDiagnostics.unsupported("Samsung HEIF conversion");
    }
    public void setSliceHeight(int height) {
        throw PortDiagnostics.unsupported("Samsung HEIF conversion");
    }
    public void setStride(int stride) {
        throw PortDiagnostics.unsupported("Samsung HEIF conversion");
    }
}
