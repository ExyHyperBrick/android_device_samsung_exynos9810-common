// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.cover;

import android.os.Binder;
import android.os.Bundle;
import android.os.IBinder;
import android.os.IInterface;
import android.os.RemoteException;
import org.lineageos.camera.compat.OptionalSamsungServices;

public interface INfcLedCoverTouchListenerCallback extends IInterface {
    void onCoverTapLeft() throws RemoteException;
    void onCoverTapMid() throws RemoteException;
    void onCoverTapRight() throws RemoteException;
    void onCoverTouchAccept() throws RemoteException;
    void onCoverTouchReject() throws RemoteException;
    void onSystemCoverEvent(int event, Bundle data) throws RemoteException;

    abstract class Stub extends Binder implements INfcLedCoverTouchListenerCallback {
        public Stub() {
            attachInterface(this,
                    "com.samsung.android.cover.INfcLedCoverTouchListenerCallback");
        }

        @Override
        public IBinder asBinder() {
            return this;
        }

        @Override
        public void onCoverTapLeft() throws RemoteException {}

        @Override
        public void onCoverTapMid() throws RemoteException {}

        @Override
        public void onCoverTapRight() throws RemoteException {}

        @Override
        public void onCoverTouchAccept() throws RemoteException {}

        @Override
        public void onCoverTouchReject() throws RemoteException {}

        @Override
        public void onSystemCoverEvent(int event, Bundle data) throws RemoteException {
            OptionalSamsungServices.unavailable("Samsung cover events");
        }

        // The camera also bundles an older SDK delegate with this overload.
        public void onSystemCoverEvent(int event, int[] data) throws RemoteException {
            OptionalSamsungServices.unavailable("Samsung legacy cover events");
        }
    }
}
