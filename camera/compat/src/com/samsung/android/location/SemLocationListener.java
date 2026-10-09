// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package com.samsung.android.location;

import android.location.Address;
import android.location.Location;

public interface SemLocationListener {
    void onLocationAvailable(Location[] locations);
    void onLocationChanged(Location location, Address address);
}
