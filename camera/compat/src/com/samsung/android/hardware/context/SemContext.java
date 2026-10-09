// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.hardware.context;

import android.os.Parcel;
import android.os.Parcelable;

public class SemContext implements Parcelable {
    private int type;

    public SemContext() {}

    public SemContext(Parcel source) {
        type = source.readInt();
    }

    public int getType() {
        return type;
    }

    @Override
    public int describeContents() {
        return 0;
    }

    @Override
    public void writeToParcel(Parcel destination, int flags) {
        destination.writeInt(type);
    }

    public static final Parcelable.Creator<SemContext> CREATOR =
            new Parcelable.Creator<SemContext>() {
                @Override
                public SemContext createFromParcel(Parcel source) {
                    return new SemContext(source);
                }

                @Override
                public SemContext[] newArray(int size) {
                    return new SemContext[size];
                }
            };
}
