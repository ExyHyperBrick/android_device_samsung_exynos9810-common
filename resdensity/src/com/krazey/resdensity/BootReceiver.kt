package com.krazey.resdensity

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(c: Context, i: Intent) {
        Log.i("ResDensity", "BootReceiver: ${i.action}")
        c.startService(Intent(c, ResDensityService::class.java))
    }
}
