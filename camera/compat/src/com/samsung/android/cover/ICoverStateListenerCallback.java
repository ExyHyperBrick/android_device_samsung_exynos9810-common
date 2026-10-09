// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.cover;

import android.os.Binder;
import android.os.IBinder;
import android.os.IInterface;
import android.os.RemoteException;

public interface ICoverStateListenerCallback extends IInterface {
    String getListenerInfo() throws RemoteException;
    void onCoverAttachStateChanged(boolean attached) throws RemoteException;
    void onCoverSwitchStateChanged(boolean open) throws RemoteException;

    abstract class Stub extends Binder implements ICoverStateListenerCallback {
        public Stub() {
            attachInterface(this, "com.samsung.android.cover.ICoverStateListenerCallback");
        }

        @Override
        public IBinder asBinder() {
            return this;
        }
    }
}
