// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.feature;

/** CSC-only integrations are absent; retain the caller's documented defaults. */
public final class SemCscFeature {
    private static final SemCscFeature INSTANCE = new SemCscFeature();
    public static SemCscFeature getInstance() { return INSTANCE; }
    public boolean getBoolean(String key) { return false; }
    public boolean getBoolean(String key, boolean fallback) { return fallback; }
    public int getInt(String key, int fallback) { return fallback; }
    public String getString(String key) { return ""; }
}
