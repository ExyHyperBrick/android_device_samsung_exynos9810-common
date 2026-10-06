/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.soundbooster;

import android.app.Application;
import android.media.AudioManager;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.os.UserHandle;
import android.util.Log;

import java.util.ArrayList;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

public final class SoundBoosterApplication extends Application {
    private static final String TAG = "Exynos9810SoundBooster";
    private static final int MAX_SERVER_RECOVERIES = 3;
    private static final long RECOVERY_WINDOW_MS = 60_000;
    private final Handler mMain = new Handler(Looper.getMainLooper());
    private Executor mEffectExecutor = Executors.newSingleThreadExecutor(task -> {
        Thread thread = new Thread(task, "soundbooster-control");
        thread.setDaemon(true);
        return thread;
    });
    private final ArrayList<Runnable> mListeners = new ArrayList<>();
    private AudioManager mAudioManager;
    private AudioManager.OnModeChangedListener mModeListener;
    private SoundBooster mController;
    private boolean mServerAlive = true;
    private boolean mRecoveryBlocked;
    private int mServerRecoveries;
    private long mRecoveryWindowStart;
    private String mInitializationError = "Controller not initialized";

    @Override
    public void onCreate() {
        super.onCreate();
        if (UserHandle.myUserId() != UserHandle.USER_SYSTEM) {
            mInitializationError = "Only the owner user controls device-wide speaker tuning";
            return;
        }
        try {
            mAudioManager = getSystemService(AudioManager.class);
            if (mAudioManager == null) throw new IllegalStateException("AudioManager unavailable");
            mController = new SoundBooster(this, mAudioManager,
                    getSharedPreferences("soundbooster", MODE_PRIVATE), mEffectExecutor, mMain,
                    this::notifyState);
            final SoundBooster controller = mController;
            mModeListener = mode -> controller.requestApply();
            mAudioManager.addOnModeChangedListener(getMainExecutor(), mModeListener);
            mAudioManager.setAudioServerStateCallback(getMainExecutor(),
                    new AudioManager.AudioServerStateCallback() {
                        @Override public void onAudioServerDown() {
                            mServerAlive = false;
                            controller.onAudioServerState(false, !mRecoveryBlocked);
                        }
                        @Override public void onAudioServerUp() {
                            if (mServerAlive) return;
                            mServerAlive = true;
                            long now = SystemClock.elapsedRealtime();
                            if (now - mRecoveryWindowStart >= RECOVERY_WINDOW_MS) {
                                mRecoveryWindowStart = now;
                                mServerRecoveries = 0;
                            }
                            if (++mServerRecoveries > MAX_SERVER_RECOVERIES) mRecoveryBlocked = true;
                            controller.onAudioServerState(true, !mRecoveryBlocked);
                        }
                    });
            mController.start();
        } catch (RuntimeException e) {
            mInitializationError = e.toString();
            if (mController != null) mController.close();
            unregisterAudioMonitoring();
            mController = null;
            Log.e(TAG, "Cannot initialize speaker tuning", e);
        }
    }

    public boolean isReady() { return mController != null; }
    public boolean isAvailable() { return mController != null && mController.isAvailable(); }
    public boolean isEnabled() { return mController != null && mController.isEnabled(); }
    public int getStatus() {
        return mController == null ? R.string.soundbooster_unavailable : mController.getStatus();
    }
    public void setEnabled(boolean enabled) {
        if (mController != null) mController.setEnabled(enabled);
    }
    public void retry() {
        if (mController == null) return;
        mRecoveryBlocked = false;
        mServerRecoveries = 0;
        mRecoveryWindowStart = SystemClock.elapsedRealtime();
        mController.onAudioServerState(mServerAlive, true);
        mController.retry();
    }
    public String describeState() {
        return mController == null ? mInitializationError : mController.describeState();
    }
    public void addListener(Runnable listener) {
        if (!mListeners.contains(listener)) mListeners.add(listener);
    }
    public void removeListener(Runnable listener) { mListeners.remove(listener); }
    private void notifyState() {
        Log.i(TAG, describeState());
        for (Runnable listener : new ArrayList<>(mListeners)) listener.run();
    }
    private void unregisterAudioMonitoring() {
        if (mAudioManager == null) return;
        try {
            if (mModeListener != null) mAudioManager.removeOnModeChangedListener(mModeListener);
        } catch (RuntimeException e) { Log.w(TAG, "Cannot unregister audio mode monitoring", e); }
        try {
            mAudioManager.clearAudioServerStateCallback();
        } catch (RuntimeException e) { Log.w(TAG, "Cannot unregister audio server monitoring", e); }
    }
    @Override
    public void onTerminate() {
        if (mController != null) mController.close();
        unregisterAudioMonitoring();
        super.onTerminate();
    }
}
