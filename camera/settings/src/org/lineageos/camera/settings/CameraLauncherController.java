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
    private static final String PACKAGE = "com.sec.android.app.camera";
    private static final String CAMERA = PACKAGE + ".Camera";
    private static final ComponentName LAUNCHER =
            new ComponentName(PACKAGE, PACKAGE + ".LauncherActivity");
    private final PackageManager mPackages;
    private final UserManager mUsers;

    CameraLauncherController(Context context) {
        // Use this process's user. Never modify another user's component state.
        mPackages = context.getPackageManager();
        mUsers = context.getSystemService(UserManager.class);
    }

    private ApplicationInfo cameraInfo() throws PackageManager.NameNotFoundException {
        ApplicationInfo info = mPackages.getApplicationInfo(PACKAGE,
                PackageManager.MATCH_DISABLED_COMPONENTS);
        if ((info.flags & ApplicationInfo.FLAG_INSTALLED) == 0) {
            throw new PackageManager.NameNotFoundException("Camera not installed for this user");
        }
        return info;
    }

    boolean isCameraAvailable() {
        try {
            cameraInfo();
            return true;
        } catch (PackageManager.NameNotFoundException | RuntimeException e) {
            return false;
        }
    }

    boolean isCameraEnabled() {
        try {
            return cameraInfo().enabled;
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
            cameraInfo();
            mPackages.setApplicationEnabledSetting(PACKAGE,
                    enabled ? PackageManager.COMPONENT_ENABLED_STATE_ENABLED
                            : PackageManager.COMPONENT_ENABLED_STATE_DISABLED_USER,
                    0);
            return isCameraAvailable() && isCameraEnabled() == enabled;
        } catch (PackageManager.NameNotFoundException | RuntimeException e) {
            return false;
        }
    }

    private ActivityInfo launcherInfo() throws PackageManager.NameNotFoundException {
        ActivityInfo info = mPackages.getActivityInfo(LAUNCHER,
                PackageManager.MATCH_DISABLED_COMPONENTS);
        if (!CAMERA.equals(info.targetActivity)) {
            throw new PackageManager.NameNotFoundException("Launcher alias unavailable");
        }
        return info;
    }

    boolean isAvailable() {
        try {
            launcherInfo();
            return isCameraEnabled();
        } catch (PackageManager.NameNotFoundException | RuntimeException e) {
            return false;
        }
    }

    boolean isShown() {
        try {
            ActivityInfo info = launcherInfo();
            int state = mPackages.getComponentEnabledSetting(LAUNCHER);
            return state == PackageManager.COMPONENT_ENABLED_STATE_ENABLED
                    || (state == PackageManager.COMPONENT_ENABLED_STATE_DEFAULT && info.enabled);
        } catch (PackageManager.NameNotFoundException | RuntimeException e) {
            return false;
        }
    }

    boolean setShown(boolean shown) {
        try {
            if (!canChangeState() || !isAvailable()) return false;
            launcherInfo();
            mPackages.setComponentEnabledSetting(LAUNCHER,
                    shown ? PackageManager.COMPONENT_ENABLED_STATE_ENABLED
                            : PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
                    PackageManager.DONT_KILL_APP);
            return isAvailable() && isShown() == shown;
        } catch (PackageManager.NameNotFoundException | RuntimeException e) {
            return false;
        }
    }
}
