/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.equalizer;

import android.content.ComponentName;
import android.content.Context;
import android.content.pm.PackageManager;

final class EqualizerLauncherController {
    private final PackageManager mPackages;
    private final ComponentName mLauncher;

    EqualizerLauncherController(Context context) {
        mPackages = context.getPackageManager();
        mLauncher = new ComponentName(context, "org.lineageos.audio.equalizer.EqualizerLauncher");
    }

    boolean isShown() {
        try {
            return readShown();
        } catch (RuntimeException e) {
            return false;
        }
    }

    private boolean readShown() {
        return mPackages.getComponentEnabledSetting(mLauncher)
                == PackageManager.COMPONENT_ENABLED_STATE_ENABLED;
    }

    boolean setShown(boolean shown) {
        try {
            if (readShown() == shown) return true;
            mPackages.setComponentEnabledSetting(mLauncher,
                    shown ? PackageManager.COMPONENT_ENABLED_STATE_ENABLED
                            : PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
                    PackageManager.DONT_KILL_APP);
            return readShown() == shown;
        } catch (RuntimeException e) {
            return false;
        }
    }
}
