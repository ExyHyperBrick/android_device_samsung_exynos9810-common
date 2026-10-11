/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.equalizer;

import android.content.Context;
import android.util.AttributeSet;
import android.view.View;
import android.widget.SeekBar;
import android.widget.TextView;

import androidx.preference.Preference;
import androidx.preference.PreferenceViewHolder;

import java.util.Arrays;

public final class EqualizerBandsPreference extends Preference {
    private static final int[] SLIDERS = {R.id.equalizer_slider_0, R.id.equalizer_slider_1,
            R.id.equalizer_slider_2, R.id.equalizer_slider_3, R.id.equalizer_slider_4};
    private static final int[] GAINS = {R.id.equalizer_gain_0, R.id.equalizer_gain_1,
            R.id.equalizer_gain_2, R.id.equalizer_gain_3, R.id.equalizer_gain_4};
    private static final int[] FREQUENCIES = {R.string.equalizer_band_60,
            R.string.equalizer_band_230, R.string.equalizer_band_910,
            R.string.equalizer_band_3600, R.string.equalizer_band_14000};
    private final int[] mGains = new int[OutputEqualizer.BAND_COUNT];
    private OnBandChangeListener mListener;

    public interface OnBandChangeListener {
        void onBandChange(int band, int gain);
    }

    public EqualizerBandsPreference(Context context, AttributeSet attrs) {
        super(context, attrs);
        setLayoutResource(R.layout.equalizer_bands);
        setSelectable(false);
        setPersistent(false);
    }

    public void setOnBandChangeListener(OnBandChangeListener listener) {
        mListener = listener;
    }

    public void setGains(int[] gains) {
        if (!Arrays.equals(mGains, gains)) {
            System.arraycopy(gains, 0, mGains, 0, mGains.length);
            notifyChanged();
        }
    }

    @Override
    public void onBindViewHolder(PreferenceViewHolder holder) {
        super.onBindViewHolder(holder);
        for (int band = 0; band < mGains.length; ++band) {
            final int index = band;
            VerticalSeekBar vertical = (VerticalSeekBar) holder.findViewById(SLIDERS[band]);
            SeekBar slider = vertical.getSeekBar();
            TextView gainLabel = (TextView) holder.findViewById(GAINS[band]);
            gainLabel.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            slider.setOnSeekBarChangeListener(null);
            vertical.setEnabled(isEnabled());
            slider.setEnabled(isEnabled());
            slider.setContentDescription(getContext().getString(FREQUENCIES[band]));
            slider.setProgress(mGains[band]);
            updateGainLabel(slider, gainLabel, mGains[band]);
            slider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
                @Override
                public void onProgressChanged(SeekBar seekBar, int gain, boolean fromUser) {
                    updateGainLabel(seekBar, gainLabel, gain);
                    if (fromUser && mListener != null) {
                        mGains[index] = gain;
                        mListener.onBandChange(index, gain);
                    }
                }
                @Override public void onStartTrackingTouch(SeekBar seekBar) {}
                @Override public void onStopTrackingTouch(SeekBar seekBar) {}
            });
        }
    }

    private void updateGainLabel(SeekBar slider, TextView label, int gain) {
        String text = getContext().getString(R.string.equalizer_gain, gain);
        label.setText(text);
        slider.setStateDescription(text);
    }
}
