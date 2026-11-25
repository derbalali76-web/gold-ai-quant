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
        if (prefs.getBoolean("te_notify", false)) try { checkTrade(prefs) } catch (e: Exception) { }
        if (!prefs.getBoolean("notify", false)) return Result.success()
        val url = prefs.getString("server_url", null) ?: return Result.success()
        val api = ApiClient(url, prefs.getString("token", "") ?: "")
        try { Push.sync(applicationContext) } catch (e: Exception) { }  // re-registers after a server restart
        val pushOn = Push.active(applicationContext)  // the server sends price/scenario/signal alerts instantly
        val follow = alertAssets(prefs)
        val alerts = if (pushOn) emptyList() else PriceAlerts.load(prefs)
        for (asset in follow + alerts.map { it.asset }.toSet()) {  // followed markets + markets with a "Alert me" alert
            val f = try { api.decision("LIVE", 0, asset) } catch (e: Exception) { continue }
            if (asset in follow) check(prefs, asset, f, pushOn)
            if (asset in follow) try { checkIdea(prefs, asset, f) } catch (e: Exception) { }
            if (!pushOn) checkPriceAlerts(prefs, asset, f)
        }
        try { PriceWidget.refresh(applicationContext) } catch (e: Exception) { }
        return Result.success()
    }

    private fun check(prefs: android.content.SharedPreferences, asset: String, f: Fetched, pushOn: Boolean = false) {
        val sfx = if (asset == "XAU") "" else "_$asset"
        val label = if (asset == "XAU") "XAU/USD" else "$asset/USD"
        // 1) a NEW validated recommendation (only ever exists after out-of-sample validation)
        val last = prefs.getString("notified$sfx", "")!!.split(';').filter { it.contains('=') }
            .associate { it.substringBefore('=') to it.substringAfter('=') }
        val (fresh, memory) = SignalWatch.diff(f.decision, last)
        prefs.edit().putString("notified$sfx", memory.entries.joinToString(";") { "${it.key}=${it.value}" })
            .putString(if (asset == "XAU") "last_decision" else "last_decision_$asset", f.raw)
            .putLong("last_received", System.currentTimeMillis()).apply()
        if (fresh.isNotEmpty() && !pushOn) notify(fresh, label)
        val day = java.time.LocalDate.now().toString()
        val b = f.decision.brief
        if (b != null && !f.decision.marketClosed) {
            // 2) scenario triggered: the last closed hour broke a level (once per level and hour)
            val seen = prefs.getString("events$sfx", "")!!.split(';').filter { it.startsWith(day) }.toMutableSet()
            b.events.forEach { e ->
                val key = "$day|${e.hourUtc}|${e.kind}|${e.levelName}"
                seen += key  // owner 2026-11-25: no «scenario triggered» text any more; the idea alerts replace it
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

    /** Opportunity idea of the HOURS card for the user's own position (cash / holder) on this asset: sent once,
     *  then one follow-up when it ends (target, failed, expired). See IdeaAlerts. */
    private fun checkIdea(prefs: android.content.SharedPreferences, asset: String, f: Fetched) { synchronized(LOCK) {
        val price = f.decision.quote ?: return
        val hold = prefs.getString("position_$asset", "CASH") == "HOLD"
        val n = IdeaAlerts.now(f.decision, asset, hold, price) ?: return
        val key = "idea_${asset}_" + if (hold) "H" else "C"
        val ck = "idea_cool_$asset"
        val st = IdeaAlerts.step(IdeaAlerts.decode(prefs.getString(key, null)), prefs.getLong(ck, 0L), n, price,
            System.currentTimeMillis())
        prefs.edit().putString(key, IdeaAlerts.encode(st.state)).putLong(ck, st.coolUntil).apply()
        val m = st.msg ?: return
        val a = st.idea ?: return
        val ctx = LanguageStore.wrap(applicationContext, LanguageStore.resolve(applicationContext))
        if (!ready(ctx)) return
        val p = { v: Double? -> v?.let { String.format(java.util.Locale.US, "%.2f", it) } ?: "—" }
        val name = ctx.getString(when (asset) { "BTC" -> R.string.ia_name_btc; "ETH" -> R.string.ia_name_eth
            "SOL" -> R.string.ia_name_sol; else -> R.string.ia_name_xau })
        val title = ctx.getString(if (hold) R.string.ia_t_hold else R.string.ia_t_cash, name)
        val body = when (m) {
            IdeaAlerts.Msg.NEW -> when (a.kind) {
                SimpleAdvice.Kind.BUY_NOW -> ctx.getString(R.string.ia_buy, p(a.price), p(a.sellAt), p(a.stop))
                SimpleAdvice.Kind.WAIT_DIP -> ctx.getString(R.string.ia_dip, p(a.buyAt), p(a.sellAt))
                SimpleAdvice.Kind.WAIT -> ctx.getString(R.string.ia_wait, p(a.buyAt))
                SimpleAdvice.Kind.HOLD_SELL_ABOVE -> ctx.getString(R.string.ia_keep, p(a.sellAt), p(a.stop))
                SimpleAdvice.Kind.SELL_REBUY -> ctx.getString(R.string.ia_sell, p(a.price), p(a.buyAt), p(a.stop))
                else -> return
            }
            IdeaAlerts.Msg.TARGET -> if (a.kind == SimpleAdvice.Kind.SELL_REBUY) ctx.getString(R.string.ia_tgt_rebuy, p(a.buyAt))
                else ctx.getString(R.string.ia_tgt, p(a.sellAt))
            IdeaAlerts.Msg.FAILED_STOP -> ctx.getString(R.string.ia_fail_stop, p(a.stop))
            IdeaAlerts.Msg.FAILED_TURN -> ctx.getString(R.string.ia_fail_turn)
            IdeaAlerts.Msg.EXPIRED -> ctx.getString(R.string.ia_expired)
        }
        val text = body + "\n" + ctx.getString(R.string.ia_note)
        val open = PendingIntent.getActivity(applicationContext, 9,
            Intent(applicationContext, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE)
        val n2 = NotificationCompat.Builder(applicationContext, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_more).setContentTitle(title)
            .setContentText(body).setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(open).setAutoCancel(true).private(applicationContext).build()
        NotificationManagerCompat.from(applicationContext).notify("idea$asset${a.at}$m".hashCode(), n2)
    } }

    /** One-shot "Alert me" alerts: fire once when the price is at/through the level, then removed. */
    private fun checkPriceAlerts(prefs: android.content.SharedPreferences, asset: String, f: Fetched) {
        val price = f.decision.quote ?: return
        if (f.decision.marketClosed) return
        val all = PriceAlerts.load(prefs)
        val hit = all.filter { it.asset == asset && PriceAlerts.reached(it, price) }
        if (hit.isEmpty()) return
        PriceAlerts.save(prefs, all - hit.toSet())
        val ctx = LanguageStore.wrap(applicationContext, LanguageStore.resolve(applicationContext))
        if (!ready(ctx)) return
        val label = if (asset == "XAU") "XAU/USD" else "$asset/USD"
        val p2 = { v: Double -> String.format(java.util.Locale.US, "%.2f", v) }
        val open = PendingIntent.getActivity(applicationContext, 5,
            Intent(applicationContext, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE)
        hit.forEach { a ->
            val n = NotificationCompat.Builder(applicationContext, CHANNEL)
                .setSmallIcon(android.R.drawable.stat_notify_more)
                .setContentTitle(ctx.getString(R.string.notif_price_title, label, p2(a.price)))
                .setContentText(ctx.getString(R.string.notif_price_text, a.label, p2(price)))
                .setStyle(NotificationCompat.BigTextStyle().bigText(ctx.getString(R.string.notif_price_text, a.label, p2(price))))
                .setContentIntent(open).setAutoCancel(true).private(applicationContext).build()
            NotificationManagerCompat.from(applicationContext).notify(a.key.hashCode(), n)
        }
    }

    /** A NEW experimental trade in the public ledger: announced once (by its ledger line number). */
    private suspend fun checkTrade(prefs: android.content.SharedPreferences) {
        val body = TrustLedger.fetch(TradeOpp.URL) ?: return
        val st = TradeOpp.parse(body) ?: return
        prefs.edit().putString("te_state", body).apply()
        val o = st.active ?: return
        if (prefs.getInt("te_notified", 0) >= o.seq) return
        prefs.edit().putInt("te_notified", o.seq).apply()
        val ctx = LanguageStore.wrap(applicationContext, LanguageStore.resolve(applicationContext))
        if (!ready(ctx)) return
        val p0 = { v: Double -> String.format(java.util.Locale.US, "%,.0f", v) }
        val text = ctx.getString(R.string.te_notif_text, p0(o.limit), p0(o.target), p0(o.stop))
        val open = PendingIntent.getActivity(applicationContext, 7,
            Intent(applicationContext, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(applicationContext, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_more).setContentTitle(ctx.getString(R.string.te_notif_title))
            .setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(open).setAutoCancel(true).private(applicationContext).build()
        NotificationManagerCompat.from(applicationContext).notify(("te" + o.seq).hashCode(), n)
    }

    private fun ready(ctx: Context): Boolean {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(applicationContext,
                android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return false
        applicationContext.getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, ctx.getString(R.string.notif_channel), NotificationManager.IMPORTANCE_HIGH))
        return true
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
                .setContentIntent(open).setAutoCancel(true).private(applicationContext).build()
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
            .setContentIntent(open).setAutoCancel(true).private(applicationContext).build()
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
            .setContentIntent(open).setAutoCancel(true).private(applicationContext).build()
        NotificationManagerCompat.from(applicationContext).notify(BRIEF_ID + label.hashCode() % 1000, n)
    }

    companion object {
        private const val BRIEF_ID = 4711
        private const val CHANNEL = "signals"
        private const val WORK = "signal-watch"
        private val LOCK = Any()

        /** One extra check now (the server asks for it when an hour closes across a level). */
        fun runNow(ctx: Context) {
            val req = androidx.work.OneTimeWorkRequestBuilder<SignalWorker>()
                .setConstraints(androidx.work.Constraints.Builder()
                    .setRequiredNetworkType(androidx.work.NetworkType.CONNECTED).build()).build()
            WorkManager.getInstance(ctx).enqueueUniqueWork("signal-now", androidx.work.ExistingWorkPolicy.KEEP, req)
        }

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

/** On a locked screen, show only "AI QUANT — new alert", never the analysis text (the user unlocks to read it). */
private fun NotificationCompat.Builder.private(ctx: android.content.Context): NotificationCompat.Builder =
    setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setPublicVersion(
        NotificationCompat.Builder(ctx, "signals").setSmallIcon(android.R.drawable.stat_notify_more)
            .setContentTitle("AI QUANT").setContentText(ctx.getString(R.string.notif_locked)).build())
