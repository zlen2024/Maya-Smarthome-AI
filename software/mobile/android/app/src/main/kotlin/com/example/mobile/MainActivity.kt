package com.example.mobile

import android.app.AppOpsManager
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.os.Process
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.util.Calendar

class MainActivity : FlutterActivity() {
    private val channelName = "maya/usage"
    private val voiceChannel = "maya/voice"
    // Set when the app is launched/resumed via the Quick Settings tile; Flutter
    // pulls (and clears) it on resume and opens the voice overlay.
    private var pendingVoiceLaunch = false

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "hasPermission" -> result.success(hasUsagePermission())
                    "openSettings" -> {
                        startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS))
                        result.success(null)
                    }
                    "getTodayUsageMinutes" -> result.success(todayUsageMinutes())
                    else -> result.notImplemented()
                }
            }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, voiceChannel)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "consumeVoiceLaunch" -> {
                        val v = pendingVoiceLaunch
                        pendingVoiceLaunch = false
                        result.success(v)
                    }
                    else -> result.notImplemented()
                }
            }
        if (intent?.getBooleanExtra("maya_voice", false) == true) pendingVoiceLaunch = true
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.getBooleanExtra("maya_voice", false)) pendingVoiceLaunch = true
    }

    private fun hasUsagePermission(): Boolean {
        val appOps = getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = appOps.checkOpNoThrow(
            AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), packageName
        )
        return mode == AppOpsManager.MODE_ALLOWED
    }

    private fun todayUsageMinutes(): Int {
        val usm = getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val startOfDay = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, 0)
            set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }.timeInMillis
        val now = System.currentTimeMillis()
        val totalMs = usm.queryAndAggregateUsageStats(startOfDay, now)
            .values.sumOf { it.totalTimeInForeground }
        return (totalMs / 60000L).toInt()
    }
}
