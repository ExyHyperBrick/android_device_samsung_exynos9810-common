/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.equalizer;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.os.Bundle;
import android.widget.Toast;

import androidx.preference.ListPreference;
import androidx.preference.Preference;
import androidx.preference.SwitchPreferenceCompat;

import com.android.settingslib.widget.MainSwitchPreference;
import com.android.settingslib.widget.SettingsBasePreferenceFragment;

public final class EqualizerFragment extends SettingsBasePreferenceFragment {
    private EqualizerApplication mApplication;
    private MainSwitchPreference mEnabled;
    private EqualizerBandsPreference mBands;
    private int mProfile;
    private EffectsStatus mEffectsStatus;
    private EqualizerLauncherController mLauncher;
    private SwitchPreferenceCompat mShown;
    private final Runnable mListener = this::refresh;

    @Override
    public void onCreatePreferences(Bundle state, String rootKey) {
        setPreferencesFromResource(R.xml.equalizer_settings, rootKey);
        mApplication = (EqualizerApplication) requireActivity().getApplication();
        mProfile = state == null ? 0 : state.getInt("profile", 0);
        if (mProfile < 0 || mProfile >= OutputEqualizer.PROFILE_COUNT) mProfile = 0;
        ListPreference profile = findPreference("equalizer_profile");
        profile.setValue(Integer.toString(mProfile));
        profile.setOnPreferenceChangeListener((preference, value) -> {
            try {
                int selected = Integer.parseInt((String) value);
                if (selected < 0 || selected >= OutputEqualizer.PROFILE_COUNT) return false;
                mProfile = selected;
                refresh();
                return true;
            } catch (RuntimeException e) { return false; }
        });
        mEnabled = findPreference("equalizer_enable");
        mEnabled.setOnPreferenceChangeListener((preference, value) -> {
            if (!(value instanceof Boolean) || !mApplication.isReady()) return false;
            mApplication.setEnabled(mProfile, (Boolean) value);
            return true;
        });
        mBands = findPreference("equalizer_bands");
        mBands.setOnBandChangeListener((band, gain) -> {
            if (mApplication.isReady()) mApplication.setBand(mProfile, band, gain);
        });
        findPreference("equalizer_reset").setOnPreferenceClickListener(preference -> {
            mApplication.reset(mProfile);
            return true;
        });
        findPreference("equalizer_retry").setOnPreferenceClickListener(preference -> {
            mApplication.retry();
            return true;
        });
        findPreference("equalizer_copy_status").setOnPreferenceClickListener(preference -> {
            ClipboardManager clipboard = requireContext().getSystemService(ClipboardManager.class);
            if (clipboard != null) clipboard.setPrimaryClip(ClipData.newPlainText(
                    getString(R.string.equalizer_title), mApplication.describeState()));
            return true;
        });
        mLauncher = new EqualizerLauncherController(requireContext());
        mShown = findPreference("equalizer_launcher");
        mShown.setOnPreferenceChangeListener((preference, value) -> {
            if (!(value instanceof Boolean)) return false;
            boolean success = mLauncher.setShown((Boolean) value);
            if (!success) Toast.makeText(requireContext(), R.string.equalizer_launcher_failed,
                    Toast.LENGTH_SHORT).show();
            refreshLauncher();
            return success;
        });
        Preference dolby = findPreference("equalizer_dolby");
        Preference speaker = findPreference("equalizer_soundbooster");
        dolby.setSelectable(true);
        speaker.setSelectable(true);
        dolby.setSummary(R.string.equalizer_effect_loading);
        speaker.setSummary(R.string.equalizer_effect_loading);
        dolby.setOnPreferenceClickListener(preference -> EffectsStatus.open(requireContext(), true));
        speaker.setOnPreferenceClickListener(preference -> EffectsStatus.open(requireContext(), false));
        mEffectsStatus = new EffectsStatus(requireContext(), (dolbyState, speakerState) -> {
            dolby.setSummary(dolbyState);
            speaker.setSummary(speakerState);
        });
        boolean owner = android.os.UserHandle.myUserId() == android.os.UserHandle.USER_SYSTEM;
        dolby.setEnabled(owner);
        speaker.setEnabled(owner);
        refresh();
    }
    @Override public void onSaveInstanceState(Bundle state) {
        state.putInt("profile", mProfile);
        super.onSaveInstanceState(state);
    }
    @Override public void onStart() {
        super.onStart();
        mApplication.addListener(mListener);
        mEffectsStatus.start();
        refresh();
    }
    @Override public void onResume() {
        super.onResume();
        refreshLauncher();
    }
    private void refreshLauncher() {
        mShown.setChecked(mLauncher.isShown());
    }
    @Override public void onStop() {
        mEffectsStatus.stop();
        mApplication.removeListener(mListener);
        super.onStop();
    }
    private void refresh() {
        if (mEnabled == null) return;
        boolean ready = mApplication.isReady();
        mEnabled.setEnabled(ready);
        mEnabled.setChecked(mApplication.isEnabled(mProfile));
        int[] gains = new int[OutputEqualizer.BAND_COUNT];
        boolean boosted = false;
        for (int band = 0; band < gains.length; ++band) {
            gains[band] = mApplication.getBand(mProfile, band);
            boosted |= gains[band] > 0;
        }
        mBands.setEnabled(ready);
        mBands.setGains(gains);
        findPreference("equalizer_level").setSummary(boosted
                ? R.string.equalizer_boost_level : R.string.equalizer_flat_level);
        Preference status = findPreference("equalizer_status");
        status.setSummary(mApplication.getStatus());
        findPreference("equalizer_reset").setEnabled(ready);
        findPreference("equalizer_retry").setVisible(ready
                && mApplication.getStatus() == R.string.equalizer_unavailable);
    }
}
