/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package com.samsung.android.media.heif;

import com.samsung.android.os.PortDiagnostics;

/** HEIF support is hidden by Camera feature policy and fails closed here. */
public final class SemHeifConfig {
    public SemHeifConfig(SemInputImage image) {
        throw PortDiagnostics.unsupported("Samsung HEIF conversion");
    }
    public void setExifData(byte[] exif, int offset, int length) {
        throw PortDiagnostics.unsupported("Samsung HEIF conversion");
    }
    public void setThumbnailImage(SemInputImage image) {
        throw PortDiagnostics.unsupported("Samsung HEIF conversion");
    }
}
