// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.cover;

import android.content.ComponentName;
import android.os.Binder;
import android.os.Bundle;
import android.os.IBinder;
import android.os.IInterface;
import android.os.RemoteException;
import org.lineageos.camera.compat.OptionalSamsungServices;

public interface ICoverManager extends IInterface {
    void addLedNotification(Bundle data) throws RemoteException;
    boolean disableLcdOffByCover(IBinder token, ComponentName component)
            throws RemoteException;
    boolean enableLcdOffByCover(IBinder token, ComponentName component)
            throws RemoteException;
    CoverState getCoverState() throws RemoteException;
    void registerCallback(IBinder callback, ComponentName component)
            throws RemoteException;
    void registerListenerCallback(IBinder callback, ComponentName component, int type)
            throws RemoteException;
    void registerNfcTouchListenerCallback(int type, IBinder callback,
            ComponentName component) throws RemoteException;
    void removeLedNotification(Bundle data) throws RemoteException;
    void sendDataToCover(int command, byte[] data) throws RemoteException;
    void sendDataToNfcLedCover(int command, byte[] data) throws RemoteException;
    void sendSystemEvent(Bundle event) throws RemoteException;
    boolean unregisterCallback(IBinder callback) throws RemoteException;
    boolean unregisterNfcTouchListenerCallback(IBinder callback) throws RemoteException;

    abstract class Stub extends Binder implements ICoverManager {
        private static final String DESCRIPTOR = "com.samsung.android.cover.ICoverManager";

        public Stub() {
            attachInterface(this, DESCRIPTOR);
        }

        public static ICoverManager asInterface(IBinder binder) {
            if (binder == null) {
                OptionalSamsungServices.unavailable("Samsung cover service");
                return null;
            }
            IInterface local = binder.queryLocalInterface(DESCRIPTOR);
            if (local instanceof ICoverManager) {
                return (ICoverManager) local;
            }
            OptionalSamsungServices.unavailable("Samsung remote cover Binder protocol");
            return null;
        }

        @Override
        public IBinder asBinder() {
            return this;
        }
    }
}
