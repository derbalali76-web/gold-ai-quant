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
        // price reached a watch level of today's scenarios: a fact, not a recommendation (once per level per day)
        val price = f.decision.quote
        val prev = if (prefs.contains("last_price")) prefs.getFloat("last_price", 0f).toDouble() else null
        val brief0 = f.decision.brief
        if (price != null && prev != null && brief0 != null && !f.decision.marketClosed) {
            val day = java.time.LocalDate.now().toString()
            val done = prefs.getString("level_alerts", "")!!.split(';').filter { it.startsWith(day) }.toMutableSet()
            brief0.scenarios.forEach { sc ->
                val crossed = SignalWatch.crossed(sc, prev, price)
                val key = "$day|${sc.kind}|${sc.triggerLevel}"
                if (crossed && key !in done) { done += key; notifyLevel(sc) }
            }
            prefs.edit().putString("level_alerts", done.joinToString(";")).apply()
        }
        if (price != null) prefs.edit().putFloat("last_price", price.toFloat()).apply()
        // once a day, in the morning: today's plan (bias + watch scenarios), so the user sees the app at work
        val today = java.time.LocalDate.now().toString()
        val hour = java.time.LocalTime.now().hour
        val b = f.decision.brief
        if (b != null && !f.decision.marketClosed && hour >= 7 && prefs.getString("brief_day", "") != today) {
            prefs.edit().putString("brief_day", today).apply()
            notifyBrief(b)
        }
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

    private fun notifyLevel(sc: Scenario) {
        val ctx = LanguageStore.wrap(applicationContext, LanguageStore.resolve(applicationContext))
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(applicationContext,
                android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val nm = applicationContext.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, ctx.getString(R.string.notif_channel),
            NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(applicationContext, 2,
            Intent(applicationContext, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE)
        val text = ctx.getString(if (sc.kind == "BULL") R.string.notif_level_up else R.string.notif_level_down)
        val n = NotificationCompat.Builder(applicationContext, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_more)
            .setContentTitle(ctx.getString(R.string.notif_level_title, String.format(java.util.Locale.US, "%.2f", sc.trigger), sc.triggerLevel))
            .setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(open).setAutoCancel(true).build()
        NotificationManagerCompat.from(applicationContext).notify(("lvl" + sc.kind + sc.triggerLevel).hashCode(), n)
    }

    private fun notifyBrief(b: Brief) {
        val ctx = LanguageStore.wrap(applicationContext, LanguageStore.resolve(applicationContext))
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(applicationContext,
                android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val nm = applicationContext.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, ctx.getString(R.string.notif_channel),
            NotificationManager.IMPORTANCE_HIGH))
        val p2 = { v: Double -> String.format(java.util.Locale.US, "%.2f", v) }
        val lines = mutableListOf(ctx.getString(when (b.bias) { "UP" -> R.string.brief_bias_up; "DOWN" -> R.string.brief_bias_down; else -> R.string.brief_bias_side }))
        b.scenarios.take(2).forEach { sc ->
            lines += when {
                sc.kind == "BULL" && sc.target != null -> ctx.getString(R.string.sc_bull, p2(sc.trigger), sc.triggerLevel, p2(sc.target), sc.targetLevel ?: "")
                sc.kind == "BULL" -> ctx.getString(R.string.sc_bull_open, p2(sc.trigger), sc.triggerLevel)
                sc.target != null -> ctx.getString(R.string.sc_bear, p2(sc.trigger), sc.triggerLevel, p2(sc.target), sc.targetLevel ?: "")
                else -> ctx.getString(R.string.sc_bear_open, p2(sc.trigger), sc.triggerLevel)
            }
        }
        lines += ctx.getString(R.string.brief_title)
        val open = PendingIntent.getActivity(applicationContext, 1,
            Intent(applicationContext, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(applicationContext, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_more)
            .setContentTitle(ctx.getString(R.string.notif_brief_title))
            .setContentText(lines.getOrElse(1) { lines[0] })
            .setStyle(NotificationCompat.BigTextStyle().bigText(lines.joinToString("\n")))
            .setContentIntent(open).setAutoCancel(true).build()
        NotificationManagerCompat.from(applicationContext).notify(BRIEF_ID, n)
    }

    companion object {
        private const val BRIEF_ID = 4711
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
