/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.soundbooster;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import android.os.Binder;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.UserHandle;

import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;

/** Read-only state for the output equalizer; it never changes effect ownership. */
public final class SoundBoosterStatusProvider extends ContentProvider {
    private final Handler mMain = new Handler(Looper.getMainLooper());

    @Override public boolean onCreate() { return true; }

    @Override public Bundle call(String method, String arg, Bundle extras) {
        getContext().enforceCallingOrSelfPermission(
                "android.permission.MODIFY_AUDIO_ROUTING", "Read speaker tuning status");
        Bundle unavailable = new Bundle();
        if (!"get_status".equals(method)
                || UserHandle.myUserId() != UserHandle.USER_SYSTEM
                || UserHandle.getUserId(Binder.getCallingUid()) != UserHandle.USER_SYSTEM) {
            return unavailable;
        }
        FutureTask<Bundle> snapshot = new FutureTask<>(() -> {
            SoundBoosterApplication application = (SoundBoosterApplication)
                    getContext().getApplicationContext();
            Bundle result = new Bundle();
            result.putBoolean("available", application.isReady() && application.isAvailable());
            result.putBoolean("enabled", application.isEnabled());
            result.putString("summary", getContext().getString(application.getStatus()));
            return result;
        });
        if (Looper.myLooper() == Looper.getMainLooper()) snapshot.run();
        else mMain.post(snapshot);
        try {
            return snapshot.get(250, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            snapshot.cancel(false);
            return unavailable;
        } catch (Exception e) {
            snapshot.cancel(false);
            return unavailable;
        }
    }

    @Override public Cursor query(Uri uri, String[] projection, String selection,
            String[] selectionArgs, String sortOrder) { return null; }
    @Override public String getType(Uri uri) { return null; }
    @Override public Uri insert(Uri uri, ContentValues values) {
        throw new UnsupportedOperationException("Read-only effect status");
    }
    @Override public int delete(Uri uri, String selection, String[] selectionArgs) {
        throw new UnsupportedOperationException("Read-only effect status");
    }
    @Override public int update(Uri uri, ContentValues values, String selection,
            String[] selectionArgs) {
        throw new UnsupportedOperationException("Read-only effect status");
    }
}
