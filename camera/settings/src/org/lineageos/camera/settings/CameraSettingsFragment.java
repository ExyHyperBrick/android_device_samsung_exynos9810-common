/*
 * SPDX-FileCopyrightText: 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.camera.settings;

import android.os.Bundle;
import android.widget.Toast;
import androidx.preference.Preference;
import com.android.settingslib.widget.MainSwitchPreference;
import com.android.settingslib.widget.SettingsBasePreferenceFragment;

public final class CameraSettingsFragment extends SettingsBasePreferenceFragment {
    private CameraLauncherController mController;
    private MainSwitchPreference mEnabled;
    private MainSwitchPreference mApertureHidden;

    @Override public void onCreatePreferences(Bundle state, String rootKey) {
        setPreferencesFromResource(R.xml.camera_settings, rootKey);
        mController = new CameraLauncherController(requireContext());
        mEnabled = findPreference("camera_enable");
        mEnabled.setOnPreferenceChangeListener((preference, value) -> {
            if (!(value instanceof Boolean)) return false;
            boolean success = mController.setCameraEnabled((Boolean) value);
            if (!success) Toast.makeText(requireContext(), R.string.camera_enable_failed,
                    Toast.LENGTH_SHORT).show();
            refresh();
            return success;
        });
        mApertureHidden = findPreference("aperture_launcher_hide");
        mApertureHidden.setOnPreferenceChangeListener((preference, value) -> {
            if (!(value instanceof Boolean)) return false;
            boolean success = mController.setApertureHidden((Boolean) value);
            if (!success) Toast.makeText(requireContext(), R.string.aperture_launcher_failed,
                    Toast.LENGTH_SHORT).show();
            refresh();
            return success;
        });
    }

    @Override public void onResume() {
        super.onResume();
        refresh();
    }

    private void refresh() {
        boolean cameraAvailable = mController.isCameraAvailable();
        boolean apertureAvailable = mController.isApertureAvailable();
        boolean allowed = mController.canChangeState();
        mEnabled.setEnabled(cameraAvailable && allowed);
        mEnabled.setChecked(mController.isCameraEnabled());
        mApertureHidden.setEnabled(apertureAvailable && allowed);
        mApertureHidden.setChecked(mController.isApertureHidden());
        Preference cameraStatus = findPreference("camera_status");
        cameraStatus.setVisible(!cameraAvailable || !allowed);
        cameraStatus.setSummary(!allowed ? R.string.camera_restricted : R.string.camera_unavailable);
        Preference apertureStatus = findPreference("aperture_launcher_status");
        apertureStatus.setVisible(!apertureAvailable || !allowed);
        apertureStatus.setSummary(!allowed ? R.string.camera_restricted
                : R.string.aperture_launcher_unavailable);
    }
}
