/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.camera.compat;

import android.content.Context;
import android.graphics.ImageFormat;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.MediaRecorder;
import android.util.Log;
import android.util.Range;
import android.util.Size;
import android.util.SizeF;

import java.lang.reflect.Array;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

/** Separate, publicly exposed rear telephoto camera for Photo and ordinary Video. */
public final class TelephotoCompat {
    private static final String TAG = "StockCameraCompat";
    private static final int LOGICAL_TELE = 100;
    private static final String PHYSICAL_TELE = "50";
    private static final String RESOLUTION_CLASS =
            "com.sec.android.app.camera.interfaces.Resolution";
    private static boolean sAvailable;
    private static float sMagnification = 2f;
    // A separate process-local selection never overwrites the saved main-camera choice.
    private static int sVideoChoice = -1;
    private static StreamConfigurationMap sStreams;
    private static Range<Integer>[] sAeRanges;

    private TelephotoCompat() {}

    /** Run before Feature's static fields are read. An initial provider error hides the control. */
    public static synchronized void applyFeatures(Context context,
            Map<String, HashMap<String, String>> features) {
        sAvailable = false;
        sStreams = null;
        sAeRanges = null;
        String reason = "no-camera-manager";
        String[] cameraIds = null;
        Integer mainFacing = null;
        Integer teleFacing = null;
        float scale = Float.NaN;
        try {
            CameraManager manager = context == null ? null
                    : context.getSystemService(CameraManager.class);
            if (manager != null) {
                cameraIds = manager.getCameraIdList();
                reason = "camera-50-not-exposed";
                if (contains(cameraIds, PHYSICAL_TELE)) {
                    CameraCharacteristics main = manager.getCameraCharacteristics("0");
                    CameraCharacteristics tele = manager.getCameraCharacteristics(PHYSICAL_TELE);
                    mainFacing = main.get(CameraCharacteristics.LENS_FACING);
                    teleFacing = tele.get(CameraCharacteristics.LENS_FACING);
                    scale = magnification(main, tele);
                    StreamConfigurationMap streams = tele.get(
                            CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
                    if (!isRearPhotoCamera(main)) {
                        reason = "incompatible-main-photo-camera";
                    } else if (!isRearPhotoCamera(tele)) {
                        reason = "incompatible-tele-photo-camera";
                    } else if (!(scale >= 1.5f && scale <= 2.5f)) {
                        reason = "invalid-tele-magnification";
                    } else if (!supportsStockPhotoSizes(streams)) {
                        reason = "missing-stock-photo-sizes";
                    } else if (!hasSizes(streams, ImageFormat.PRIVATE)) {
                        reason = "missing-private-streams";
                    } else if (!hasSizes(streams, ImageFormat.YUV_420_888)) {
                        reason = "missing-yuv-streams";
                    } else {
                        sStreams = streams;
                        sAeRanges = tele.get(
                                CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES);
                        // Ordinary Video requires its validated fallback before opening.
                        sAvailable = isVideoSupported(1920, 1080, 30);
                        reason = sAvailable ? "ready" : "no-fhd30-video-fallback";
                        if (sAvailable) sMagnification = scale;
                    }
                }
            }
        } catch (CameraAccessException | RuntimeException e) {
            reason = "metadata-error";
            Log.w(TAG, "Telephoto metadata unavailable; use main rear camera", e);
        }
        Log.i(TAG, "Telephoto capability available=" + sAvailable
                + " reason=" + reason + " cameras=" + Arrays.toString(cameraIds)
                + " mainFacing=" + mainFacing + " teleFacing=" + teleFacing
                + " magnification=" + scale);
        put(features, "SUPPORT_BACK_TELE_CAMERA", Boolean.toString(sAvailable));
        put(features, "BACK_TELE_CAMERA_ID", sAvailable ? PHYSICAL_TELE : "-1");
        // Two physical cameras must be closed and opened separately, without fusion IDs 20/21.
        put(features, "SUPPORT_SEAMLESS_ZOOM", "false");
        put(features, "BACK_TELE_CAMERA_ZOOM_LEVEL", "2.0");
        if (sAvailable) Log.i(TAG, "Enable exposed rear telephoto device 50");
    }

    private static void put(Map<String, HashMap<String, String>> features,
            String name, String value) {
        HashMap<String, String> entry = new HashMap<>();
        entry.put("value", value);
        features.put(name, entry);
    }

    public static synchronized boolean isAvailableForMode(int mode) {
        return sAvailable && (mode == 0 || mode == 1);
    }

    /** CameraSettings uses 1 for rear and 0 for front, including logical tele 100. */
    public static synchronized boolean isAvailableForFacing(int cameraFacing, int mode) {
        return cameraFacing == 1 && isAvailableForMode(mode);
    }

    /** Log layout decisions, without logging the per-frame zoom calculations. */
    public static synchronized boolean isLensButtonAvailable(int cameraFacing, int mode) {
        boolean available = isAvailableForFacing(cameraFacing, mode);
        Log.i(TAG, "Telephoto lens buttons available=" + available
                + " facing=" + cameraFacing + " mode=" + mode
                + " capability=" + sAvailable);
        return available;
    }

    public static int normalizeCameraId(int id, int mode) {
        return id == LOGICAL_TELE && !isAvailableForMode(mode) ? 0 : id;
    }

    public static int normalizeLensType(int lens, int mode) {
        return lens == 2 && !isAvailableForMode(mode) ? 0 : lens;
    }

    /** Relative zoom remains 1x on the opened tele sensor; only the displayed scale changes. */
    public static synchronized int displayZoom(int relativeZoom, int logicalId) {
        return logicalId == LOGICAL_TELE && sAvailable
                ? Math.round(relativeZoom * sMagnification) : relativeZoom;
    }

    public static synchronized boolean isVideoSupported(int width, int height, int fps) {
        // This path uses public ordinary AE controls, not Samsung's vendor high-speed override.
        if (sStreams == null || fps <= 0 || fps > 30 || sAeRanges == null) return false;
        boolean aeSupports = false;
        for (Range<Integer> range : sAeRanges) {
            if (range != null && range.contains(fps)) aeSupports = true;
        }
        if (!aeSupports) return false;
        Size size = new Size(width, height);
        if (!contains(sStreams.getOutputSizes(ImageFormat.PRIVATE), size)
                || !contains(sStreams.getOutputSizes(MediaRecorder.class), size)) return false;
        long duration = sStreams.getOutputMinFrameDuration(MediaRecorder.class, size);
        return duration > 0 && duration <= (1_000_000_000L + fps - 1) / fps;
    }

    /** Return a copy so filtering tele choices never changes the cached main-camera list. */
    public static Object[] filterVideoResolutions(Object[] choices, int logicalId) {
        if (logicalId != LOGICAL_TELE || choices == null) return choices;
        ArrayList<Object> safe = new ArrayList<>();
        for (Object choice : choices) if (supportsResolution(choice)) safe.add(choice);
        Object[] filtered = (Object[]) Array.newInstance(
                choices.getClass().getComponentType(), safe.size());
        return safe.toArray(filtered);
    }

    /** Keep a saved main-camera choice intact while the tele camera uses a supported value. */
    public static int constrainVideoResolution(int logicalId, int requested) {
        if (logicalId != LOGICAL_TELE) return requested;
        return validatedResolution(sVideoChoice >= 0 ? sVideoChoice : requested);
    }

    public static synchronized int selectVideoResolution(int requested) {
        sVideoChoice = validatedResolution(requested);
        return sVideoChoice;
    }

    private static int validatedResolution(int requested) {
        try {
            Class<?> type = Class.forName(RESOLUTION_CLASS);
            try {
                Object resolution = type.getMethod("getResolution", int.class).invoke(null, requested);
                if (supportsResolution(resolution)) return requested;
            } catch (ReflectiveOperationException | RuntimeException ignored) {
                // Invalid old preference IDs also use the validated fallback below.
            }
            Object fallback = type.getField("RESOLUTION_1920X1080").get(null);
            if (supportsResolution(fallback)) return number(fallback, "getId");
        } catch (ReflectiveOperationException | RuntimeException e) {
            Log.e(TAG, "Cannot resolve a safe telephoto video setting", e);
        }
        // Initialization requires FHD30. Never pass an unsupported selection to a camera maker.
        throw new IllegalStateException("No validated telephoto video resolution");
    }

    private static boolean supportsResolution(Object resolution) {
        try {
            return resolution != null && isVideoSupported(number(resolution, "getWidth"),
                    number(resolution, "getHeight"), number(resolution, "getFps"));
        } catch (ReflectiveOperationException | RuntimeException e) {
            return false;
        }
    }

    private static int number(Object value, String method) throws ReflectiveOperationException {
        return (Integer) value.getClass().getMethod(method).invoke(value);
    }

    static float magnification(CameraCharacteristics main, CameraCharacteristics tele) {
        if (main == null || tele == null) return Float.NaN;
        SizeF mainSize = main.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE);
        SizeF teleSize = tele.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE);
        float[] mainFocal = main.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS);
        float[] teleFocal = tele.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS);
        if (mainSize == null || teleSize == null || mainFocal == null || teleFocal == null
                || mainFocal.length != 1 || teleFocal.length != 1
                || !positive(mainSize.getWidth()) || !positive(mainSize.getHeight())
                || !positive(teleSize.getWidth()) || !positive(teleSize.getHeight())
                || !positive(mainFocal[0]) || !positive(teleFocal[0])) return Float.NaN;
        float horizontal = (teleFocal[0] / teleSize.getWidth())
                / (mainFocal[0] / mainSize.getWidth());
        float vertical = (teleFocal[0] / teleSize.getHeight())
                / (mainFocal[0] / mainSize.getHeight());
        return positive(horizontal) && positive(vertical)
                && Math.abs(horizontal - vertical) < 0.15f ? horizontal : Float.NaN;
    }

    private static boolean positive(float value) {
        return Float.isFinite(value) && value > 0;
    }

    private static boolean isRearPhotoCamera(CameraCharacteristics camera) {
        if (camera == null) return false;
        Integer facing = camera.get(CameraCharacteristics.LENS_FACING);
        if (facing == null || facing != CameraCharacteristics.LENS_FACING_BACK) return false;
        boolean compatible = false;
        int[] capabilities = camera.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES);
        if (capabilities != null) {
            for (int capability : capabilities) {
                if (capability == CameraCharacteristics
                        .REQUEST_AVAILABLE_CAPABILITIES_BACKWARD_COMPATIBLE) compatible = true;
            }
        }
        return compatible && hasSizes(camera.get(
                CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP), ImageFormat.JPEG);
    }

    private static boolean supportsStockPhotoSizes(StreamConfigurationMap streams) {
        if (streams == null) return false;
        Size[] jpeg = streams.getOutputSizes(ImageFormat.JPEG);
        // These sizes are reused by the stock main-camera preference and Photo maker.
        for (Size required : new Size[] { new Size(4032, 3024), new Size(4032, 2268),
                new Size(4032, 1960), new Size(3024, 3024) }) {
            if (!contains(jpeg, required)) return false;
        }
        return true;
    }

    private static boolean hasSizes(StreamConfigurationMap streams, int format) {
        if (streams == null) return false;
        Size[] sizes = streams.getOutputSizes(format);
        if (sizes == null) return false;
        for (Size size : sizes) {
            if (size != null && size.getWidth() > 0 && size.getHeight() > 0) return true;
        }
        return false;
    }

    private static boolean contains(String[] ids, String id) {
        if (ids != null) for (String candidate : ids) if (id.equals(candidate)) return true;
        return false;
    }

    private static boolean contains(Size[] sizes, Size size) {
        if (sizes != null) for (Size candidate : sizes) if (size.equals(candidate)) return true;
        return false;
    }
}
