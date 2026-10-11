/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.equalizer;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.UserHandle;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Refreshes read-only effect status while settings is visible. */
final class EffectsStatus {
    interface Listener { void onStatus(String dolby, String speaker); }
    private static final ExecutorService WORKER = Executors.newSingleThreadExecutor();
    private static final Uri DOLBY = Uri.parse("content://org.lineageos.dap.status");
    private static final Uri SPEAKER = Uri.parse(
            "content://org.lineageos.audio.soundbooster.status");
    private final Context mContext;
    private final Listener mListener;
    private final Handler mMain = new Handler(Looper.getMainLooper());
    private final Runnable mRefresh = this::refresh;
    private boolean mStarted;
    private boolean mPending;
    private int mGeneration;

    EffectsStatus(Context context, Listener listener) {
        mContext = context.getApplicationContext();
        mListener = listener;
    }
    void start() {
        mStarted = true;
        ++mGeneration;
        refresh();
    }
    void stop() {
        mStarted = false;
        ++mGeneration;
        mMain.removeCallbacks(mRefresh);
    }
    private void refresh() {
        if (!mStarted || mPending) return;
        if (UserHandle.myUserId() != UserHandle.USER_SYSTEM) {
            String unavailable = mContext.getString(R.string.equalizer_effect_unavailable);
            mListener.onStatus(unavailable, unavailable);
            return;
        }
        mPending = true;
        final int generation = mGeneration;
        WORKER.execute(() -> {
            final String dolby = read(DOLBY);
            final String speaker = read(SPEAKER);
            mMain.post(() -> {
                mPending = false;
                if (!mStarted) return;
                if (generation == mGeneration) {
                    mListener.onStatus(dolby, speaker);
                    mMain.postDelayed(mRefresh, 2000);
                } else {
                    refresh();
                }
            });
        });
    }
    private String read(Uri uri) {
        try {
            Bundle result = mContext.getContentResolver().call(uri, "get_status", null, null);
            if (result != null && result.getBoolean("available", false)) {
                String state = mContext.getString(result.getBoolean("enabled", false)
                        ? R.string.equalizer_effect_on : R.string.equalizer_effect_off);
                String summary = result.getString("summary", "");
                return summary.isEmpty() ? state : mContext.getString(
                        R.string.equalizer_effect_detail, state, summary);
            }
        } catch (RuntimeException e) {
            // A missing companion, denied permission or restart is not an EQ failure.
        }
        return mContext.getString(R.string.equalizer_effect_unavailable);
    }
    static boolean open(Context context, boolean dolby) {
        if (UserHandle.myUserId() != UserHandle.USER_SYSTEM) return false;
        String pkg = dolby ? "org.lineageos.dap" : "org.lineageos.audio.soundbooster";
        String activity = dolby ? "DolbyActivity" : "SoundBoosterActivity";
        try {
            context.startActivity(new Intent().setComponent(
                    new ComponentName(pkg, pkg + "." + activity)));
            return true;
        } catch (RuntimeException e) {
            return false;
        }
    }
}
