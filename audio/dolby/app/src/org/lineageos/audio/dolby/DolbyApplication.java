/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.dolby;

import android.app.Application;
import android.content.SharedPreferences;
import android.media.AudioManager;
import android.media.audiofx.AudioEffect;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.os.UserHandle;
import android.util.Log;

import java.util.ArrayList;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

public final class DolbyApplication extends Application {
    private static final String TAG = "Exynos9810Dolby";
    private static final int MAX_SETUP_ATTEMPTS = 3;
    private static final int MAX_SERVER_RECOVERIES = 3;
    private static final long RECOVERY_WINDOW_MS = 60_000;

    private final Handler mMain = new Handler(Looper.getMainLooper());
    private Executor mEffectExecutor = Executors.newSingleThreadExecutor(task -> {
        Thread thread = new Thread(task, "dolby-control");
        thread.setDaemon(true);
        return thread;
    });
    private final ArrayList<Runnable> mListeners = new ArrayList<>();
    private SharedPreferences mPreferences;
    private AudioManager mAudioManager;
    // Only the worker owns/calls the native handle. UI state belongs to the main thread.
    private AudioEffect mEffect;
    private volatile long mGeneration;
    private volatile boolean mServerAlive = true;
    private boolean mReady;
    private boolean mEnabled;
    private int mProfile = MotorolaDolby.MUSIC;
    private int mMode = AudioManager.MODE_NORMAL;
    private int mStatus = R.string.dolby_starting;
    private String mDetails = "No completed setup";
    private boolean mRecoveryBlocked;
    private long mRecoveryWindowStart;
    private int mServerRecoveries;

    @Override
    public void onCreate() {
        super.onCreate();
        if (UserHandle.myUserId() != UserHandle.USER_SYSTEM) {
            mStatus = R.string.dolby_owner_only;
            return;
        }
        try {
            mPreferences = getSharedPreferences("dolby", MODE_PRIVATE);
            mEnabled = mPreferences.getBoolean("enabled", true);
            mProfile = mPreferences.getInt("profile", MotorolaDolby.MUSIC);
            if (mProfile != MotorolaDolby.MUSIC && mProfile != MotorolaDolby.DYNAMIC) {
                mProfile = MotorolaDolby.MUSIC;
            }
            mAudioManager = getSystemService(AudioManager.class);
            if (mAudioManager == null) throw new IllegalStateException("AudioManager unavailable");
            mMode = mAudioManager.getMode();
            mAudioManager.addOnModeChangedListener(getMainExecutor(), mode -> {
                mMode = mode;
                requestApply();
            });
            mAudioManager.setAudioServerStateCallback(getMainExecutor(),
                    new AudioManager.AudioServerStateCallback() {
                        @Override public void onAudioServerDown() {
                            mServerAlive = false;
                            requestApply();
                        }
                        @Override public void onAudioServerUp() {
                            if (mServerAlive) return;
                            mServerAlive = true;
                            // Avoid an endless audioserver crash/recreate cycle caused by a blob.
                            long now = SystemClock.elapsedRealtime();
                            if (now - mRecoveryWindowStart >= RECOVERY_WINDOW_MS) {
                                mRecoveryWindowStart = now;
                                mServerRecoveries = 0;
                            }
                            if (++mServerRecoveries > MAX_SERVER_RECOVERIES) {
                                mRecoveryBlocked = true;
                            }
                            requestApply();
                        }
                    });
            mReady = true;
            requestApply();
        } catch (RuntimeException e) {
            mStatus = R.string.dolby_unavailable;
            mDetails = e.toString();
            Log.e(TAG, "Cannot initialize audio monitoring", e);
        }
    }

    public boolean isEnabled() { return mEnabled; }
    public boolean isReady() { return mReady; }
    public int getProfile() { return mProfile; }
    public int getStatus() { return mStatus; }

    public void setEnabled(boolean enabled) {
        if (!mReady) return;
        mEnabled = enabled;
        mPreferences.edit().putBoolean("enabled", enabled).apply();
        retry();
    }

    public void setProfile(int profile) {
        if (profile != MotorolaDolby.MUSIC && profile != MotorolaDolby.DYNAMIC) {
            throw new IllegalArgumentException("Unsupported Dolby profile " + profile);
        }
        if (!mReady || profile == mProfile) return;
        mProfile = profile;
        mPreferences.edit().putInt("profile", profile).apply();
        retry();
    }

    public void retry() {
        if (!mReady) return;
        mRecoveryBlocked = false;
        mServerRecoveries = 0;
        mRecoveryWindowStart = SystemClock.elapsedRealtime();
        requestApply();
    }

    private void requestApply() {
        long generation = ++mGeneration;
        boolean available = mReady && mServerAlive && !mRecoveryBlocked;
        try {
            if (mAudioManager != null) mMode = mAudioManager.getMode();
        } catch (RuntimeException e) {
            available = false;
        }
        final boolean canApply = available;
        final boolean enabled = mEnabled;
        final int profile = mProfile;
        final int mode = mMode;
        mStatus = R.string.dolby_starting;
        mDetails = "Pending: previous handle cleanup not yet confirmed";
        notifyState();
        mEffectExecutor.execute(() -> applyOnWorker(generation, enabled, profile, mode, canApply, 1));
    }

    private static final class Superseded extends RuntimeException {
        private static final long serialVersionUID = 1L;
    }

    private void current(long generation) {
        if (generation != mGeneration) throw new Superseded();
    }

    private void applyOnWorker(long generation, boolean enabled, int profile, int mode,
            boolean available, int attempt) {
        if (generation != mGeneration) return;
        AudioEffect candidate = null;
        int status = R.string.dolby_unavailable;
        String details = "No effect attached";
        boolean failed = false;
        boolean retryable = true;
        try {
            releaseOnWorker();
            current(generation);
            if (!enabled) {
                status = R.string.dolby_off;
            } else if (!available) {
                details = "Audio server unavailable or automatic recovery suspended";
            } else if (mode != AudioManager.MODE_NORMAL) {
                status = R.string.dolby_paused;
            } else {
                candidate = new AudioEffect(AudioEffect.EFFECT_TYPE_NULL,
                        MotorolaDolby.UUID_DAP, 0, 0);
                current(generation);
                if (!candidate.hasControl()) {
                    retryable = false;
                    throw new IllegalStateException("Another client owns the Dolby effect");
                }
                Runnable valid = () -> current(generation);
                MotorolaDolby.prepare(candidate, profile, valid);
                current(generation);
                int result = candidate.setEnabled(true);
                if (result != AudioEffect.SUCCESS || !candidate.getEnabled()) {
                    throw new IllegalStateException("Cannot enable Dolby: " + result);
                }
                current(generation);
                String state = MotorolaDolby.verify(candidate, profile, valid);
                current(generation);
                candidate.setControlStatusListener((effect, hasControl) -> {
                    if (!hasControl) getMainExecutor().execute(() -> {
                        if (generation == mGeneration) {
                            mRecoveryBlocked = true;
                            requestApply();
                        }
                    });
                });
                // Register before the final ownership check so a loss in this window
                // is either observed here or delivered through the listener.
                current(generation);
                if (!candidate.hasControl()) {
                    retryable = false;
                    throw new IllegalStateException("Lost Dolby control during setup");
                }
                details = "id=" + candidate.getId() + ", enabled=true, control=true\n" + state;
                mEffect = candidate;
                candidate = null;
                status = R.string.dolby_active;
            }
        } catch (Superseded e) {
            return;
        } catch (RuntimeException e) {
            failed = true;
            details = e.toString();
            Log.e(TAG, "Setup attempt " + attempt + " failed", e);
        } finally {
            if (candidate != null) closeEffect(candidate);
        }
        final int completedStatus = status;
        final String completedDetails = details;
        final boolean retry = failed && retryable && attempt < MAX_SETUP_ATTEMPTS;
        getMainExecutor().execute(() -> {
            if (generation != mGeneration) return;
            mStatus = retry ? R.string.dolby_starting : completedStatus;
            mDetails = completedDetails;
            notifyState();
            if (retry) {
                // Bounded retries cover DMS startup; there is no timer or polling while active.
                mMain.postDelayed(() -> {
                    if (generation != mGeneration) return;
                    mEffectExecutor.execute(() -> applyOnWorker(generation, enabled, profile,
                            mode, available, attempt + 1));
                }, attempt * 1000L);
            }
        });
    }

    private void releaseOnWorker() {
        AudioEffect previous = mEffect;
        mEffect = null;
        if (previous != null) closeEffect(previous);
    }

    private void closeEffect(AudioEffect effect) {
        try {
            if (effect.hasControl()) {
                try {
                    if (mServerAlive) MotorolaDolby.disableInternal(effect);
                } catch (RuntimeException e) {
                    Log.w(TAG, "Cannot bypass DMS; releasing framework handle", e);
                }
                effect.setEnabled(false);
            }
        } catch (RuntimeException e) {
            Log.w(TAG, "Cannot disable old effect", e);
        } finally {
            try { effect.release(); }
            catch (RuntimeException e) { Log.w(TAG, "Cannot release old effect", e); }
        }
    }

    public String describeState() {
        return "Requested enabled=" + mEnabled + ", profile=" + mProfile + ", audio mode=" + mMode
                + "\n" + getString(mStatus) + "\nLast setup: " + mDetails;
    }

    public void addListener(Runnable listener) {
        if (!mListeners.contains(listener)) mListeners.add(listener);
    }
    public void removeListener(Runnable listener) { mListeners.remove(listener); }
    private void notifyState() {
        Log.i(TAG, describeState());
        for (Runnable listener : new ArrayList<>(mListeners)) listener.run();
    }
}
