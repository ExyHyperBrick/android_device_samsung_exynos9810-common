/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.soundbooster;

import android.media.AudioManager;
import android.os.Bundle;

import com.android.settingslib.collapsingtoolbar.CollapsingToolbarBaseActivity;

import java.io.FileDescriptor;
import java.io.PrintWriter;

public final class SoundBoosterActivity extends CollapsingToolbarBaseActivity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        setVolumeControlStream(AudioManager.STREAM_MUSIC);
        setTitle(R.string.soundbooster_title);
        if (state == null) getSupportFragmentManager().beginTransaction()
                .replace(com.android.settingslib.collapsingtoolbar.R.id.content_frame,
                        new SoundBoosterFragment()).commit();
    }
    @Override public void dump(String prefix, FileDescriptor fd, PrintWriter writer, String[] args) {
        super.dump(prefix, fd, writer, args);
        SoundBoosterApplication application = (SoundBoosterApplication) getApplication();
        writer.println(prefix + application.describeState().replace("\n", "\n" + prefix));
    }
}
