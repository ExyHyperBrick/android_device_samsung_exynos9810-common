/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.equalizer;

import android.app.Application;
import android.media.AudioManager;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.os.UserHandle;
import android.util.Log;

import java.util.ArrayList;
import java.util.concurrent.Executors;

public final class EqualizerApplication extends Application {
    private static final String TAG = "Exynos9810OutputEq";
    private static final int MAX_SERVER_RECOVERIES = 3;
    private static final long RECOVERY_WINDOW_MS = 60_000;
    private final Handler mMain = new Handler(Looper.getMainLooper());
    private final ArrayList<Runnable> mListeners = new ArrayList<>();
    private OutputEqualizer mController;
    private AudioManager mAudioManager;
    private boolean mMonitoring;
    private boolean mServerAlive = true;
    private boolean mRecoveryBlocked;
    private int mRecoveries;
    private long mRecoveryWindowStart;
    private String mError = "Controller not initialized";

    @Override public void onCreate() {
        super.onCreate();
        if (UserHandle.myUserId() != UserHandle.USER_SYSTEM) {
            mError = "Only the owner user controls output EQ";
            return;
        }
        try {
            mAudioManager = getSystemService(AudioManager.class);
            if (mAudioManager == null) throw new IllegalStateException("AudioManager unavailable");
            mController = new OutputEqualizer(this, getSharedPreferences("output_equalizer",
                    MODE_PRIVATE), Executors.newSingleThreadExecutor(task -> {
                        Thread thread = new Thread(task, "output-equalizer-control");
                        thread.setDaemon(true);
                        return thread;
                    }), mMain, this::notifyState);
            final OutputEqualizer controller = mController;
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
                                mRecoveries = 0;
                            }
                            if (++mRecoveries > MAX_SERVER_RECOVERIES) mRecoveryBlocked = true;
                            controller.onAudioServerState(true, !mRecoveryBlocked);
                        }
                    });
            mMonitoring = true;
            controller.start();
        } catch (RuntimeException e) {
            mError = e.toString();
            if (mController != null) mController.close();
            mController = null;
            unregisterMonitoring();
            Log.e(TAG, "Cannot initialize output EQ", e);
        }
    }
    public boolean isReady() { return mController != null; }
    public boolean isEnabled(int profile) {
        return mController != null && mController.isEnabled(profile);
    }
    public int getBand(int profile, int band) {
        return mController == null ? 0 : mController.getBand(profile, band);
    }
    public void setBand(int profile, int band, int gain) {
        if (mController != null) mController.setBand(profile, band, gain);
    }
    public void setEnabled(int profile, boolean enabled) {
        if (mController != null) mController.setEnabled(profile, enabled);
    }
    public void reset(int profile) { if (mController != null) mController.reset(profile); }
    public int getStatus() {
        if (UserHandle.myUserId() != UserHandle.USER_SYSTEM) return R.string.equalizer_owner_only;
        return mController == null ? R.string.equalizer_unavailable : mController.getStatus();
    }
    public void retry() {
        if (mController == null) return;
        mRecoveryBlocked = false;
        mRecoveries = 0;
        mRecoveryWindowStart = SystemClock.elapsedRealtime();
        mController.onAudioServerState(mServerAlive, true);
        mController.retry();
    }
    public String describeState() {
        return mController == null ? mError : mController.describeState();
    }
    public void addListener(Runnable listener) {
        if (!mListeners.contains(listener)) mListeners.add(listener);
    }
    public void removeListener(Runnable listener) { mListeners.remove(listener); }
    private void notifyState() {
        for (Runnable listener : new ArrayList<>(mListeners)) listener.run();
    }
    private void unregisterMonitoring() {
        if (!mMonitoring || mAudioManager == null) return;
        try { mAudioManager.clearAudioServerStateCallback(); }
        catch (RuntimeException e) { Log.w(TAG, "Cannot unregister audio monitoring", e); }
        mMonitoring = false;
    }
    @Override public void onTerminate() {
        if (mController != null) mController.close();
        unregisterMonitoring();
        super.onTerminate();
    }
}
