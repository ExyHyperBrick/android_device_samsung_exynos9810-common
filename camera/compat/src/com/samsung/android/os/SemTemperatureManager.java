/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package com.samsung.android.os;

/** Samsung's named camera thermistor does not exist as an Android service. */
public final class SemTemperatureManager {
    private SemTemperatureManager() {}
    public static Thermistor getThermistor(int type) {
        PortDiagnostics.unavailable("Samsung camera thermistor");
        return null;
    }
    public static final class Thermistor {
        private Thermistor() {}
        public int getTemperature() {
            throw PortDiagnostics.unsupported("Samsung camera thermistor");
        }
    }
}
