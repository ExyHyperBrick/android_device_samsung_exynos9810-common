// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.desktopmode;

import android.os.Parcel;
import android.os.Parcelable;

/** Disabled DeX state; no Samsung desktop-mode service is present. */
public class SemDesktopModeState implements Parcelable {
    public int enabled = 2;
    public int state;
    private int displayType;

    public SemDesktopModeState() {}

    public SemDesktopModeState(Parcel source) {
        enabled = source.readInt();
        state = source.readInt();
        displayType = source.readInt();
    }

    @Override
    public int describeContents() {
        return 0;
    }

    @Override
    public void writeToParcel(Parcel destination, int flags) {
        destination.writeInt(enabled);
        destination.writeInt(state);
        destination.writeInt(displayType);
    }

    public static final Parcelable.Creator<SemDesktopModeState> CREATOR =
            new Parcelable.Creator<SemDesktopModeState>() {
                @Override
                public SemDesktopModeState createFromParcel(Parcel source) {
                    return new SemDesktopModeState(source);
                }

                @Override
                public SemDesktopModeState[] newArray(int size) {
                    return new SemDesktopModeState[size];
                }
            };
}
