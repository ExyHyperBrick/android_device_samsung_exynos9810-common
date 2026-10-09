// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.hardware.context;

import android.os.Bundle;
import android.os.Parcel;
import android.os.Parcelable;

public class SemContextEventContext implements Parcelable {
    protected Bundle values = new Bundle();

    public SemContextEventContext() {}

    public SemContextEventContext(Parcel source) {
        Bundle parcelValues = source.readBundle(getClass().getClassLoader());
        if (parcelValues != null) {
            values = parcelValues;
        }
    }

    public void setValues(Bundle data) {
        values = data == null ? new Bundle() : new Bundle(data);
    }

    @Override
    public int describeContents() {
        return 0;
    }

    @Override
    public void writeToParcel(Parcel destination, int flags) {
        destination.writeBundle(values);
    }

    public static final Parcelable.Creator<SemContextEventContext> CREATOR =
            new Parcelable.Creator<SemContextEventContext>() {
                @Override
                public SemContextEventContext createFromParcel(Parcel source) {
                    return new SemContextEventContext(source);
                }

                @Override
                public SemContextEventContext[] newArray(int size) {
                    return new SemContextEventContext[size];
                }
            };
}
