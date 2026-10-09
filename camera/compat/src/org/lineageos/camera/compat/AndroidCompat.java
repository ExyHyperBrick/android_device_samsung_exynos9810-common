/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.camera.compat;

import android.app.Activity;
import android.app.StatusBarManager;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothHeadset;
import android.content.pm.FeatureInfo;
import android.content.pm.PackageManager;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.CaptureResult;
import android.hardware.camera2.params.OutputConfiguration;
import android.hardware.camera2.utils.TypeReference;
import android.hardware.display.DisplayManager;
import android.hardware.display.WifiDisplayStatus;
import android.media.AudioAttributes;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioRecordingConfiguration;
import android.media.AudioSystem;
import android.media.MediaExtractor;
import android.media.MediaMetadataRetriever;
import android.media.MediaRecorder;
import android.media.MediaRouter;
import android.net.ConnectivityManager;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.os.SystemProperties;
import android.os.UserHandle;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.telephony.PhoneStateListener;
import android.telephony.TelephonyManager;
import android.util.Log;
import android.view.Surface;
import android.view.View;
import android.view.accessibility.AccessibilityManager;
import android.widget.TextView;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Type;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.WeakHashMap;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/** App-local adapters for the Android Samsung extension calls in G960F Camera. */
public final class AndroidCompat {
    private static final String TAG = "SamsungCameraCompat";
    private static final int SAMSUNG_HAPTIC_BASE = 50024;
    private static final Set<String> sReported = Collections.newSetFromMap(
            new ConcurrentHashMap<String, Boolean>());
    private static final Map<PhoneStateListener, Integer> sListenerSubscriptions =
            Collections.synchronizedMap(new WeakHashMap<PhoneStateListener, Integer>());

    // Preserve the stock enum names and ordinal order for embedded references.
    // Vibration intensity remains under Android's own policy and user settings.
    public enum SemMagnitudeType {
        TYPE_TOUCH, TYPE_NOTIFICATION, TYPE_CALL, TYPE_MAX, TYPE_MIN,
        TYPE_EXTRA, TYPE_FORCE
    }
    public enum SemMagnitudeTypes {
        TYPE_TOUCH, TYPE_NOTIFICATION, TYPE_CALL, TYPE_MAX, TYPE_MIN,
        TYPE_EXTRA, TYPE_FORCE
    }

    private AndroidCompat() {}

    private static void unsupported(String operation) {
        if (sReported.add(operation)) {
            Log.w(TAG, operation + ": Samsung extension unavailable; "
                    + "using the basic Android path");
        }
    }

    private static void denied(String operation, RuntimeException exception) {
        if (sReported.add(operation + ":denied")) {
            Log.w(TAG, operation + ": Android denied the optional operation ("
                    + exception.getClass().getSimpleName() + ")");
        }
    }

    // These module APIs exist in AOSP, but their implementation libraries do
    // not expose a compile dependency to device projects. Reflection avoids
    // importing hidden module classes or changing global hidden-API policy.
    private static Object invokeModuleApi(Object receiver, String name,
            Class<?>[] parameters, Object... arguments) {
        if (receiver == null) return null;
        try {
            return receiver.getClass().getMethod(name, parameters)
                    .invoke(receiver, arguments);
        } catch (InvocationTargetException exception) {
            Throwable cause = exception.getCause();
            if (cause instanceof RuntimeException) {
                denied(name, (RuntimeException) cause);
            } else {
                unsupported(name);
            }
        } catch (ReflectiveOperationException | SecurityException exception) {
            unsupported(name);
        }
        return null;
    }

    // Match stock KeyMaker without its system JAR. Keep the complete Type:
    // parameterized Range/Pair keys need their arguments for marshaling.
    // These constructors retain the default vendor ID used by stock too.
    public static CameraCharacteristics.Key<?> createCameraCharacteristicsKey(
            String name, Type type) {
        return new CameraCharacteristics.Key<>(name,
                TypeReference.createSpecializedTypeReference(type));
    }

    public static CaptureRequest.Key<?> createCaptureRequestKey(
            String name, Type type) {
        return new CaptureRequest.Key<>(name,
                TypeReference.createSpecializedTypeReference(type));
    }

    public static CaptureResult.Key<?> createCaptureResultKey(
            String name, Type type) {
        return new CaptureResult.Key<>(name,
                TypeReference.createSpecializedTypeReference(type));
    }

    public static boolean hasSamsungStreamOptions() {
        try {
            OutputConfiguration.class.getConstructor(int.class, Surface.class,
                    int.class, int.class);
            return true;
        } catch (NoSuchMethodException | SecurityException exception) {
            return false;
        }
    }

    public static void collapsePanels(StatusBarManager manager) {
        if (manager == null) return;
        try {
            manager.collapsePanels();
        } catch (SecurityException exception) {
            denied("collapsePanels", exception);
        }
    }

    public static int semGetHeadsetSetting(BluetoothHeadset headset,
            BluetoothDevice device, int setting) {
        // Stock setting 100 is the headset's voice-recognition capability.
        // An unknown capability must not enable the Camera Bluetooth mic path.
        if (setting != 100) {
            unsupported("semGetHeadsetSetting");
            return 0;
        }
        if (headset == null || device == null) return 0;
        return Boolean.TRUE.equals(invokeModuleApi(headset,
                "isVoiceRecognitionSupported", new Class<?>[]{BluetoothDevice.class},
                device)) ? 1 : 0;
    }

    public static BluetoothDevice semGetHighPriorityDevice(
            BluetoothHeadset headset) {
        Object device = invokeModuleApi(headset, "getActiveDevice", new Class<?>[0]);
        return device instanceof BluetoothDevice ? (BluetoothDevice) device : null;
    }

    public static int semGetSystemFeatureLevel(PackageManager manager,
            String feature) {
        if (manager == null || feature == null) return 0;
        FeatureInfo[] features = manager.getSystemAvailableFeatures();
        if (features == null) return 0;
        for (FeatureInfo info : features) {
            if (info != null && feature.equals(info.name)) return info.version;
        }
        return 0;
    }

    public static WifiDisplayStatus semGetWifiDisplayStatus(
            DisplayManager manager) {
        return manager == null ? new WifiDisplayStatus()
                : manager.getWifiDisplayStatus();
    }

    public static int getActiveDisplayState(WifiDisplayStatus status) {
        return status == null ? WifiDisplayStatus.DISPLAY_STATE_NOT_CONNECTED
                : status.getActiveDisplayState();
    }

    public static int getConnectedState(WifiDisplayStatus status) {
        // Samsung's extended connection mode has no AOSP counterpart. The
        // Camera excludes extended mode 3; ordinary AOSP mirroring is mode 0.
        return 0;
    }

    public static AudioAttributes.Builder semAddAudioTag(
            AudioAttributes.Builder builder, String tag) {
        return builder.addTag(tag);
    }

    public static float semGetSituationVolume(AudioManager manager,
            int situation, int device) {
        if (manager == null) return 0.0f;
        if (situation >= 1 && situation <= 16 && device >= 0 && device <= 2) {
            try {
                // This is the exact stock framework query. The Samsung audio
                // HAL can still answer it through the ordinary Android API.
                String reply = manager.getParameters("g_volume_situation_key;type="
                        + situation + ";device=" + device);
                float volume = Float.parseFloat(reply);
                if (Float.isFinite(volume) && volume >= 0.0f && volume <= 1.0f) {
                    return volume;
                }
            } catch (IllegalArgumentException | NullPointerException exception) {
                unsupported("Samsung situation-volume HAL query");
            }
        }
        // AOSP has no situation table. Derive linear gain from the real system
        // volume curve rather than reporting fabricated full-volume success.
        int index = manager.getStreamVolume(AudioManager.STREAM_SYSTEM);
        float db = manager.getStreamVolumeDb(AudioManager.STREAM_SYSTEM, index,
                AudioDeviceInfo.TYPE_BUILTIN_SPEAKER);
        return Float.isFinite(db) ? (float) Math.pow(10.0, db / 20.0) : 0.0f;
    }

    public static int semGetStreamType(int samsungStream) {
        switch (samsungStream) {
            case 1: return AudioManager.STREAM_MUSIC;
            case 2: return AudioManager.STREAM_VOICE_CALL;
            case 4: return AudioManager.STREAM_BLUETOOTH_SCO;
            case 5: return AudioManager.STREAM_SYSTEM_ENFORCED;
            case 3:
            case 6:
                unsupported("Samsung-specific audio stream");
                return AudioManager.STREAM_MUSIC;
            default: return -1;
        }
    }

    public static boolean semIsFmRadioActive(AudioManager manager) {
        // AOSP does not publish the Samsung FM player's activity. Samsung's
        // global audio-service query is unavailable in this port.
        unsupported("semIsFmRadioActive");
        return false;
    }

    public static boolean semIsRecordActive(AudioManager manager, int source) {
        if (source >= 0) return AudioSystem.isSourceActive(source);
        if (manager == null) return false;
        List<AudioRecordingConfiguration> recordings =
                manager.getActiveRecordingConfigurations();
        return recordings != null && !recordings.isEmpty();
    }

    public static AudioRecord.Builder semAllowConcurrentCapture(
            AudioRecord.Builder builder, boolean allow) {
        // Android's capture arbitration still applies; this flag cannot bypass
        // microphone privacy or another application's exclusive capture.
        return builder.setPrivacySensitive(!allow);
    }

    public static void semSetVideoSize(MediaMetadataRetriever retriever,
            int width, int height, boolean firstFlag, boolean secondFlag) {
        unsupported("Samsung metadata frame sizing/transform");
    }

    public static void semSetAuthor(MediaRecorder recorder, int author) {
        unsupported("Samsung recording author metadata");
    }

    public static void semSetDurationInterval(MediaRecorder recorder,
            int interval) {
        unsupported("Samsung recording duration notifications");
    }

    public static void semSetFileSizeInterval(MediaRecorder recorder,
            long interval, int flags) {
        unsupported("Samsung recording size notifications");
    }

    public static void semSetIframeInterval(MediaRecorder recorder,
            int interval) {
        unsupported("Samsung recording I-frame interval");
    }

    public static void semSetRecordingMode(MediaRecorder recorder, int mode) {
        // The basic recording path uses regular MediaRecorder configuration.
        // Camera feature policy must hide modes requiring Samsung's recorder.
        if (mode != 0 && mode != 1000) {
            unsupported("Samsung advanced recording mode");
        }
    }

    public static void semSetVideoFlip(MediaRecorder recorder, int mode) {
        // Do not pretend that ignoring this flag mirrors an encoded video.
        if (mode != 0) unsupported("Samsung recorded-video transform");
    }

    public static String semGetDeviceAddress(MediaRouter.RouteInfo route) {
        return route == null ? null : route.getDeviceAddress();
    }

    public static int semGetStatusCode(MediaRouter.RouteInfo route) {
        return route == null ? MediaRouter.RouteInfo.STATUS_NONE
                : route.getStatusCode();
    }

    public static boolean semIsNetworkSupported(ConnectivityManager manager,
            int type) {
        return Boolean.TRUE.equals(invokeModuleApi(manager, "isNetworkSupported",
                new Class<?>[]{Integer.TYPE}, type));
    }

    public static boolean semIsProductDev() {
        return Build.IS_DEBUGGABLE;
    }

    public static void semGoToSleep(PowerManager manager, long time) {
        if (manager == null) return;
        try {
            manager.goToSleep(time);
        } catch (SecurityException exception) {
            denied("semGoToSleep", exception);
        }
    }

    public static void semSetAutoBrightnessLimit(PowerManager manager,
            int lower, int upper) {
        // Keep Android's brightness policy. Do not change global settings to
        // emulate a proprietary per-application brightness limit.
        unsupported("Samsung automatic-brightness limits");
    }

    public static void semWakeUp(PowerManager manager, long time, int reason,
            String details) {
        if (manager == null) return;
        try {
            manager.wakeUp(time, PowerManager.WAKE_REASON_APPLICATION, details);
        } catch (SecurityException exception) {
            denied("semWakeUp", exception);
        }
    }

    public static String get(String key) {
        return SystemProperties.get(key);
    }

    public static String get(String key, String fallback) {
        return SystemProperties.get(key, fallback);
    }

    public static String getCountryCode() {
        return SystemProperties.get("ro.csc.country_code",
                Locale.getDefault().getCountry());
    }

    public static int semGetMyUserId() {
        return UserHandle.myUserId();
    }

    public static VibrationEffect semCreateWaveform(int pattern, int repeat,
            SemMagnitudeType magnitude) {
        unsupported("Samsung vibration pattern/intensity");
        // Camera only asks for one-shot touch feedback. Repeating Samsung
        // patterns are deliberately not reproduced by an indefinite vibration.
        return VibrationEffect.createPredefined(VibrationEffect.EFFECT_CLICK);
    }

    public static void semVibrate(Vibrator vibrator, int pattern, int repeat,
            AudioAttributes attributes, SemMagnitudeTypes magnitude) {
        if (vibrator == null || !vibrator.hasVibrator()) return;
        unsupported("Samsung vibration pattern/intensity");
        vibrator.vibrate(VibrationEffect.createPredefined(
                VibrationEffect.EFFECT_CLICK), attributes);
    }

    public static int semGetCallState(TelephonyManager manager, int subId) {
        return manager == null ? TelephonyManager.CALL_STATE_IDLE
                : manager.getCallState(subId);
    }

    public static boolean semIsVideoCall(TelephonyManager manager) {
        // There is no AOSP query for the current Samsung video-call session.
        // Regular call-state guards use the real telephony API above.
        unsupported("Samsung video-call classification");
        return false;
    }

    public static int semGetVibrationIndex(int index) {
        // The stock bridge adds 50024 before Vibrator pattern selection. Keep
        // that identifier local; the final vibration adapter uses AOSP effects.
        return SAMSUNG_HAPTIC_BASE + index;
    }

    public static void semSetRoundedCornerColor(View view, int corners,
            int color) {
        unsupported("Samsung rounded-corner decoration");
    }

    public static void semSetRoundedCorners(View view, int corners) {
        unsupported("Samsung rounded-corner decoration");
    }

    public static void semUpdateAssitantMenu(AccessibilityManager manager,
            Bundle options) {
        unsupported("Samsung Assistant Menu integration");
    }

    public static boolean semIsResumed(Activity activity) {
        return activity != null && activity.isResumed();
    }

    public static void semSetSubscriptionId(PhoneStateListener listener,
            int subscriptionId) {
        if (listener != null) sListenerSubscriptions.put(listener, subscriptionId);
    }

    public static void listen(TelephonyManager manager, PhoneStateListener listener,
            int events) {
        if (manager == null || listener == null) return;
        Integer subscriptionId = sListenerSubscriptions.get(listener);
        TelephonyManager subscription = subscriptionId == null ? manager
                : manager.createForSubscriptionId(subscriptionId);
        subscription.listen(listener, events);
        // Keep the weak association across unregister/re-register cycles. It
        // vanishes when Camera releases its listener and cannot retain Camera.
    }

    public static void semSetRunningMode(MediaExtractor extractor, int mode) {
        unsupported("Samsung media-extractor running mode");
    }

    public static void semSetButtonShapeEnabled(TextView view,
            boolean enabled) {
        unsupported("Samsung button-shape decoration");
    }
}
