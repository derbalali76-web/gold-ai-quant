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
        val api = ApiClient(url, prefs.getString("token", "") ?: "")
        for (asset in alertAssets(prefs)) {  // only the markets this trader follows
            val f = try { api.decision("LIVE", 0, asset) } catch (e: Exception) { continue }
            check(prefs, asset, f)
        }
        return Result.success()
    }

    private fun check(prefs: android.content.SharedPreferences, asset: String, f: Fetched) {
        val sfx = if (asset == "XAU") "" else "_$asset"
        val label = if (asset == "XAU") "XAU/USD" else "$asset/USD"
        // 1) a NEW validated recommendation (only ever exists after out-of-sample validation)
        val last = prefs.getString("notified$sfx", "")!!.split(';').filter { it.contains('=') }
            .associate { it.substringBefore('=') to it.substringAfter('=') }
        val (fresh, memory) = SignalWatch.diff(f.decision, last)
        prefs.edit().putString("notified$sfx", memory.entries.joinToString(";") { "${it.key}=${it.value}" })
            .putString(if (asset == "XAU") "last_decision" else "last_decision_$asset", f.raw)
            .putLong("last_received", System.currentTimeMillis()).apply()
        if (fresh.isNotEmpty()) notify(fresh, label)
        val day = java.time.LocalDate.now().toString()
        val b = f.decision.brief
        if (b != null && !f.decision.marketClosed) {
            // 2) scenario triggered: the last closed hour broke a level (once per level and hour)
            val seen = prefs.getString("events$sfx", "")!!.split(';').filter { it.startsWith(day) }.toMutableSet()
            b.events.forEach { e ->
                val key = "$day|${e.hourUtc}|${e.kind}|${e.levelName}"
                if (key !in seen) { seen += key; notifyEvent(e, label) }
            }
            prefs.edit().putString("events$sfx", seen.joinToString(";")).apply()
            // 3) price reached a watch level of today's scenarios (once per level per day)
            val price = f.decision.quote
            val pk = "last_price$sfx"
            val prev = if (prefs.contains(pk)) prefs.getFloat(pk, 0f).toDouble() else null
            if (price != null && prev != null) {
                val done = prefs.getString("level_alerts$sfx", "")!!.split(';').filter { it.startsWith(day) }.toMutableSet()
                b.scenarios.forEach { sc ->
                    val key = "$day|${sc.kind}|${sc.triggerLevel}"
                    if (SignalWatch.crossed(sc, prev, price) && key !in done) { done += key; notifyLevel(sc, label) }
                }
                prefs.edit().putString("level_alerts$sfx", done.joinToString(";")).apply()
            }
            if (price != null) prefs.edit().putFloat(pk, price.toFloat()).apply()
            // 4) once a day, in the morning: today's plan for this asset
            if (java.time.LocalTime.now().hour >= 7 && prefs.getString("brief_day$sfx", "") != day) {
                prefs.edit().putString("brief_day$sfx", day).apply()
                notifyBrief(b, label)
            }
        }
    }

    private fun ready(ctx: Context): Boolean {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(applicationContext,
                android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return false
        applicationContext.getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, ctx.getString(R.string.notif_channel), NotificationManager.IMPORTANCE_HIGH))
        return true
    }

    private fun notifyEvent(e: ScenarioEvent, label: String) {
        val ctx = LanguageStore.wrap(applicationContext, LanguageStore.resolve(applicationContext))
        if (!ready(ctx)) return
        val p2 = { v: Double -> String.format(java.util.Locale.US, "%.2f", v) }
        val title = ctx.getString(if (e.kind == "BULL") R.string.notif_trig_up else R.string.notif_trig_down, label)
        val text = ctx.getString(if (e.kind == "BULL") R.string.notif_trig_up_text else R.string.notif_trig_down_text,
            p2(e.level), e.levelName, e.target?.let(p2) ?: "—", e.targetName ?: "") + "\n" + ctx.getString(R.string.pos_watch_note)
        val open = PendingIntent.getActivity(applicationContext, 3,
            Intent(applicationContext, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(applicationContext, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_more).setContentTitle(title)
            .setContentText(text.substringBefore("\n")).setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(open).setAutoCancel(true).build()
        NotificationManagerCompat.from(applicationContext).notify(("evt$label${e.kind}${e.levelName}").hashCode(), n)
    }

    private fun notify(signals: List<SignalWatch.Signal>, label: String) {
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
                .setContentTitle("$label · " + ctx.getString(R.string.notif_title, a, h))
                .setContentText(ctx.getString(R.string.notif_text))
                .setStyle(NotificationCompat.BigTextStyle().bigText(ctx.getString(R.string.notif_text)))
                .setContentIntent(open).setAutoCancel(true).build()
            NotificationManagerCompat.from(applicationContext).notify((label + sg.horizon).hashCode(), n)
        }
    }

    private fun notifyLevel(sc: Scenario, label: String) {
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
            .setContentTitle("$label · " + ctx.getString(R.string.notif_level_title, String.format(java.util.Locale.US, "%.2f", sc.trigger), sc.triggerLevel))
            .setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(open).setAutoCancel(true).build()
        NotificationManagerCompat.from(applicationContext).notify(("lvl" + label + sc.kind + sc.triggerLevel).hashCode(), n)
    }

    private fun notifyBrief(b: Brief, label: String) {
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
            .setContentTitle("$label · " + ctx.getString(R.string.notif_brief_title))
            .setContentText(lines.getOrElse(1) { lines[0] })
            .setStyle(NotificationCompat.BigTextStyle().bigText(lines.joinToString("\n")))
            .setContentIntent(open).setAutoCancel(true).build()
        NotificationManagerCompat.from(applicationContext).notify(BRIEF_ID + label.hashCode() % 1000, n)
    }

    companion object {
        private const val BRIEF_ID = 4711
        private const val CHANNEL = "signals"
        private const val WORK = "signal-watch"

        /** Assets this trader receives alerts for (default: gold only). Stored on the phone only. */
        fun alertAssets(prefs: android.content.SharedPreferences): Set<String> =
            (prefs.getString("alert_assets", "XAU") ?: "XAU").split(',').map { it.trim() }
                .filter { it in setOf("XAU", "BTC", "ETH", "SOL") }.toSet()

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
