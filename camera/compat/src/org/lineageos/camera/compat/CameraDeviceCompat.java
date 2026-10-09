// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package org.lineageos.camera.compat;

import android.content.Context;
import android.graphics.ImageFormat;
import android.graphics.Rect;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.util.Log;
import android.util.Size;

/** Resolve the stock front-camera alias without changing logical settings. */
public final class CameraDeviceCompat {
    private static final String TAG = "StockCameraCompat";
    private static final int STOCK_DYNAMIC_FRONT_ID = 3;
    private static final int STANDARD_FRONT_ID = 1;

    private CameraDeviceCompat() {}

    // A confirmed physical front camera remains usable across provider restarts.
    private static boolean sStandardFrontValidated;
    private static boolean sProviderUnavailable;
    private static int sLastResolvedDeviceId = STOCK_DYNAMIC_FRONT_ID;

    public static synchronized int resolveFrontCameraDeviceId(
            Context context, int deviceId) {
        if (deviceId != STOCK_DYNAMIC_FRONT_ID || context == null) {
            return deviceId;
        }
        try {
            CameraManager manager = context.getSystemService(CameraManager.class);
            if (manager == null) return unavailableDeviceId(null);
            String[] ids = manager.getCameraIdList();
            if (contains(ids, Integer.toString(STOCK_DYNAMIC_FRONT_ID))) {
                sProviderUnavailable = false;
                return recordResolution(STOCK_DYNAMIC_FRONT_ID);
            }
            if (!contains(ids, Integer.toString(STANDARD_FRONT_ID))) {
                return unavailableDeviceId(null);
            }
            CameraCharacteristics characteristics =
                    manager.getCameraCharacteristics(Integer.toString(STANDARD_FRONT_ID));
            sStandardFrontValidated = isFrontPhotoCamera(characteristics);
            sProviderUnavailable = false;
            return recordResolution(sStandardFrontValidated
                    ? STANDARD_FRONT_ID : STOCK_DYNAMIC_FRONT_ID);
        } catch (CameraAccessException | RuntimeException e) {
            return unavailableDeviceId(e);
        }
    }

    /** Keep AOSP front-fallback coordinates within the opened physical camera. */
    public static synchronized Rect constrainFallbackActiveArray(
            String cameraId, Rect physical, Rect requested) {
        if (!sStandardFrontValidated || sLastResolvedDeviceId != STANDARD_FRONT_ID
                || !Integer.toString(STANDARD_FRONT_ID).equals(cameraId)
                || physical == null || physical.isEmpty()
                || requested == null || requested.isEmpty()
                || physical.contains(requested)
                || AndroidCompat.hasSamsungStreamOptions()) {
            return requested;
        }
        // Cached characteristics rectangles belong to the stock capability.
        // Bound a copy before stock zoom and metering calculations use it.
        Rect bounded = new Rect(requested);
        if (!bounded.intersect(physical)) {
            bounded.set(physical);
        }
        return bounded;
    }

    private static int unavailableDeviceId(Throwable error) {
        if (!sProviderUnavailable) {
            String message = sStandardFrontValidated
                    ? "Front provider unavailable; retain validated device 1"
                    : "Front provider unavailable; keep stock device 3";
            Log.w(TAG, message, error);
        }
        sProviderUnavailable = true;
        return recordResolution(sStandardFrontValidated
                ? STANDARD_FRONT_ID : STOCK_DYNAMIC_FRONT_ID);
    }

    private static int recordResolution(int resolvedDeviceId) {
        if (resolvedDeviceId != sLastResolvedDeviceId) {
            if (resolvedDeviceId == STANDARD_FRONT_ID) {
                Log.i(TAG, "Resolve unavailable stock front device 3"
                        + " to exposed front device 1");
            } else {
                Log.i(TAG, "Keep stock front device 3");
            }
            sLastResolvedDeviceId = resolvedDeviceId;
        }
        return resolvedDeviceId;
    }

    private static boolean contains(String[] ids, String requested) {
        if (ids == null) return false;
        for (String id : ids) {
            if (requested.equals(id)) return true;
        }
        return false;
    }

    private static boolean isFrontPhotoCamera(CameraCharacteristics characteristics) {
        if (characteristics == null) return false;
        Integer facing = characteristics.get(CameraCharacteristics.LENS_FACING);
        if (facing == null || facing != CameraCharacteristics.LENS_FACING_FRONT) {
            return false;
        }
        int[] capabilities = characteristics.get(
                CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES);
        boolean backwardsCompatible = false;
        if (capabilities != null) {
            for (int capability : capabilities) {
                if (capability == CameraCharacteristics
                        .REQUEST_AVAILABLE_CAPABILITIES_BACKWARD_COMPATIBLE) {
                    backwardsCompatible = true;
                    break;
                }
            }
        }
        if (!backwardsCompatible) return false;
        StreamConfigurationMap streams = characteristics.get(
                CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
        if (streams == null) return false;
        Size[] jpegSizes = streams.getOutputSizes(ImageFormat.JPEG);
        if (jpegSizes == null) return false;
        for (Size size : jpegSizes) {
            if (size != null && size.getWidth() > 0 && size.getHeight() > 0) {
                return true;
            }
        }
        return false;
    }

    /** Keep AOSP Pro exposure choices inside the opened sensor's public range. */
    public static android.util.Range<Long> constrainExposureTimeRange(
            android.util.Range<Long> physical, android.util.Range<Long> requested) {
        if (AndroidCompat.hasSamsungStreamOptions() || physical == null) {
            return requested;
        }
        if (requested == null || physical.contains(requested)) {
            return requested == null ? physical : requested;
        }
        long lower = Math.max(physical.getLower(), requested.getLower());
        long upper = Math.min(physical.getUpper(), requested.getUpper());
        if (lower > upper) {
            return physical;
        }
        return new android.util.Range<>(lower, upper);
    }

    /** The Samsung graphics effect PDK requires a separate modern ABI port. */
    public static boolean isSamsungEffectProcessorSupported() {
        return false;
    }

    public static void requireSamsungEffectProcessor() {
        if (!isSamsungEffectProcessorSupported()) {
            throw new IllegalStateException("Samsung graphics effect PDK is unavailable");
        }
    }

}
