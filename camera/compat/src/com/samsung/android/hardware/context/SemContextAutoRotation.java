// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.hardware.context;

import android.os.Parcel;
import android.os.Parcelable;

public class SemContextAutoRotation extends SemContextEventContext {
    public SemContextAutoRotation() {}

    public SemContextAutoRotation(Parcel source) {
        super(source);
    }

    public int getAngle() {
        return values.getInt("Angle", 0);
    }

    public static final Parcelable.Creator<SemContextAutoRotation> CREATOR =
            new Parcelable.Creator<SemContextAutoRotation>() {
                @Override
                public SemContextAutoRotation createFromParcel(Parcel source) {
                    return new SemContextAutoRotation(source);
                }

                @Override
                public SemContextAutoRotation[] newArray(int size) {
                    return new SemContextAutoRotation[size];
                }
            };
}
