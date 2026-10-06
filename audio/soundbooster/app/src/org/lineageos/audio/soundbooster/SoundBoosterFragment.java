/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.soundbooster;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.os.Bundle;

import androidx.preference.Preference;

import com.android.settingslib.widget.MainSwitchPreference;
import com.android.settingslib.widget.SettingsBasePreferenceFragment;

public final class SoundBoosterFragment extends SettingsBasePreferenceFragment {
    private SoundBoosterApplication mApplication;
    private MainSwitchPreference mEnabled;
    private Preference mStatus;
    private Preference mRetry;
    private final Runnable mListener = this::refresh;

    @Override
    public void onCreatePreferences(Bundle state, String rootKey) {
        setPreferencesFromResource(R.xml.soundbooster_settings, rootKey);
        mApplication = (SoundBoosterApplication) requireActivity().getApplication();
        mEnabled = findPreference("soundbooster_enable");
        mStatus = findPreference("soundbooster_status");
        mRetry = findPreference("soundbooster_retry");
        mEnabled.setOnPreferenceChangeListener((preference, value) -> {
            if (!mApplication.isAvailable() || !(value instanceof Boolean)) return false;
            mApplication.setEnabled((Boolean) value);
            return true;
        });
        mRetry.setOnPreferenceClickListener(preference -> {
            mApplication.retry();
            return true;
        });
        findPreference("soundbooster_copy_status").setOnPreferenceClickListener(preference -> {
            ClipboardManager clipboard = requireContext().getSystemService(ClipboardManager.class);
            if (clipboard != null) clipboard.setPrimaryClip(ClipData.newPlainText(
                    getString(R.string.soundbooster_title), mApplication.describeState()));
            return true;
        });
        refresh();
    }
    @Override public void onStart() {
        super.onStart();
        mApplication.addListener(mListener);
        refresh();
    }
    @Override public void onStop() {
        mApplication.removeListener(mListener);
        super.onStop();
    }
    private void refresh() {
        mEnabled.setVisible(mApplication.isAvailable());
        mEnabled.setChecked(mApplication.isEnabled());
        mStatus.setSummary(mApplication.getStatus());
        mRetry.setVisible(mApplication.isReady()
                && mApplication.getStatus() == R.string.soundbooster_unavailable);
    }
}
