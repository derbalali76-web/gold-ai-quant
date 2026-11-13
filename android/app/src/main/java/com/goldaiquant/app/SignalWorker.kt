package com.goldaiquant.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/** Background check (every 15 min): announces a NEW validated BUY/SELL once. Never trades, never shows numbers it
 *  did not receive from the server. */
class SignalWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences("gold_ai_quant", Context.MODE_PRIVATE)
        if (!prefs.getBoolean("notify", false)) return Result.success()
        val url = prefs.getString("server_url", null) ?: return Result.success()
        val f = try { ApiClient(url, prefs.getString("token", "") ?: "").decision("LIVE", 0) } catch (e: Exception) {
            return Result.success() // try again at the next period
        }
        val last = prefs.getString("notified", "")!!.split(';').filter { it.contains('=') }
            .associate { it.substringBefore('=') to it.substringAfter('=') }
        val (fresh, memory) = SignalWatch.diff(f.decision, last)
        prefs.edit().putString("notified", memory.entries.joinToString(";") { "${it.key}=${it.value}" })
            .putString("last_decision", f.raw).putLong("last_received", System.currentTimeMillis()).apply()
        if (fresh.isNotEmpty()) notify(fresh)
        return Result.success()
    }

    private fun notify(signals: List<SignalWatch.Signal>) {
        val ctx = LanguageStore.wrap(applicationContext, LanguageStore.resolve(applicationContext))
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(applicationContext,
                android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val nm = applicationContext.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, ctx.getString(R.string.notif_channel),
            NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(applicationContext, 0,
            Intent(applicationContext, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE)
        signals.forEach { sg ->
            val h = ctx.getString(when (sg.horizon) { "WEEK" -> R.string.h_week; "MONTH" -> R.string.h_month; else -> R.string.h_hours })
            val a = ctx.getString(if (sg.action == Action.BUY) R.string.a_buy else R.string.a_sell)
            val n = NotificationCompat.Builder(applicationContext, CHANNEL)
                .setSmallIcon(android.R.drawable.stat_notify_more)
                .setContentTitle(ctx.getString(R.string.notif_title, a, h))
                .setContentText(ctx.getString(R.string.notif_text))
                .setStyle(NotificationCompat.BigTextStyle().bigText(ctx.getString(R.string.notif_text)))
                .setContentIntent(open).setAutoCancel(true).build()
            NotificationManagerCompat.from(applicationContext).notify(sg.horizon.hashCode(), n)
        }
    }

    companion object {
        private const val CHANNEL = "signals"
        private const val WORK = "signal-watch"

        fun schedule(ctx: Context, on: Boolean) {
            val wm = WorkManager.getInstance(ctx)
            if (!on) { wm.cancelUniqueWork(WORK); return }
            val req = PeriodicWorkRequestBuilder<SignalWorker>(15, TimeUnit.MINUTES)
                .setConstraints(androidx.work.Constraints.Builder()
                    .setRequiredNetworkType(androidx.work.NetworkType.CONNECTED).build()).build()
            wm.enqueueUniquePeriodicWork(WORK, ExistingPeriodicWorkPolicy.UPDATE, req)
        }
    }
}
