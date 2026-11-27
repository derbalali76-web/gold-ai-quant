package com.goldaiquant.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/** Receives the server's DATA messages and shows them in the phone's language. Never trades. */
class FcmService : FirebaseMessagingService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onNewToken(token: String) {
        scope.launch { Push.sync(applicationContext, token) }
    }

    override fun onMessageReceived(m: RemoteMessage) {
        val d = m.data
        // an hour closed across a level: re-check the opportunity idea now (owner 2026-11-25: replaces the old
        // «scenario triggered» text, which could contradict the screen)
        if (d["type"] == "check" || d["type"] == "event") { SignalWorker.runNow(applicationContext); return }
        val asset = d["asset"] ?: return
        if (d["type"] == "price" && d["key"].orEmpty().startsWith("jt|")) {
            val id = d["key"]!!.removePrefix("jt|").toLongOrNull() ?: return
            val prefs = applicationContext.getSharedPreferences("gold_ai_quant", MODE_PRIVATE)
            Journal.closeById(prefs, id, d["level"]?.toDoubleOrNull() ?: return)?.let { AutoSell.notify(applicationContext, it) }
            return
        }
        val label = if (asset == "XAU") "XAU/USD" else "$asset/USD"
        val ctx = LanguageStore.wrap(applicationContext, LanguageStore.resolve(applicationContext))
        val p2 = { s: String? -> s?.toDoubleOrNull()?.let { String.format(java.util.Locale.US, "%.2f", it) } ?: "—" }
        val (title, text) = when (d["type"]) {
            "price" -> {
                // fired once: remove it from the phone's list too (the bell turns off)
                val prefs = applicationContext.getSharedPreferences("gold_ai_quant", MODE_PRIVATE)
                d["key"]?.takeIf { it.isNotBlank() }?.let { k ->
                    PriceAlerts.save(prefs, PriceAlerts.load(prefs).filterNot { it.key == k })
                }
                ctx.getString(R.string.notif_price_title, label, p2(d["level"])) to
                    ctx.getString(R.string.notif_price_text, d["label"].orEmpty(), p2(d["price"]))
            }
            "zone" -> {  // the price entered a support / resistance zone: what breaks it, what holds it (watch only)
                val sup = d["side"] == "SUPPORT"
                ctx.getString(R.string.notif_zone_title, label) to
                    ctx.getString(if (sup) R.string.notif_zone_sup_text else R.string.notif_zone_res_text,
                        p2(d["low"]) + "–" + p2(d["high"]), p2(d["next"]), p2(d["other"]))
            }
            "signal" -> {
                val h = ctx.getString(when (d["horizon"]) { "WEEK" -> R.string.h_week; "MONTH" -> R.string.h_month; else -> R.string.h_hours })
                val a = ctx.getString(if (d["side"] == "BUY") R.string.a_buy else R.string.a_sell)
                "$label · " + ctx.getString(R.string.notif_title, a, h) to ctx.getString(R.string.notif_text)
            }
            else -> return
        }
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this,
                android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel("signals", ctx.getString(R.string.notif_channel), NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(this, 7,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(this, "signals").setSmallIcon(android.R.drawable.stat_notify_more)
            .setContentTitle(title).setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(open).setAutoCancel(true)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setPublicVersion(
                NotificationCompat.Builder(this, "signals").setSmallIcon(android.R.drawable.stat_notify_more)
                    .setContentTitle("AI QUANT").setContentText(ctx.getString(R.string.notif_locked)).build())
            .build()
        NotificationManagerCompat.from(this).notify((d.toString()).hashCode(), n)
    }
}
