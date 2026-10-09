/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.camera.compat;

import android.os.SystemClock;

/** UI recording progress for platforms without Samsung duration notifications. */
public final class RecordingClock {
    private long mElapsedMillis;
    private long mRunningSinceMillis;
    private boolean mRunning;
    private boolean mActive;

    /** Called only after the recorder has started successfully, or file rollover. */
    public synchronized void start() {
        mElapsedMillis = 0;
        mRunningSinceMillis = SystemClock.elapsedRealtime();
        mRunning = true;
        mActive = true;
    }

    /** A successful recorder pause preserves the recorded active duration. */
    public synchronized void pause() {
        if (mRunning) {
            mElapsedMillis = elapsedMillis();
            mRunning = false;
        }
    }

    /** A successful recorder resume starts a new active segment. */
    public synchronized void resume() {
        if (mActive && !mRunning) {
            mRunningSinceMillis = SystemClock.elapsedRealtime();
            mRunning = true;
        }
    }

    /** Keeps a next-file callback from reviving a finished or paused recorder. */
    public synchronized void rollover() {
        if (!mActive) {
            return;
        }
        mElapsedMillis = 0;
        if (mRunning) {
            mRunningSinceMillis = SystemClock.elapsedRealtime();
        }
    }

    /** Freezes final duration and prevents delayed callbacks restarting the tick. */
    public synchronized void finish() {
        pause();
        mActive = false;
    }

    public synchronized boolean isActive() {
        return mActive;
    }

    public synchronized long elapsedMillis() {
        if (!mRunning) {
            return mElapsedMillis;
        }
        long delta = Math.max(0, SystemClock.elapsedRealtime() - mRunningSinceMillis);
        return delta > Long.MAX_VALUE - mElapsedMillis
                ? Long.MAX_VALUE : mElapsedMillis + delta;
    }
}
