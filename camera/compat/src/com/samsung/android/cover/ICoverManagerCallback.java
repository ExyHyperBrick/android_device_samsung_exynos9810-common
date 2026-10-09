// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.cover;

import android.os.Binder;
import android.os.IBinder;
import android.os.IInterface;
import android.os.RemoteException;

public interface ICoverManagerCallback extends IInterface {
    void coverCallback(CoverState state) throws RemoteException;
    String getListenerInfo() throws RemoteException;

    abstract class Stub extends Binder implements ICoverManagerCallback {
        public Stub() {
            attachInterface(this, "com.samsung.android.cover.ICoverManagerCallback");
        }

        @Override
        public IBinder asBinder() {
            return this;
        }
    }
}
