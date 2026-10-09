// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.hardware.context;

import android.os.Parcel;
import android.os.Parcelable;

/** Callback payload type retained without registering a Samsung event source. */
public class SemContextEvent implements Parcelable {
    public SemContext semContext = new SemContext();
    private SemContextAutoRotation autoRotation = new SemContextAutoRotation();

    public SemContextEvent() {}

    public SemContextEvent(Parcel source) {
        semContext = SemContext.CREATOR.createFromParcel(source);
        autoRotation = SemContextAutoRotation.CREATOR.createFromParcel(source);
    }

    public SemContextAutoRotation getAutoRotationContext() {
        return autoRotation;
    }

    @Override
    public int describeContents() {
        return 0;
    }

    @Override
    public void writeToParcel(Parcel destination, int flags) {
        semContext.writeToParcel(destination, flags);
        autoRotation.writeToParcel(destination, flags);
    }

    public static final Parcelable.Creator<SemContextEvent> CREATOR =
            new Parcelable.Creator<SemContextEvent>() {
                @Override
                public SemContextEvent createFromParcel(Parcel source) {
                    return new SemContextEvent(source);
                }

                @Override
                public SemContextEvent[] newArray(int size) {
                    return new SemContextEvent[size];
                }
            };
}
