/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.equalizer;

import android.content.Context;
import android.content.SharedPreferences;
import android.media.audiofx.AudioEffect;
import android.os.Handler;
import android.util.Log;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;
import java.util.UUID;
import java.util.concurrent.Executor;

/** Stores output profiles; the native effect selects them from its actual device. */
final class OutputEqualizer {
    private static final String TAG = "Exynos9810OutputEq";
    static final UUID UUID_EFFECT = UUID.fromString("32614e50-20f4-4e2c-949b-4f770747b102");
    static final int PROFILE_COUNT = 3;
    static final int BAND_COUNT = 5;
    private static final int MAX_ATTEMPTS = 3;
    private static final long APPLY_DELAY_MS = 150;
    private final Context mContext;
    private final SharedPreferences mPreferences;
    private final Executor mWorker;
    private final Handler mMain;
    private final Runnable mChanged;
    private final int[][] mProfiles = new int[PROFILE_COUNT][BAND_COUNT + 1];
    private final Runnable mApply = this::applySnapshot;

    // Preferences and UI state live on main; the handle is accessed only on the audio worker.
    private boolean mAvailable;
    private boolean mDiscovering;
    private boolean mBlocked;
    private boolean mClosed;
    private volatile boolean mServerAlive = true;
    private boolean mRecoveryAllowed = true;
    private volatile long mGeneration;
    private long mDiscoveryGeneration;
    private volatile long mHandleToken;
    private AudioEffect mEffect;
    private int mStatus = R.string.equalizer_starting;
    private String mDetails = "Effect discovery pending";

    OutputEqualizer(Context context, SharedPreferences preferences, Executor worker, Handler main,
            Runnable changed) {
        mContext = context;
        mPreferences = preferences;
        mWorker = worker;
        mMain = main;
        mChanged = changed;
        for (int profile = 0; profile < PROFILE_COUNT; ++profile) {
            mProfiles[profile][0] = preferences.getBoolean(enabledKey(profile), false) ? 1 : 0;
            for (int band = 0; band < BAND_COUNT; ++band) {
                mProfiles[profile][band + 1] = Math.max(-12, Math.min(12,
                        preferences.getInt(bandKey(profile, band), 0)));
            }
        }
    }

    private static String enabledKey(int profile) { return "enabled_" + profile; }
    private static String bandKey(int profile, int band) { return "gain_" + profile + "_" + band; }
    private static void checkProfile(int profile) {
        if (profile < 0 || profile >= PROFILE_COUNT) throw new IllegalArgumentException("Profile");
    }
    private boolean anyEnabled() {
        for (int[] profile : mProfiles) if (profile[0] != 0) return true;
        return false;
    }
    boolean isEnabled(int profile) { checkProfile(profile); return mProfiles[profile][0] != 0; }
    int getBand(int profile, int band) {
        checkProfile(profile);
        if (band < 0 || band >= BAND_COUNT) throw new IllegalArgumentException("Band");
        return mProfiles[profile][band + 1];
    }
    int getStatus() { return mStatus; }

    void setEnabled(int profile, boolean enabled) {
        checkProfile(profile);
        if (mClosed) return;
        mProfiles[profile][0] = enabled ? 1 : 0;
        mPreferences.edit().putBoolean(enabledKey(profile), enabled).apply();
        retry();
    }
    void setBand(int profile, int band, int gain) {
        getBand(profile, band);
        if (gain < -12 || gain > 12) throw new IllegalArgumentException("Gain");
        if (mClosed) return;
        mProfiles[profile][band + 1] = gain;
        mPreferences.edit().putInt(bandKey(profile, band), gain).apply();
        requestApply();
    }
    void reset(int profile) {
        checkProfile(profile);
        if (mClosed) return;
        SharedPreferences.Editor editor = mPreferences.edit();
        for (int band = 0; band < BAND_COUNT; ++band) {
            mProfiles[profile][band + 1] = 0;
            editor.putInt(bandKey(profile, band), 0);
        }
        editor.apply();
        requestApply();
    }

    void start() {
        if (mClosed || mDiscovering || !mServerAlive || !mRecoveryAllowed) return;
        mDiscovering = true;
        discover(++mDiscoveryGeneration, 1);
    }
    private void discover(long generation, int attempt) {
        mWorker.execute(() -> {
            boolean found = false;
            try {
                AudioEffect.Descriptor[] descriptors = AudioEffect.queryEffects();
                if (descriptors != null) {
                    for (AudioEffect.Descriptor descriptor : descriptors) {
                        if (UUID_EFFECT.equals(descriptor.uuid)) found = true;
                    }
                }
            } catch (RuntimeException e) { Log.w(TAG, "Effect discovery failed", e); }
            final boolean available = found;
            mContext.getMainExecutor().execute(() -> {
                if (mClosed || generation != mDiscoveryGeneration) return;
                if (!available && attempt < MAX_ATTEMPTS) {
                    mMain.postDelayed(() -> {
                        if (!mClosed && generation == mDiscoveryGeneration) {
                            discover(generation, attempt + 1);
                        }
                    }, attempt * 1000L);
                    return;
                }
                mDiscovering = false;
                mAvailable = available;
                if (available) requestApply();
                else publish(R.string.equalizer_unavailable, "Output EQ not registered");
            });
        });
    }
    void retry() {
        mBlocked = false;
        if (!mAvailable) start();
        requestApply();
    }
    void onAudioServerState(boolean alive, boolean allowed) {
        mServerAlive = alive;
        mRecoveryAllowed = allowed;
        if (!alive) {
            ++mDiscoveryGeneration;
            mDiscovering = false;
            mAvailable = false;
        }
        requestApply();
        if (alive && !mAvailable) start();
    }
    private void requestApply() {
        if (mClosed) return;
        ++mGeneration;
        mMain.removeCallbacks(mApply);
        mMain.postDelayed(mApply, APPLY_DELAY_MS);
        mChanged.run();
    }
    private void applySnapshot() {
        if (mClosed) return;
        final long generation = mGeneration;
        final boolean requested = anyEnabled();
        final boolean allowed = requested && mAvailable && mServerAlive
                && mRecoveryAllowed && !mBlocked;
        int[][] snapshot = new int[PROFILE_COUNT][];
        for (int profile = 0; profile < PROFILE_COUNT; ++profile) {
            snapshot[profile] = mProfiles[profile].clone();
        }
        final int idleStatus = !requested ? R.string.equalizer_off
                : R.string.equalizer_unavailable;
        publish(allowed ? R.string.equalizer_starting : idleStatus,
                !requested ? "All profiles disabled" : "Waiting for effect availability/control");
        mWorker.execute(() -> applyOnWorker(generation, allowed, snapshot, idleStatus, 1));
    }
    private static final class Superseded extends RuntimeException {
        private static final long serialVersionUID = 1L;
    }
    private void current(long generation) {
        if (generation != mGeneration) throw new Superseded();
    }
    private static void requireSuccess(int result, String operation) {
        if (result != AudioEffect.SUCCESS) {
            throw new IllegalStateException(operation + ": " + result);
        }
    }
    private void applyOnWorker(long generation, boolean allowed, int[][] profiles, int idleStatus,
            int attempt) {
        if (generation != mGeneration) return;
        int status = idleStatus;
        String details = "All profiles disabled or effect not available";
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
                    throw new IllegalStateException("Another client owns output EQ");
                }
                for (int profile = 0; profile < PROFILE_COUNT; ++profile) {
                    current(generation);
                    ByteBuffer payload = ByteBuffer.allocate((BAND_COUNT + 1) * Integer.BYTES)
                            .order(ByteOrder.nativeOrder());
                    for (int value : profiles[profile]) payload.putInt(value);
                    requireSuccess(mEffect.setParameter(new int[]{0, profile}, payload.array()),
                            "Set profile " + profile);
                }
                current(generation);
                requireSuccess(mEffect.setEnabled(true), "Enable output EQ");
                byte[] nativeBytes = new byte[4 * Integer.BYTES];
                int result = mEffect.getParameter(new int[]{1}, nativeBytes);
                int[] nativeState = new int[4];
                if (result == nativeBytes.length) {
                    ByteBuffer payload = ByteBuffer.wrap(nativeBytes).order(ByteOrder.nativeOrder());
                    for (int i = 0; i < nativeState.length; ++i) nativeState[i] = payload.getInt();
                }
                details = "Profiles applied; native status result=" + result
                        + ", [route, rate, mode, processing]=" + Arrays.toString(nativeState);
                status = R.string.equalizer_active;
            }
        } catch (Superseded e) {
            return;
        } catch (RuntimeException e) {
            releaseOnWorker();
            failed = true;
            status = R.string.equalizer_unavailable;
            details = e.toString();
            Log.w(TAG, "Output EQ setup attempt " + attempt + " failed", e);
        }
        final int finalStatus = status;
        final String finalDetails = details;
        final boolean retry = failed && retryable && attempt < MAX_ATTEMPTS;
        mContext.getMainExecutor().execute(() -> {
            if (mClosed || generation != mGeneration) return;
            publish(finalStatus, finalDetails);
            if (retry) mMain.postDelayed(() -> {
                if (!mClosed && generation == mGeneration && mServerAlive && mRecoveryAllowed) {
                    mWorker.execute(() -> applyOnWorker(generation, allowed, profiles,
                            idleStatus, attempt + 1));
                }
            }, attempt * 1000L);
        });
    }
    private void releaseOnWorker() {
        ++mHandleToken;
        if (mEffect == null) return;
        try {
            if (mEffect.hasControl()) mEffect.setEnabled(false);
        } catch (RuntimeException e) { Log.w(TAG, "Cannot disable output EQ", e); }
        try { mEffect.release(); }
        catch (RuntimeException e) { Log.w(TAG, "Cannot release output EQ", e); }
        mEffect = null;
    }
    private void publish(int status, String details) {
        mStatus = status;
        mDetails = details;
        mChanged.run();
    }
    String describeState() {
        return "available=" + mAvailable + ", blocked=" + mBlocked + ", serverAlive="
                + mServerAlive + ", recoveryAllowed=" + mRecoveryAllowed + ", profiles="
                + Arrays.deepToString(mProfiles) + "; last setup snapshot: " + mDetails;
    }
    void close() {
        mClosed = true;
        ++mGeneration;
        ++mDiscoveryGeneration;
        mMain.removeCallbacks(mApply);
        mWorker.execute(this::releaseOnWorker);
    }
}
