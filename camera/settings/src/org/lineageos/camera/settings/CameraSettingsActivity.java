/*
 * SPDX-FileCopyrightText: 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.camera.settings;

import android.os.Bundle;
import com.android.settingslib.collapsingtoolbar.CollapsingToolbarBaseActivity;

public final class CameraSettingsActivity extends CollapsingToolbarBaseActivity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        setTitle(R.string.camera_settings_title);
        if (state == null) getSupportFragmentManager().beginTransaction()
                .replace(com.android.settingslib.collapsingtoolbar.R.id.content_frame,
                        new CameraSettingsFragment()).commit();
    }
}
