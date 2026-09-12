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

public final class DolbyFragment extends SettingsBasePreferenceFragment {
    private DolbyApplication mDolby;
    private MainSwitchPreference mEnabled;
    private SelectorWithWidgetPreference mMusic;
    private SelectorWithWidgetPreference mDynamic;
    private Preference mStatus;
    private Preference mRetry;
    private final Runnable mListener = this::refresh;

    @Override
    public void onCreatePreferences(Bundle state, String rootKey) {
        setPreferencesFromResource(R.xml.dolby_settings, rootKey);
        mDolby = (DolbyApplication) requireActivity().getApplication();
        mEnabled = findPreference("dolby_enable");
        mMusic = findPreference("dolby_profile_music");
        mDynamic = findPreference("dolby_profile_dynamic");
        mStatus = findPreference("dolby_status");
        mRetry = findPreference("dolby_retry");

        // The existing device-protected controller store is the only source of truth.
        mEnabled.setOnPreferenceChangeListener((preference, value) -> {
            if (!mDolby.isReady() || !(value instanceof Boolean)) return false;
            mDolby.setEnabled((Boolean) value);
            return true;
        });
        mMusic.setOnPreferenceClickListener(preference -> setProfile(MotorolaDolby.MUSIC));
        mDynamic.setOnPreferenceClickListener(preference -> setProfile(MotorolaDolby.DYNAMIC));
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

    private boolean setProfile(int profile) {
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
        mMusic.setEnabled(ready && enabled);
        mDynamic.setEnabled(ready && enabled);
        mMusic.setChecked(mDolby.getProfile() == MotorolaDolby.MUSIC);
        mDynamic.setChecked(mDolby.getProfile() == MotorolaDolby.DYNAMIC);
        mStatus.setSummary(mDolby.getStatus());
        mRetry.setVisible(ready && enabled && mDolby.getStatus() == R.string.dolby_unavailable);
    }
}
