/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.soundbooster;

import android.content.Context;
import android.content.SharedPreferences;
import android.hardware.display.DisplayManager;
import android.media.AudioAttributes;
import android.media.AudioDeviceAttributes;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.media.AudioPlaybackConfiguration;
import android.media.audiofx.AudioEffect;
import android.os.Handler;
import android.util.Log;
import android.view.Display;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.Executor;

/** Independent, speaker-only controller for the Samsung speaker effect. */
final class SoundBooster {
    private static final String TAG = "Exynos9810SoundBooster";
    static final UUID UUID_EFFECT = UUID.fromString("50de45f0-5d4c-11e5-a837-0800200c9a66");
    private static final int PARAM_ROTATION = 1;
    private static final int MAX_ATTEMPTS = 3;
    private static final AudioAttributes MEDIA = new AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build();

    private final Context mContext;
    private final AudioManager mAudioManager;
    private final DisplayManager mDisplayManager;
    private final SharedPreferences mPreferences;
    private final Executor mWorker;
    private final Handler mMain;
    private final Runnable mChanged;
    private final AudioManager.OnDevicesForAttributesChangedListener mRouteListener =
            (attributes, devices) -> requestApply();
    private final AudioManager.AudioPlaybackCallback mPlaybackListener =
            new AudioManager.AudioPlaybackCallback() {
                @Override public void onPlaybackConfigChanged(
                        List<AudioPlaybackConfiguration> configurations) { requestApply(); }
            };
    private final DisplayManager.DisplayListener mDisplayListener =
            new DisplayManager.DisplayListener() {
                @Override public void onDisplayAdded(int id) { displayChanged(id); }
                @Override public void onDisplayRemoved(int id) { displayChanged(id); }
                @Override public void onDisplayChanged(int id) { displayChanged(id); }
            };

    // Main-thread state; native handles are exclusively accessed on the shared audio worker.
    private boolean mAvailable;
    private boolean mEnabled;
    private boolean mBlocked;
    private boolean mClosed;
    private boolean mRouteRegistered;
    private boolean mPlaybackRegistered;
    private boolean mDisplayRegistered;
    private volatile boolean mServerAlive = true;
    private boolean mServerAllowed = true;
    private volatile long mGeneration;
    private volatile long mDiscoveryGeneration;
    private boolean mDiscoveryRunning;
    private volatile long mHandleToken;
    private AudioEffect mEffect;
    private int mAppliedRotation = -1;
    private int mStatus = R.string.soundbooster_starting;
    private String mDetails = "Effect discovery pending";

    SoundBooster(Context context, AudioManager audioManager, SharedPreferences preferences,
            Executor worker, Handler main, Runnable changed) {
        mContext = context;
        mAudioManager = audioManager;
        mDisplayManager = context.getSystemService(DisplayManager.class);
        mPreferences = preferences;
        mWorker = worker;
        mMain = main;
        mChanged = changed;
        mEnabled = preferences.getBoolean("soundbooster_enabled", true);
    }

    void start() {
        if (mClosed || mDiscoveryRunning || !mServerAlive) return;
        mDiscoveryRunning = true;
        discover(++mDiscoveryGeneration, 1);
    }

    private void discover(long generation, int attempt) {
        mWorker.execute(() -> {
            boolean found = false;
            try {
                AudioEffect.Descriptor[] descriptors = AudioEffect.queryEffects();
                if (descriptors == null) throw new IllegalStateException("Effect list unavailable");
                for (AudioEffect.Descriptor descriptor : descriptors) {
                    if (UUID_EFFECT.equals(descriptor.uuid)) found = true;
                }
            } catch (RuntimeException e) {
                Log.w(TAG, "Effect discovery failed", e);
            }
            final boolean available = found;
            final boolean retry = !found && attempt < MAX_ATTEMPTS;
            mContext.getMainExecutor().execute(() -> {
                if (mClosed || generation != mDiscoveryGeneration) return;
                if (retry) {
                    mMain.postDelayed(() -> {
                        if (!mClosed && generation == mDiscoveryGeneration) {
                            discover(generation, attempt + 1);
                        }
                    }, attempt * 1000L);
                    return;
                }
                mDiscoveryRunning = false;
                mAvailable = available;
                if (available) requestApply();
                else {
                    mStatus = R.string.soundbooster_unavailable;
                    mDetails = "SoundBooster effect not registered";
                    mChanged.run();
                }
            });
        });
    }

    boolean isAvailable() { return mAvailable; }
    boolean isEnabled() { return mEnabled; }
    int getStatus() { return mStatus; }

    void setEnabled(boolean enabled) {
        if (!mAvailable || mClosed) return;
        mEnabled = enabled;
        mPreferences.edit().putBoolean("soundbooster_enabled", enabled).apply();
        retry();
    }

    void retry() {
        mBlocked = false;
        if (!mAvailable) start();
        else requestApply();
    }

    void onAudioServerState(boolean alive, boolean allowed) {
        mServerAlive = alive;
        mServerAllowed = allowed;
        if (!alive) {
            ++mDiscoveryGeneration;
            mDiscoveryRunning = false;
        }
        if (alive && !mAvailable) start();
        requestApply();
    }

    private void displayChanged(int id) {
        if (id == Display.DEFAULT_DISPLAY) requestApply();
    }

    private void registerMonitoring() {
        if (!mRouteRegistered) {
            mAudioManager.addOnDevicesForAttributesChangedListener(
                    MEDIA, mContext.getMainExecutor(), mRouteListener);
            mRouteRegistered = true;
        }
        if (!mPlaybackRegistered) {
            mAudioManager.registerAudioPlaybackCallback(mPlaybackListener, mMain);
            mPlaybackRegistered = true;
        }
        if (!mDisplayRegistered && mDisplayManager != null) {
            mDisplayManager.registerDisplayListener(mDisplayListener, mMain);
            mDisplayRegistered = true;
        }
    }

    private static boolean speakerOnly(List<AudioDeviceAttributes> devices) {
        if (devices == null || devices.isEmpty()) return false;
        for (AudioDeviceAttributes device : devices) {
            if (device == null || device.getRole() != AudioDeviceAttributes.ROLE_OUTPUT) return false;
            int type = device.getType();
            if (type != AudioDeviceInfo.TYPE_BUILTIN_SPEAKER
                    && type != AudioDeviceInfo.TYPE_BUILTIN_SPEAKER_SAFE) return false;
        }
        return true;
    }

    void requestApply() {
        if (!mAvailable || mClosed) return;
        final long generation = ++mGeneration;
        boolean allowed = false;
        int rotation = 0;
        int status = R.string.soundbooster_unavailable;
        String details = "Audio server unavailable or automatic recovery suspended";
        try {
            registerMonitoring();
            if (!mEnabled) {
                status = R.string.soundbooster_off;
                details = "Disabled by user";
            } else if (mServerAlive && mServerAllowed && !mBlocked) {
                status = R.string.soundbooster_paused;
                details = "Waiting for speaker-only playback in normal audio mode";
                allowed = mAudioManager.getMode() == AudioManager.MODE_NORMAL
                        && speakerOnly(mAudioManager.getDevicesForAttributes(MEDIA));
                // Connected hardware is not a route. Check selected policy routes, including
                // active streams that may use a different output from media.
                for (AudioPlaybackConfiguration configuration :
                        mAudioManager.getActivePlaybackConfigurations()) {
                    if (!configuration.isActive()) continue;
                    AudioAttributes attributes = configuration.getAudioAttributes();
                    int usage = attributes.getUsage();
                    if (usage == AudioAttributes.USAGE_VOICE_COMMUNICATION
                            || usage == AudioAttributes.USAGE_VOICE_COMMUNICATION_SIGNALLING
                            || !speakerOnly(mAudioManager.getDevicesForAttributes(attributes))) {
                        allowed = false;
                        break;
                    }
                }
                Display display = mDisplayManager == null ? null
                        : mDisplayManager.getDisplay(Display.DEFAULT_DISPLAY);
                if (display != null) rotation = display.getRotation();
            }
        } catch (RuntimeException e) {
            allowed = false;
            status = R.string.soundbooster_unavailable;
            details = e.toString();
            Log.w(TAG, "Cannot determine speaker route", e);
        }
        final boolean canProcess = allowed;
        final int angle = rotation;
        final int idleStatus = status;
        final String idleDetails = details;
        mStatus = R.string.soundbooster_starting;
        mChanged.run();
        mWorker.execute(() -> applyOnWorker(generation, canProcess, angle, idleStatus,
                idleDetails, 1));
    }

    private void current(long generation) {
        if (generation != mGeneration) throw new Superseded();
    }

    private static final class Superseded extends RuntimeException {
        private static final long serialVersionUID = 1L;
    }

    private void applyOnWorker(long generation, boolean allowed, int rotation, int idleStatus,
            String idleDetails, int attempt) {
        if (generation != mGeneration) return;
        int status = idleStatus;
        String details = idleDetails;
        boolean failed = false;
        boolean retryable = true;
        try {
            if (!allowed) {
                releaseOnWorker();
            } else {
                if (mEffect == null) {
                    mEffect = new AudioEffect(AudioEffect.EFFECT_TYPE_NULL, UUID_EFFECT, 0, 0);
                    final long token = ++mHandleToken;
                    mEffect.setControlStatusListener((effect, control) -> {
                        if (!control) mContext.getMainExecutor().execute(() -> {
                            if (!mClosed && token == mHandleToken) {
                                mBlocked = true;
                                requestApply();
                            }
                        });
                    });
                }
                current(generation);
                if (!mEffect.hasControl()) {
                    retryable = false;
                    throw new IllegalStateException("Another client owns speaker tuning");
                }
                if (rotation != mAppliedRotation) {
                    // Native code maps Surface rotation to Samsung's orientation convention.
                    int result = mEffect.setParameter(PARAM_ROTATION, rotation);
                    if (result != AudioEffect.SUCCESS) {
                        throw new IllegalStateException("Cannot set speaker rotation: " + result);
                    }
                    mAppliedRotation = rotation;
                }
                current(generation);
                if (!mEffect.getEnabled()) {
                    int result = mEffect.setEnabled(true);
                    if (result != AudioEffect.SUCCESS || !mEffect.getEnabled()) {
                        throw new IllegalStateException("Cannot enable speaker tuning: " + result);
                    }
                }
                current(generation);
                if (!mEffect.hasControl()) {
                    retryable = false;
                    throw new IllegalStateException("Lost speaker tuning control");
                }
                // INSERT_LAST orders this after Samsung DAP's INSERT_FIRST; VOLUME_IND lets
                // AudioFlinger deliver the real volume instead of estimating stream gain.
                status = R.string.soundbooster_active;
                details = "id=" + mEffect.getId() + ", enabled=true, control=true, rotation=" + rotation;
            }
            current(generation);
        } catch (Superseded e) {
            releaseOnWorker();
            return;
        } catch (RuntimeException e) {
            failed = true;
            details = e.toString();
            releaseOnWorker();
            Log.w(TAG, "Speaker tuning setup attempt " + attempt + " failed", e);
        }
        final int completedStatus = failed ? R.string.soundbooster_unavailable : status;
        final String completedDetails = details;
        final boolean retry = failed && retryable && attempt < MAX_ATTEMPTS;
        final boolean block = failed && !retryable;
        mContext.getMainExecutor().execute(() -> {
            if (generation != mGeneration || mClosed) return;
            if (block) mBlocked = true;
            mStatus = retry ? R.string.soundbooster_starting : completedStatus;
            mDetails = completedDetails;
            mChanged.run();
            if (retry) mMain.postDelayed(() -> {
                if (generation != mGeneration || mClosed) return;
                mWorker.execute(() -> applyOnWorker(generation, allowed, rotation, idleStatus,
                        idleDetails, attempt + 1));
            }, attempt * 1000L);
        });
    }

    private void releaseOnWorker() {
        AudioEffect effect = mEffect;
        mEffect = null;
        mAppliedRotation = -1;
        ++mHandleToken;
        if (effect == null) return;
        try {
            if (mServerAlive && effect.hasControl()) effect.setEnabled(false);
        } catch (RuntimeException e) {
            Log.w(TAG, "Cannot disable speaker tuning", e);
        } finally {
            try { effect.release(); }
            catch (RuntimeException e) { Log.w(TAG, "Cannot release speaker tuning", e); }
        }
    }

    void close() {
        mClosed = true;
        ++mGeneration;
        ++mDiscoveryGeneration;
        try {
            if (mRouteRegistered) {
                mAudioManager.removeOnDevicesForAttributesChangedListener(mRouteListener);
            }
        } catch (RuntimeException e) { Log.w(TAG, "Cannot unregister route monitoring", e); }
        try {
            if (mPlaybackRegistered) mAudioManager.unregisterAudioPlaybackCallback(mPlaybackListener);
        } catch (RuntimeException e) { Log.w(TAG, "Cannot unregister playback monitoring", e); }
        try {
            if (mDisplayRegistered) mDisplayManager.unregisterDisplayListener(mDisplayListener);
        } catch (RuntimeException e) { Log.w(TAG, "Cannot unregister display monitoring", e); }
        mWorker.execute(this::releaseOnWorker);
    }

    String describeState() {
        return "Speaker tuning available=" + mAvailable + ", requested enabled=" + mEnabled
                + "\n" + mContext.getString(mStatus) + "\nLast setup: " + mDetails;
    }
}
