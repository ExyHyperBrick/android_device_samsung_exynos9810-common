// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.cover;

import android.os.Parcel;
import android.os.Parcelable;

/** App-local state container; no stock cover Binder protocol is implemented. */
public class CoverState implements Parcelable {
    public boolean attached;
    public int color;
    public boolean fakeCover;
    public int fotaMode;
    public int heightPixel;
    public int model;
    public boolean switchState = true;
    public int type = 2;
    public int widthPixel;
    public String smartCoverAppUri;

    public CoverState() {}

    public CoverState(Parcel source) {
        attached = source.readInt() != 0;
        color = source.readInt();
        fakeCover = source.readInt() != 0;
        fotaMode = source.readInt();
        heightPixel = source.readInt();
        model = source.readInt();
        switchState = source.readInt() != 0;
        type = source.readInt();
        widthPixel = source.readInt();
        smartCoverAppUri = source.readString();
    }

    public String getSmartCoverAppUri() {
        return smartCoverAppUri;
    }

    @Override
    public int describeContents() {
        return 0;
    }

    @Override
    public void writeToParcel(Parcel destination, int flags) {
        destination.writeInt(attached ? 1 : 0);
        destination.writeInt(color);
        destination.writeInt(fakeCover ? 1 : 0);
        destination.writeInt(fotaMode);
        destination.writeInt(heightPixel);
        destination.writeInt(model);
        destination.writeInt(switchState ? 1 : 0);
        destination.writeInt(type);
        destination.writeInt(widthPixel);
        destination.writeString(smartCoverAppUri);
    }

    public static final Parcelable.Creator<CoverState> CREATOR =
            new Parcelable.Creator<CoverState>() {
                @Override
                public CoverState createFromParcel(Parcel source) {
                    return new CoverState(source);
                }

                @Override
                public CoverState[] newArray(int size) {
                    return new CoverState[size];
                }
            };
}
