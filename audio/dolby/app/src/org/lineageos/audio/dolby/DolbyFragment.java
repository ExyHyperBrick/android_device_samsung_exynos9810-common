/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.dolby;

import android.os.Bundle;

import androidx.preference.Preference;

import com.android.settingslib.widget.MainSwitchPreference;
import com.android.settingslib.widget.SelectorWithWidgetPreference;
import com.android.settingslib.widget.SettingsBasePreferenceFragment;

import java.util.EnumMap;

public final class DolbyFragment extends SettingsBasePreferenceFragment {
    private DolbyApplication mDolby;
    private MainSwitchPreference mEnabled;
    private final EnumMap<DolbyProfile, SelectorWithWidgetPreference> mProfiles =
            new EnumMap<>(DolbyProfile.class);
    private Preference mStatus;
    private Preference mRetry;
    private final Runnable mListener = this::refresh;

    @Override
    public void onCreatePreferences(Bundle state, String rootKey) {
        setPreferencesFromResource(R.xml.dolby_settings, rootKey);
        mDolby = (DolbyApplication) requireActivity().getApplication();
        mEnabled = findPreference("dolby_enable");
        mProfiles.clear();
        for (DolbyProfile profile : DolbyProfile.values()) {
            SelectorWithWidgetPreference preference = findPreference(profile.preferenceKey);
            preference.setOnPreferenceClickListener(unused -> setProfile(profile));
            mProfiles.put(profile, preference);
        }
        mStatus = findPreference("dolby_status");
        mRetry = findPreference("dolby_retry");

        // The existing device-protected controller store is the only source of truth.
        mEnabled.setOnPreferenceChangeListener((preference, value) -> {
            if (!mDolby.isReady() || !(value instanceof Boolean)) return false;
            mDolby.setEnabled((Boolean) value);
            return true;
        });
        mRetry.setOnPreferenceClickListener(preference -> {
            mDolby.retry();
            return true;
        });
        refresh();
    }

    @Override
    public void onStart() {
        super.onStart();
        mDolby.addListener(mListener);
        refresh();
    }

    @Override
    public void onStop() {
        mDolby.removeListener(mListener);
        super.onStop();
    }

    private boolean setProfile(DolbyProfile profile) {
        if (!mDolby.isReady() || !mDolby.isEnabled()) return false;
        mDolby.setProfile(profile);
        refresh();
        return true;
    }

    private void refresh() {
        boolean ready = mDolby.isReady();
        boolean enabled = mDolby.isEnabled();
        mEnabled.setEnabled(ready);
        mEnabled.setChecked(enabled);
        for (DolbyProfile profile : DolbyProfile.values()) {
            SelectorWithWidgetPreference preference = mProfiles.get(profile);
            preference.setEnabled(ready && enabled);
            preference.setChecked(mDolby.getProfile() == profile);
        }
        mStatus.setSummary(mDolby.getStatus());
        mRetry.setVisible(ready && enabled && mDolby.getStatus() == R.string.dolby_unavailable);
    }
}
