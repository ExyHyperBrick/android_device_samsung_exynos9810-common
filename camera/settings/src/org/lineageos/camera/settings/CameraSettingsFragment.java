/*
 * SPDX-FileCopyrightText: 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.camera.settings;

import android.os.Bundle;
import android.widget.Toast;
import com.android.settingslib.widget.MainSwitchPreference;
import com.android.settingslib.widget.SettingsBasePreferenceFragment;

public final class CameraSettingsFragment extends SettingsBasePreferenceFragment {
    private CameraLauncherController mController;
    private MainSwitchPreference mEnabled;
    private MainSwitchPreference mShown;

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
        mShown = findPreference("camera_launcher_enable");
        mShown.setOnPreferenceChangeListener((preference, value) -> {
            if (!(value instanceof Boolean)) return false;
            boolean success = mController.setShown((Boolean) value);
            if (!success) Toast.makeText(requireContext(), R.string.camera_launcher_failed,
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
        boolean cameraEnabled = mController.isCameraEnabled();
        boolean launcherAvailable = mController.isAvailable();
        boolean allowed = mController.canChangeState();
        mEnabled.setEnabled(cameraAvailable && allowed);
        mEnabled.setChecked(cameraEnabled);
        mShown.setEnabled(launcherAvailable && allowed);
        mShown.setChecked(mController.isShown());
        androidx.preference.Preference status = findPreference("camera_launcher_status");
        status.setVisible(!launcherAvailable || !allowed);
        status.setSummary(!cameraAvailable ? R.string.camera_unavailable
                : !allowed ? R.string.camera_restricted
                : !cameraEnabled ? R.string.camera_disabled : R.string.camera_launcher_unavailable);
    }
}
