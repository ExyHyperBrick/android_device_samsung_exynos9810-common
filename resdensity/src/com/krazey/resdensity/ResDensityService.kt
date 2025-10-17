package com.krazey.resdensity

import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.display.DisplayManager
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.ServiceManager
import android.os.UserHandle
import android.provider.Settings
import android.util.Log
import android.view.Display
import android.view.IWindowManager
import kotlin.math.abs
import kotlin.math.min

/**
 * Preserve perceived UI size when switching 2960x1440 <-> 2220x1080:
 *  - Scale effective DPI by resolution ratio
 *  - Snap to nearest valid slider tick for that mode
 *  - On 1080p -> 1440p, nudge +2 then back to avoid status-bar padding race
 *
 * Requires sharedUserId="android.uid.system" and platform signing.
 */
class ResDensityService : Service(), DisplayManager.DisplayListener {

    private lateinit var dm: DisplayManager
    private val h = Handler(Looper.getMainLooper())
    private val wm: IWindowManager by lazy {
        IWindowManager.Stub.asInterface(ServiceManager.getService("window"))
    }

    private val TAG = "ResDensity"

    // Persisted key
    private val KEY_LAST_MINPX = "resdensity_last_min_px"

    // Real slider ticks (DPI values)
    private val TICKS_1440 = intArrayOf(392, 448, 504, 560, 612, 666, 720)
    private val TICKS_1080 = intArrayOf(392, 448, 504, 560)

    // Timing
    private val settleDelayMs = 900L     // debounce after flips/config changes
    private val nudgeA_ms = 2200L        // 1080 -> 1440: write target+2
    private val nudgeB_ms = 3000L        // then revert to target
    private val nudgeStep = 2            // ensure a real change

    private var applying = false

    // Listen for configuration changes (mode toggles)
    private val cfgReceiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            Log.i(TAG, "cfgReceiver: ${i.action}")
            scheduleApply()
        }
    }

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "Service created")
        dm = getSystemService(DisplayManager::class.java)

        // Seed last-min if needed
        currentMinPx().takeIf { it > 0 }?.let { curMin ->
            if (Settings.Secure.getInt(contentResolver, KEY_LAST_MINPX, 0) == 0) {
                Settings.Secure.putInt(contentResolver, KEY_LAST_MINPX, curMin)
                Log.i(TAG, "Seed KEY_LAST_MINPX=$curMin")
            }
        }

        dm.registerDisplayListener(this, h)
        registerReceiver(cfgReceiver, IntentFilter(Intent.ACTION_CONFIGURATION_CHANGED))
        scheduleApply()
    }

    override fun onDestroy() {
        try { dm.unregisterDisplayListener(this) } catch (_: Throwable) {}
        try { unregisterReceiver(cfgReceiver) } catch (_: Throwable) {}
        h.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    override fun onBind(i: Intent?): IBinder? = null
    override fun onStartCommand(i: Intent?, flags: Int, startId: Int): Int {
        Log.i(TAG, "onStartCommand")
        return START_STICKY
    }

    // DisplayListener
    override fun onDisplayAdded(id: Int) {}
    override fun onDisplayRemoved(id: Int) {}
    override fun onDisplayChanged(id: Int) {
        if (id != Display.DEFAULT_DISPLAY) return
        val m = dm.getDisplay(id)?.mode
        Log.i(TAG, "onDisplayChanged: ${m?.physicalWidth}x${m?.physicalHeight}")
        scheduleApply()
    }

    private fun scheduleApply() {
        Log.i(TAG, "scheduleApply in ${settleDelayMs}ms")
        h.removeCallbacks(applyOnce)
        h.postDelayed(applyOnce, settleDelayMs)
    }

    private val applyOnce = Runnable {
        Log.i(TAG, "applyOnce START")
        if (applying) {
            Log.i(TAG, "applyOnce: already applying → bail")
            return@Runnable
        }

        val newMin = currentMinPx()
        Log.i(TAG, "currentMinPx=$newMin")
        if (newMin <= 0) return@Runnable

        val cr = contentResolver
        val oldMin = Settings.Secure.getInt(cr, KEY_LAST_MINPX, 0)
        Log.i(TAG, "flip check: oldMin=$oldMin → newMin=$newMin")

        val ticksNow = if (newMin >= 1440) TICKS_1440 else TICKS_1080
        val forcedNow = forcedDpiFromSecure() // effective override if set

        // No real flip?
        if (oldMin == 0 || oldMin == newMin) {
            if (oldMin == 0) {
                Settings.Secure.putInt(cr, KEY_LAST_MINPX, newMin)
                Log.i(TAG, "seeded KEY_LAST_MINPX=$newMin")
            } else {
                Log.d(TAG, "no flip (old==new)")
            }
            Log.d(TAG, "applyOnce END(no-op)")
            return@Runnable
        }

        // --- SCALE-BASED MAPPING ---
        val effNow = if (forcedNow > 0) forcedNow else baseDpi()
        val scale = newMin.toFloat() / oldMin.toFloat()
        val ideal = effNow * scale
        val idxNew = nearestIndexFloat(ticksNow, ideal)
        val target = ticksNow[idxNew]

        Log.i(TAG, "map: effNow=$effNow, scale=$scale ⇒ ideal=$ideal ⇒ idx=$idxNew ⇒ target=$target")

        val goingUp = oldMin < newMin // 1080 -> 1440

        // If already effectively at target, still nudge on upswitch
        val eff = effectiveDpiFast()
        if (abs(eff - target) < 2) {
            if (goingUp) {
                Log.i(TAG, "already at target; upswitch ⇒ schedule +$nudgeStep/back")
                h.postDelayed({
                    try {
                        Log.i(TAG, "nudgeA setForcedDpi(${target + nudgeStep})")
                        setForcedDpi(target + nudgeStep)
                    } catch (t: Throwable) { Log.e(TAG, "nudgeA failed", t) }
                }, nudgeA_ms)
                h.postDelayed({
                    try {
                        Log.i(TAG, "nudgeB setForcedDpi($target)")
                        setForcedDpi(target)
                    } catch (t: Throwable) { Log.e(TAG, "nudgeB failed", t) }
                }, nudgeB_ms)
            }
            Settings.Secure.putInt(cr, KEY_LAST_MINPX, newMin)
            Log.d(TAG, "applyOnce END(no-op at target)")
            return@Runnable
        }

        // Apply target; on upswitch, force a tiny flip then revert
        applying = true
        try {
            Log.i(TAG, "setForcedDpi($target)")
            setForcedDpi(target)
            if (goingUp) {
                Log.i(TAG, "upswitch ⇒ schedule +$nudgeStep/back")
                h.postDelayed({
                    try {
                        Log.i(TAG, "nudgeA setForcedDpi(${target + nudgeStep})")
                        setForcedDpi(target + nudgeStep)
                    } catch (t: Throwable) { Log.e(TAG, "nudgeA failed", t) }
                }, nudgeA_ms)
                h.postDelayed({
                    try {
                        Log.i(TAG, "nudgeB setForcedDpi($target)")
                        setForcedDpi(target)
                    } catch (t: Throwable) { Log.e(TAG, "nudgeB failed", t) }
                }, nudgeB_ms)
            }
        } catch (t: Throwable) {
            Log.e(TAG, "setForcedDpi failed", t)
        } finally {
            applying = false
            Settings.Secure.putInt(cr, KEY_LAST_MINPX, newMin)
            Log.i(TAG, "applyOnce END")
        }
    }

    // ---- helpers ----

    private fun setForcedDpi(target: Int) {
        val even = if ((target and 1) != 0) target + 1 else target
        wm.setForcedDisplayDensityForUser(Display.DEFAULT_DISPLAY, even, UserHandle.USER_CURRENT)
    }

    private fun currentMinPx(): Int {
        val d = dm.getDisplay(Display.DEFAULT_DISPLAY) ?: return 0
        val m = d.mode ?: return 0
        return min(m.physicalWidth, m.physicalHeight)
    }

    private fun baseDpi(): Int =
        try { wm.getBaseDisplayDensity(Display.DEFAULT_DISPLAY) } catch (_: Throwable) { 0 }

    private fun forcedDpiFromSecure(): Int {
        val cr = contentResolver
        val k = Settings.Secure.DISPLAY_DENSITY_FORCED
        val v0 = Settings.Secure.getInt(cr, "${k}_0", 0)
        if (v0 > 0) return v0
        val v = Settings.Secure.getInt(cr, k, 0)
        return if (v > 0) v else 0
    }

    private fun effectiveDpiFast(): Int =
        forcedDpiFromSecure().let { if (it > 0) it else baseDpi() }

    private fun nearestIndex(arr: IntArray, value: Int): Int {
        var best = 0
        var diff = Int.MAX_VALUE
        for (i in arr.indices) {
            val d = abs(arr[i] - value)
            if (d < diff) { diff = d; best = i }
        }
        return best
    }

    private fun nearestIndexFloat(arr: IntArray, value: Float): Int {
        var best = 0
        var diff = Float.MAX_VALUE
        for (i in arr.indices) {
            val d = kotlin.math.abs(arr[i].toFloat() - value)
            if (d < diff) {
                diff = d
                best = i
            }
        }
        return best
    }
}
