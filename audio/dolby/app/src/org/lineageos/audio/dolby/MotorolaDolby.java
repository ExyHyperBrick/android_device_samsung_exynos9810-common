/* SPDX-License-Identifier: Apache-2.0 */
package org.lineageos.audio.dolby;

import android.media.audiofx.AudioEffect;
import android.os.SystemClock;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

/** Narrow protocol adapter for the pinned v4.2 Motorola payload, not Samsung DAP. */
final class MotorolaDolby {
    static final UUID UUID_DAP = UUID.fromString("9d4921da-8225-4f29-aefa-39537a04bcaa");
    static final int DYNAMIC = 0;
    static final int MUSIC = 2;
    private static final int PARAM_DAP = 5;
    private static final int KEY_ON = 0;
    private static final int KEY_PROFILE_COUNT = 0x03000000;
    private static final int KEY_PROFILE = 0x0a000000;
    private static final int PROFILE_PARAMETER = 0x01000000;
    private static final int VOLUME_LEVELER = 103;
    // DMS acknowledges queued writes before its EventHandler applies them. A successful
    // setParameter() is not a readback fence. Poll only on this app's control worker.
    private static final long READBACK_TIMEOUT_MS = 2000;
    private static final long READBACK_POLL_MS = 20;

    private MotorolaDolby() {}

    private static byte[] ints(int... values) {
        ByteBuffer b = ByteBuffer.allocate(values.length * 4).order(ByteOrder.LITTLE_ENDIAN);
        for (int v : values) b.putInt(v);
        return b.array();
    }

    private static void set(AudioEffect effect, byte[] data, Runnable current) {
        current.run();
        int status = effect.setParameter(PARAM_DAP, data);
        current.run();
        if (status != AudioEffect.SUCCESS) {
            throw new IllegalStateException("Motorola parameter write returned " + status);
        }
    }

    private static int read(AudioEffect effect, int key, Runnable current) {
        current.run();
        byte[] value = ints(key, 0, 0);
        int bytes = effect.getParameter(key + PARAM_DAP, value);
        current.run();
        if (bytes < 4 || bytes > value.length) {
            throw new IllegalStateException("Motorola read 0x" + Integer.toHexString(key)
                    + " returned " + bytes + " bytes/status; DMS may not be ready");
        }
        return ByteBuffer.wrap(value).order(ByteOrder.LITTLE_ENDIAN).getInt();
    }

    static void prepare(AudioEffect effect, int profile, Runnable current) {
        if (profile != MUSIC && profile != DYNAMIC) {
            throw new IllegalArgumentException("Unsupported Dolby profile " + profile);
        }
        int count = read(effect, KEY_PROFILE_COUNT, current);
        if (count <= profile || count > 64) {
            throw new IllegalStateException("DMS reported an invalid profile count: " + count);
        }
        // The stock Motorola wrapper sends these 12-byte commands under parameter 5.
        // Neither Samsung's profile=0 nor its enable=19 protocol applies here.
        set(effect, ints(KEY_ON, 1, 0), current);
        awaitOff(effect, current);
        set(effect, ints(KEY_PROFILE, 1, profile), current);
        // Profile-scoped leveler off, matching the module's default installer policy.
        // Layout: kind, value-count+1, profile, parameter ID, value.
        set(effect, ints(PROFILE_PARAMETER, 2, profile, VOLUME_LEVELER, 0), current);
        // Confirm configuration while internally bypassed, before requesting internal on.
        awaitState(effect, profile, 0, current);
        set(effect, ints(KEY_ON, 1, 1), current);
    }

    private static void stillCurrent(AudioEffect effect, Runnable current) {
        current.run();
        if (!effect.hasControl()) {
            throw new IllegalStateException("Lost Motorola effect control while awaiting DMS");
        }
    }

    private static void pause(AudioEffect effect, Runnable current, long deadline) {
        stillCurrent(effect, current);
        long remaining = deadline - SystemClock.elapsedRealtime();
        if (remaining > 0) SystemClock.sleep(Math.min(READBACK_POLL_MS, remaining));
        stillCurrent(effect, current);
    }

    private static void awaitOff(AudioEffect effect, Runnable current) {
        long deadline = SystemClock.elapsedRealtime() + READBACK_TIMEOUT_MS;
        while (true) {
            stillCurrent(effect, current);
            int on = read(effect, KEY_ON, current);
            stillCurrent(effect, current);
            if (on == 0) return;
            if (SystemClock.elapsedRealtime() >= deadline) {
                throw new IllegalStateException("Motorola internal-off readback timed out: dsOn=" + on);
            }
            pause(effect, current, deadline);
        }
    }

    private static void awaitState(AudioEffect effect, int profile, int expectedOn,
            Runnable current) {
        long deadline = SystemClock.elapsedRealtime() + READBACK_TIMEOUT_MS;
        while (true) {
            stillCurrent(effect, current);
            int actualProfile = read(effect, KEY_PROFILE, current);
            int on = read(effect, KEY_ON, current);
            int leveler = read(effect, PROFILE_PARAMETER + (VOLUME_LEVELER << 16)
                    + (profile << 8), current);
            stillCurrent(effect, current);
            if (actualProfile == profile && on == expectedOn && leveler == 0) return;
            if (SystemClock.elapsedRealtime() >= deadline) {
                throw new IllegalStateException("Motorola readback mismatch after "
                        + READBACK_TIMEOUT_MS + " ms: profile=" + actualProfile + ", dsOn=" + on
                        + ", volumeLeveler=" + leveler + "; expected profile=" + profile
                        + ", dsOn=" + expectedOn + ", volumeLeveler=0");
            }
            // Do not re-send writes, recreate the effect, or accept a stale/malformed read.
            // Mode changes, bypass, server loss and newer selections cancel this wait.
            pause(effect, current, deadline);
        }
    }

    static String verify(AudioEffect effect, int profile, Runnable current) {
        awaitState(effect, profile, 1, current);
        return "Last verified Motorola state: profile=" + profile
                + (profile == MUSIC ? " (Music)" : " (Dynamic)")
                + ", dsOn=1, volumeLeveler=0\nSpeaker tuning: " + speakerTuning(effect, current);
    }

    private static String speakerTuning(AudioEffect effect, Runnable current) {
        // Pinned API: get length with (port << 16) + 2, then name with + 4.
        // Port 0 is internal_speaker. Do not force a Motorola orientation/tuning on other ports.
        current.run();
        byte[] length = new byte[4];
        int bytes = effect.getParameter(2, length);
        current.run();
        if (bytes != 4) throw new IllegalStateException("Motorola tuning length read: " + bytes);
        int n = ByteBuffer.wrap(length).order(ByteOrder.LITTLE_ENDIAN).getInt();
        if (n <= 0 || n > 252) throw new IllegalStateException("Invalid Motorola tuning length " + n);
        byte[] name = new byte[((n + 4) / 4) * 4];
        current.run();
        bytes = effect.getParameter(4, name);
        current.run();
        if (bytes <= 0 || bytes > name.length) {
            throw new IllegalStateException("Motorola tuning-name read: " + bytes);
        }
        String value = new String(name, 0, bytes, StandardCharsets.UTF_8)
                .replace('\0', ' ').trim();
        if (value.isEmpty()) throw new IllegalStateException("Motorola returned an empty tuning name");
        return value;
    }

    static void disableInternal(AudioEffect effect) {
        int status = effect.setParameter(PARAM_DAP, ints(KEY_ON, 1, 0));
        if (status != AudioEffect.SUCCESS) {
            throw new IllegalStateException("Motorola internal disable returned " + status);
        }
    }
}
