/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.equalizer;

import android.media.AudioManager;
import android.os.Bundle;

import com.android.settingslib.collapsingtoolbar.CollapsingToolbarBaseActivity;

import java.io.FileDescriptor;
import java.io.PrintWriter;

public final class EqualizerActivity extends CollapsingToolbarBaseActivity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        setVolumeControlStream(AudioManager.STREAM_MUSIC);
        setTitle(R.string.equalizer_title);
        if (state == null) getSupportFragmentManager().beginTransaction()
                .replace(com.android.settingslib.collapsingtoolbar.R.id.content_frame,
                        new EqualizerFragment()).commit();
    }
    @Override public void dump(String prefix, FileDescriptor fd, PrintWriter writer, String[] args) {
        super.dump(prefix, fd, writer, args);
        writer.println(prefix + ((EqualizerApplication) getApplication()).describeState());
    }
}
