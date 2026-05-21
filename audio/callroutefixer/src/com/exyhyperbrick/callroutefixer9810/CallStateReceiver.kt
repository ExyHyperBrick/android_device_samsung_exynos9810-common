package com.exyhyperbrick.callroutefixer9810

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.AudioSystem
import android.os.SystemClock
import android.telephony.TelephonyManager
import android.util.Log
import java.util.concurrent.atomic.AtomicLong
import kotlin.concurrent.thread

class CallStateReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_LOCKED_BOOT_COMPLETED,
            Intent.ACTION_BOOT_COMPLETED -> {
                Log.i(TAG, "ready")
            }
            TelephonyManager.ACTION_PHONE_STATE_CHANGED -> {
                val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE)
                if (state != TelephonyManager.EXTRA_STATE_OFFHOOK) {
                    return
                }

                val now = SystemClock.elapsedRealtime()
                val previous = sLastRefreshMs.getAndSet(now)
                if (now - previous < MIN_REFRESH_INTERVAL_MS) {
                    Log.i(TAG, "OFFHOOK ignored, refresh already scheduled")
                    return
                }

                val pendingResult = goAsync()
                val appContext = context.applicationContext

                thread(name = "CallRouteFixer9810") {
                    try {
                        /*
                         * Early attempts only re-apply the selected route.  On
                         * exynos9810 this can still leave the live
                         * VOICE_COMMUNICATION RecordThread without an output
                         * reference.  Later attempts perform the same short
                         * speaker -> earpiece pulse that users already used as
                         * a manual workaround, after the call input is expected
                         * to be open.
                         */
                        refreshAfterDelay(appContext, 600, pulseSpeaker = false)
                        refreshAfterDelay(appContext, 1400, pulseSpeaker = false)
                        refreshAfterDelay(appContext, 2600, pulseSpeaker = true)
                        refreshAfterDelay(appContext, 4200, pulseSpeaker = true)
                    } finally {
                        pendingResult.finish()
                    }
                }
            }
        }
    }

    private fun refreshAfterDelay(context: Context, delayMs: Long, pulseSpeaker: Boolean) {
        SystemClock.sleep(delayMs)
        refreshCommunicationRoute(context, delayMs, pulseSpeaker)
    }

    private fun refreshCommunicationRoute(
        context: Context,
        delayMs: Long,
        pulseSpeaker: Boolean,
    ) {
        val audioManager = context.getSystemService(AudioManager::class.java) ?: run {
            Log.w(TAG, "AudioManager unavailable")
            return
        }

        val mode = audioManager.mode
        if (mode != AudioManager.MODE_IN_CALL && mode != AudioManager.MODE_IN_COMMUNICATION) {
            Log.i(TAG, "skip delay=${delayMs}ms mode=$mode")
            return
        }

        val currentForce = getCommunicationForceUse()
        val currentDevice = audioManager.communicationDevice
        val targetDevice = currentDevice ?: selectDefaultCommunicationDevice(audioManager)

        if (targetDevice == null) {
            Log.w(TAG, "no communication device available delay=${delayMs}ms mode=$mode")
            return
        }

        if (pulseSpeaker && targetDevice.type == AudioDeviceInfo.TYPE_BUILTIN_EARPIECE) {
            pulseSpeakerThenRestore(
                audioManager = audioManager,
                delayMs = delayMs,
                mode = mode,
                currentForce = currentForce,
                currentDevice = currentDevice,
                targetDevice = targetDevice,
            )
            return
        }

        reapplyCommunicationForceUse(currentForce)

        val ok = audioManager.setCommunicationDevice(targetDevice)
        Log.i(
            TAG,
            "refresh delay=${delayMs}ms mode=$mode " +
                "current=${currentDevice?.toLogString() ?: "null"} " +
                "target=${targetDevice.toLogString()} force=$currentForce result=$ok"
        )
    }

    private fun pulseSpeakerThenRestore(
        audioManager: AudioManager,
        delayMs: Long,
        mode: Int,
        currentForce: Int,
        currentDevice: AudioDeviceInfo?,
        targetDevice: AudioDeviceInfo,
    ) {
        val speakerDevice = audioManager.availableCommunicationDevices
            .firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }

        if (speakerDevice == null) {
            Log.w(TAG, "no speaker device available for pulse delay=${delayMs}ms")
            reapplyCommunicationForceUse(currentForce)
            val ok = audioManager.setCommunicationDevice(targetDevice)
            Log.i(TAG, "restore-only target=${targetDevice.toLogString()} result=$ok")
            return
        }

        Log.i(
            TAG,
            "speaker pulse begin delay=${delayMs}ms mode=$mode " +
                "current=${currentDevice?.toLogString() ?: "null"} " +
                "speaker=${speakerDevice.toLogString()} target=${targetDevice.toLogString()} " +
                "force=$currentForce"
        )

        runCatching {
            AudioSystem.setForceUse(AudioSystem.FOR_COMMUNICATION, AudioSystem.FORCE_SPEAKER)
        }.onFailure {
            Log.w(TAG, "failed to force speaker for communication", it)
        }

        val speakerOk = audioManager.setCommunicationDevice(speakerDevice)
        SystemClock.sleep(SPEAKER_PULSE_MS)

        reapplyCommunicationForceUse(currentForce)
        val targetOk = audioManager.setCommunicationDevice(targetDevice)

        Log.i(
            TAG,
            "speaker pulse done delay=${delayMs}ms " +
                "speakerResult=$speakerOk targetResult=$targetOk " +
                "target=${targetDevice.toLogString()} force=$currentForce"
        )
    }

    private fun getCommunicationForceUse(): Int =
        runCatching {
            AudioSystem.getForceUse(AudioSystem.FOR_COMMUNICATION)
        }.getOrElse {
            Log.w(TAG, "failed to read communication force use", it)
            AudioSystem.FORCE_NONE
        }

    private fun reapplyCommunicationForceUse(force: Int) {
        runCatching {
            AudioSystem.setForceUse(AudioSystem.FOR_COMMUNICATION, force)
            Log.i(TAG, "reapplied communication force=$force")
        }.onFailure {
            Log.w(TAG, "failed to reapply communication force use", it)
        }
    }

    private fun selectDefaultCommunicationDevice(audioManager: AudioManager): AudioDeviceInfo? {
        val devices = audioManager.availableCommunicationDevices

        return devices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_EARPIECE }
            ?: devices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }
    }

    private fun AudioDeviceInfo.toLogString(): String =
        "type=$type/id=$id/product=${productName ?: "unknown"}"

    companion object {
        private const val TAG = "CallRouteFixer9810"
        private const val MIN_REFRESH_INTERVAL_MS = 3_000L
        private const val SPEAKER_PULSE_MS = 160L

        private val sLastRefreshMs = AtomicLong(0L)
    }
}
