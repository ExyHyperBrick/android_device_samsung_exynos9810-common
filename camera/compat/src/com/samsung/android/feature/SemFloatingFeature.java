// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.feature;

import android.util.Log;
import android.util.Xml;
import java.io.FileInputStream;
import java.util.HashMap;
import java.util.Map;
import org.xmlpull.v1.XmlPullParser;

/** Camera-local settings for the test port; no Samsung service is exported. */
public final class SemFloatingFeature {
    private static final String TAG = "StockCameraCompat";
    private static final SemFloatingFeature INSTANCE = new SemFloatingFeature();
    private final Map<String, String> values = new HashMap<>();

    private SemFloatingFeature() {
        try (FileInputStream in = new FileInputStream(
                "/system_ext/etc/camera/floating_feature.xml")) {
            XmlPullParser parser = Xml.newPullParser();
            parser.setInput(in, "UTF-8");
            int event;
            while ((event = parser.next()) != XmlPullParser.END_DOCUMENT) {
                if (event == XmlPullParser.START_TAG
                        && parser.getName().startsWith("SEC_FLOATING_FEATURE_")) {
                    values.put(parser.getName(), parser.nextText().trim());
                }
            }
            Log.i(TAG, "Loaded camera test features: " + values.size());
        } catch (Exception e) {
            Log.e(TAG, "Camera test features unavailable", e);
        }
    }
    public static SemFloatingFeature getInstance() { return INSTANCE; }
    public String getString(String key) { return getString(key, ""); }
    public String getString(String key, String fallback) {
        return values.getOrDefault(key, fallback);
    }
    public boolean getBoolean(String key) {
        return Boolean.parseBoolean(getString(key));
    }
    public int getInt(String key) {
        try { return Integer.parseInt(getString(key)); }
        catch (NumberFormatException e) { return -1; }
    }
}
