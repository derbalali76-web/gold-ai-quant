package com.goldaiquant.app

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Home-screen widget: price of the selected asset and the level to watch, from the last analysis the app saved.
 *  Refreshed by the app after each analysis and by the background worker; it never fetches on its own. */
class PriceWidget : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, mgr: AppWidgetManager, ids: IntArray) = render(ctx, mgr, ids)

    companion object {
        fun refresh(ctx: Context) {
            val mgr = AppWidgetManager.getInstance(ctx)
            val ids = mgr.getAppWidgetIds(ComponentName(ctx, PriceWidget::class.java))
            if (ids.isNotEmpty()) render(ctx, mgr, ids)
        }

        /** Same rule as the app's headline: first scenario trigger, else the plan's watch price, else nearest level. */
        fun watch(d: Decision): Double? {
            d.brief?.scenarios?.firstOrNull()?.let { return it.trigger }
            val c = d.outlooks.firstOrNull()
            c?.plan?.watchPrice?.let { return it }
            return d.levels?.supports?.firstOrNull()?.price ?: d.levels?.resistances?.firstOrNull()?.price
        }

        private fun render(ctx0: Context, mgr: AppWidgetManager, ids: IntArray) {
            val ctx = LanguageStore.wrap(ctx0, LanguageStore.resolve(ctx0))
            val prefs = ctx0.getSharedPreferences("gold_ai_quant", Context.MODE_PRIVATE)
            val asset = prefs.getString("asset", "XAU") ?: "XAU"
            val raw = prefs.getString(if (asset == "XAU") "last_decision" else "last_decision_$asset", null)
            val d = raw?.let { try { DecisionParser.parse(it) } catch (e: Exception) { null } }
            val p2 = { v: Double -> String.format(Locale.US, "%,.2f", v) }
            val v = RemoteViews(ctx0.packageName, R.layout.widget_price)
            v.setTextViewText(R.id.w_pair, if (asset == "XAU") "XAU/USD" else "$asset/USD")
            v.setTextViewText(R.id.w_price, d?.quote?.let(p2) ?: "—")
            val w = d?.let(::watch)
            val hold = prefs.getString("position_$asset", "CASH") == "HOLD"
            v.setTextViewText(R.id.w_watch, if (w == null) ctx.getString(R.string.widget_empty)
                else ctx.getString(if (hold) R.string.hl_hold_watch else R.string.hl_watch, p2(w)))
            v.setTextViewText(R.id.w_time, d?.quoteTime?.let {
                ctx.getString(R.string.updated_at, DateTimeFormatter.ofPattern("HH:mm").format(it.atZone(ZoneId.systemDefault())))
            } ?: "")
            val open = PendingIntent.getActivity(ctx0, 11, Intent(ctx0, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP), PendingIntent.FLAG_IMMUTABLE)
            v.setOnClickPendingIntent(R.id.w_root, open)
            mgr.updateAppWidget(ids, v)
        }
    }
}
