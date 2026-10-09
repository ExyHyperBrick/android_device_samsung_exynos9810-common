/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package com.samsung.android.media.heif;

import com.samsung.android.os.PortDiagnostics;
import java.nio.ByteBuffer;

/** Preserve the stock interface shape without claiming an HEIF encoder. */
public interface SemHeifConverter extends AutoCloseable {
    void initialize();
    int convert(SemHeifConfig configuration, ByteBuffer output);
    void deinitialize();
    @Override default void close() { deinitialize(); }
    final class Factory {
        private Factory() {}
        public static SemHeifConverter create(int codec, int mode) {
            throw PortDiagnostics.unsupported("Samsung HEIF conversion");
        }
    }
}
