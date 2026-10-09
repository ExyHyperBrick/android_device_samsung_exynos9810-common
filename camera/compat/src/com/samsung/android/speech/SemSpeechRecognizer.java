/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package com.samsung.android.speech;

import com.samsung.android.os.PortDiagnostics;

/** No synthetic recognition results are delivered by the disabled service. */
public final class SemSpeechRecognizer {
    public interface ResultListener {
        void onResults(String[] results);
    }
    public SemSpeechRecognizer() {
        PortDiagnostics.unavailable("Samsung voice shutter recognition");
    }
    public String[] getCommandStringArray(int commandType) {
        // Settings uses these labels even before starting recognition.
        return new String[]{"Smile", "Cheese", "Capture", "Shoot", "Record video"};
    }
    public int getRecognitionResult() { return -1; }
    public void setListener(ResultListener listener) {
        // Do not retain the Camera or invoke a callback for an absent engine.
    }
    public void startRecognition(int commandType) {
        PortDiagnostics.unavailable("Samsung voice shutter recognition");
    }
    public void stopRecognition() {}
}
