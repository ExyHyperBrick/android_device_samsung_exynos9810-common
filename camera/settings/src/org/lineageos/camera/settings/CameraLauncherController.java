/*
 * SPDX-FileCopyrightText: 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.camera.settings;

import android.content.ComponentName;
import android.content.Context;
import android.content.pm.ActivityInfo;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.UserManager;

final class CameraLauncherController {
    private static final String SAMSUNG_PACKAGE = "com.sec.android.app.camera";
    private static final String APERTURE_PACKAGE = "org.lineageos.aperture";
    private static final ComponentName SAMSUNG_LAUNCHER =
            new ComponentName(SAMSUNG_PACKAGE, SAMSUNG_PACKAGE + ".LauncherActivity");
    private static final ComponentName APERTURE_LAUNCHER =
            new ComponentName(APERTURE_PACKAGE, APERTURE_PACKAGE + ".CameraLauncher");
    private final PackageManager mPackages;
    private final UserManager mUsers;

    CameraLauncherController(Context context) {
        // Use this process's user. Never modify another user's component state.
        mPackages = context.getPackageManager();
        mUsers = context.getSystemService(UserManager.class);
    }

    private ApplicationInfo applicationInfo(String packageName)
            throws PackageManager.NameNotFoundException {
        ApplicationInfo info = mPackages.getApplicationInfo(packageName,
                PackageManager.MATCH_DISABLED_COMPONENTS);
        if ((info.flags & ApplicationInfo.FLAG_INSTALLED) == 0) {
            throw new PackageManager.NameNotFoundException("Camera not installed for this user");
        }
        return info;
    }

    boolean isCameraAvailable() {
        try {
            applicationInfo(SAMSUNG_PACKAGE);
            return true;
        } catch (PackageManager.NameNotFoundException | RuntimeException e) {
            return false;
        }
    }

    boolean isCameraEnabled() {
        try {
            return applicationInfo(SAMSUNG_PACKAGE).enabled;
        } catch (PackageManager.NameNotFoundException | RuntimeException e) {
            return false;
        }
    }

    boolean canChangeState() {
        try {
            return mUsers != null && !mUsers.hasUserRestriction(UserManager.DISALLOW_APPS_CONTROL);
        } catch (RuntimeException e) {
            return false;
        }
    }

    boolean setCameraEnabled(boolean enabled) {
        try {
            if (!canChangeState()) return false;
            applicationInfo(SAMSUNG_PACKAGE);
            if (enabled) {
                try {
                    launcherInfo(SAMSUNG_LAUNCHER, SAMSUNG_PACKAGE + ".Camera");
                    // Restore icons hidden by the previous, separate launcher switch.
                    mPackages.setComponentEnabledSetting(SAMSUNG_LAUNCHER,
                            PackageManager.COMPONENT_ENABLED_STATE_ENABLED,
                            PackageManager.DONT_KILL_APP);
                    if (mPackages.getComponentEnabledSetting(SAMSUNG_LAUNCHER)
                            != PackageManager.COMPONENT_ENABLED_STATE_ENABLED) return false;
                } catch (PackageManager.NameNotFoundException e) {
                    // Older camera packages do not have a separate launcher alias.
                }
            }
            mPackages.setApplicationEnabledSetting(SAMSUNG_PACKAGE,
                    enabled ? PackageManager.COMPONENT_ENABLED_STATE_ENABLED
                            : PackageManager.COMPONENT_ENABLED_STATE_DISABLED_USER,
                    0);
            return isCameraAvailable() && isCameraEnabled() == enabled;
        } catch (PackageManager.NameNotFoundException | RuntimeException e) {
            return false;
        }
    }

    private ActivityInfo launcherInfo(ComponentName launcher, String target)
            throws PackageManager.NameNotFoundException {
        ActivityInfo info = mPackages.getActivityInfo(launcher,
                PackageManager.MATCH_DISABLED_COMPONENTS);
        if (!target.equals(info.targetActivity)) {
            throw new PackageManager.NameNotFoundException("Launcher alias unavailable");
        }
        return info;
    }

    boolean isApertureAvailable() {
        try {
            launcherInfo(APERTURE_LAUNCHER, APERTURE_PACKAGE + ".CameraActivity");
            return applicationInfo(APERTURE_PACKAGE).enabled;
        } catch (PackageManager.NameNotFoundException | RuntimeException e) {
            return false;
        }
    }

    boolean isApertureHidden() {
        try {
            ActivityInfo info = launcherInfo(APERTURE_LAUNCHER,
                    APERTURE_PACKAGE + ".CameraActivity");
            int state = mPackages.getComponentEnabledSetting(APERTURE_LAUNCHER);
            return state != PackageManager.COMPONENT_ENABLED_STATE_ENABLED
                    && (state != PackageManager.COMPONENT_ENABLED_STATE_DEFAULT || !info.enabled);
        } catch (PackageManager.NameNotFoundException | RuntimeException e) {
            return false;
        }
    }

    boolean setApertureHidden(boolean hidden) {
        try {
            if (!canChangeState() || !isApertureAvailable()) return false;
            mPackages.setComponentEnabledSetting(APERTURE_LAUNCHER,
                    hidden ? PackageManager.COMPONENT_ENABLED_STATE_DISABLED
                            : PackageManager.COMPONENT_ENABLED_STATE_ENABLED,
                    PackageManager.DONT_KILL_APP);
            return isApertureAvailable() && isApertureHidden() == hidden;
        } catch (RuntimeException e) {
            return false;
        }
    }
}
