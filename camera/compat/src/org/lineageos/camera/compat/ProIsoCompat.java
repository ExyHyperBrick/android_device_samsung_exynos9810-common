/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.camera.compat;

import android.content.Context;
import android.content.res.Resources;
import android.hardware.camera2.CameraCharacteristics;
import android.util.Range;

/** ISO selector values for the public Exynos9810 manual exposure path. */
public final class ProIsoCompat {
    private static final int[] PUBLIC_VALUES = {
        0, 50, 64, 80, 100, 125, 160, 200,
        250, 320, 400, 500, 640, 800, 1000, 1250
    };

    private ProIsoCompat() {}

    public static Range<Integer> publicSensitivityRange(
            CameraCharacteristics characteristics) {
        if (characteristics == null) {
            return null;
        }
        Range<Integer> range = characteristics.get(
                CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE);
        if (range == null || range.getLower() <= 0) {
            return null;
        }
        return range;
    }

    public static int sensorSensitivity(int index, int stockValue) {
        if (index != 14 && index != 15) {
            return stockValue;
        }
        if (AndroidCompat.hasSamsungStreamOptions()) {
            return stockValue;
        }
        return PUBLIC_VALUES[index];
    }

    public static String[] isoLabels(Resources resources, int resourceId) {
        String[] labels = resources.getStringArray(resourceId);
        if (AndroidCompat.hasSamsungStreamOptions()) {
            return labels;
        }
        if (labels.length != 15
                || !"iso_value".equals(resources.getResourceEntryName(resourceId))) {
            throw new IllegalStateException("Unexpected Samsung ISO labels");
        }
        labels = labels.clone();
        labels[13] = Integer.toString(PUBLIC_VALUES[14]);
        labels[14] = Integer.toString(PUBLIC_VALUES[15]);
        return labels;
    }

    public static String isoTitle(Context context, int resourceId) {
        return translateTitle(context.getString(resourceId),
                context.getResources(), resourceId);
    }

    public static String isoResourceString(Resources resources, int resourceId) {
        return translateTitle(resources.getString(resourceId),
                resources, resourceId);
    }

    private static String translateTitle(String title, Resources resources,
            int resourceId) {
        if (AndroidCompat.hasSamsungStreamOptions()) {
            return title;
        }
        String name = resources.getResourceEntryName(resourceId);
        if ("ISO_1600".equals(name)) {
            return Integer.toString(PUBLIC_VALUES[14]);
        }
        if ("ISO_3200".equals(name)) {
            return Integer.toString(PUBLIC_VALUES[15]);
        }
        return title;
    }

    /** Inclusive indices of representable values; null disables manual ISO. */
    public static int[] indexBounds(Range<Integer> range) {
        if (range == null || range.getLower() <= 0) {
            return null;
        }
        int first = 0;
        int last = 0;
        for (int index = 1; index < PUBLIC_VALUES.length; index++) {
            if (range.contains(PUBLIC_VALUES[index])) {
                if (first == 0) {
                    first = index;
                }
                last = index;
            }
        }
        return first == 0 ? null : new int[] { first, last };
    }
}
