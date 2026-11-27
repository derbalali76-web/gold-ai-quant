package com.goldaiquant.app

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

/** «وصل الهدف، وقت البيع» for an automatic test buy (journal), from the worker, the server push or a live tick. */
object AutoSell {
    fun notify(app: Context, t: Journal.Trade) {
        val ctx = LanguageStore.wrap(app, LanguageStore.resolve(app))
        if (android.os.Build.VERSION.SDK_INT >= 33 && androidx.core.content.ContextCompat.checkSelfPermission(app,
                android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) return
        app.getSystemService(android.app.NotificationManager::class.java).createNotificationChannel(
            android.app.NotificationChannel("signals", ctx.getString(R.string.notif_channel),
                android.app.NotificationManager.IMPORTANCE_HIGH))
        val prefs = app.getSharedPreferences("gold_ai_quant", Context.MODE_PRIVATE)
        val sell = t.sellPrice ?: return
        val net = Journal.net(t, sell, Journal.costs(prefs))
        val f = { v: Double -> String.format(java.util.Locale.US, "%.2f", v) }
        val name = ctx.getString(when (t.asset) { "BTC" -> R.string.ia_name_btc; "ETH" -> R.string.ia_name_eth
            "SOL" -> R.string.ia_name_sol; else -> R.string.ia_name_xau })
        val title = ctx.getString(R.string.j_auto_sold_title, name)
        val body = ctx.getString(R.string.j_auto_sold, f(sell), f(t.buyPrice), (if (net >= 0) "+" else "−") + f(kotlin.math.abs(net)))
        val open = PendingIntent.getActivity(app, 10, Intent(app, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP), PendingIntent.FLAG_IMMUTABLE)
        try {
            NotificationManagerCompat.from(app).notify(("jsell" + t.id).hashCode(),
                NotificationCompat.Builder(app, "signals").setSmallIcon(android.R.drawable.stat_notify_more)
                    .setContentTitle(title).setContentText(body).setStyle(NotificationCompat.BigTextStyle().bigText(body))
                    .setContentIntent(open).setAutoCancel(true).private(app).build())
        } catch (e: SecurityException) { }
    }
}
