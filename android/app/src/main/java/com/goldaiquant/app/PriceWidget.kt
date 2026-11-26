package com.goldaiquant.app

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.os.Bundle
import android.view.View
import android.widget.RemoteViews
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Home-screen widget (owner-approved 2026-11-26, design board «ويدجت مقترح» option 2): the «ماذا أفعل؟» idea of the
 *  HOURS card for the user's position on the selected asset (same rule as the screen and the idea notifications),
 *  next to the price, today's move and a 24 h sparkline. Narrow widgets show the price side only. Built from the
 *  last analysis the app saved; refreshed by the app and the background worker, it never fetches on its own. */
class PriceWidget : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, mgr: AppWidgetManager, ids: IntArray) = render(ctx, mgr, ids)

    override fun onAppWidgetOptionsChanged(ctx: Context, mgr: AppWidgetManager, id: Int, opts: Bundle) =
        render(ctx, mgr, intArrayOf(id))

    companion object {
        private const val WIDE_DP = 230
        private val GREEN = 0xFF3DD68C.toInt()
        private val RED = 0xFFF07A7E.toInt()
        private val DIM = 0xFF8C8A83.toInt()

        fun refresh(ctx: Context) {
            val mgr = AppWidgetManager.getInstance(ctx)
            val ids = mgr.getAppWidgetIds(ComponentName(ctx, PriceWidget::class.java))
            if (ids.isNotEmpty()) render(ctx, mgr, ids)
        }

        /** Kept for older callers: first scenario trigger, else the plan's watch price, else nearest level. */
        fun watch(d: Decision): Double? {
            d.brief?.scenarios?.firstOrNull()?.let { return it.trigger }
            val c = d.outlooks.firstOrNull()
            c?.plan?.watchPrice?.let { return it }
            return d.levels?.supports?.firstOrNull()?.price ?: d.levels?.resistances?.firstOrNull()?.price
        }

        /** Title + up to two lines for the idea, as on the «ماذا أفعل؟» sheet. */
        fun ideaLines(ctx: Context, i: SimpleAdvice.Idea, p: (Double?) -> String): Triple<Int, String, String> = when (i.kind) {
            SimpleAdvice.Kind.BUY_NOW -> Triple(R.string.sa_buy_now, ctx.getString(R.string.w_target, p(i.sellAt)),
                ctx.getString(R.string.w_cancel_below, p(i.invalid)))
            SimpleAdvice.Kind.WAIT_DIP -> Triple(R.string.sa_wait_dip, ctx.getString(R.string.w_buy_near, p(i.buyAt)),
                ctx.getString(R.string.w_target_after, p(i.sellAt)))
            SimpleAdvice.Kind.WAIT -> Triple(R.string.sa_wait, ctx.getString(R.string.w_buy_near, p(i.buyAt)), "")
            SimpleAdvice.Kind.HOLD_SELL_ABOVE -> Triple(R.string.sa_keep, ctx.getString(R.string.w_sell_near, p(i.sellAt)),
                i.invalid?.let { ctx.getString(R.string.w_cancel_below, p(it)) } ?: "")
            SimpleAdvice.Kind.SELL_REBUY -> Triple(R.string.sa_sell_rebuy, ctx.getString(R.string.w_buy_market),
                ctx.getString(R.string.w_rebuy_near, p(i.buyAt)))
            SimpleAdvice.Kind.CONFLICT -> Triple(R.string.sa_wait, ctx.getString(R.string.w_conflict), "")
            SimpleAdvice.Kind.NONE -> Triple(R.string.sa_none, "", "")
        }

        private fun spark(values: List<Double>, color: Int): Bitmap? {
            if (values.size < 2) return null
            val w = 300; val h = 60
            val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
            val lo = values.min(); val hi = values.max(); val span = (hi - lo).takeIf { it > 0 } ?: 1.0
            val path = Path()
            values.forEachIndexed { k, v ->
                val x = k * (w - 4f) / (values.size - 1) + 2f
                val y = (h - 4f) - ((v - lo) / span).toFloat() * (h - 8f)
                if (k == 0) path.moveTo(x, y) else path.lineTo(x, y)
            }
            Canvas(bmp).drawPath(path, Paint(Paint.ANTI_ALIAS_FLAG).apply {
                style = Paint.Style.STROKE; strokeWidth = 4f; this.color = color; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND
            })
            return bmp
        }

        private fun render(ctx0: Context, mgr: AppWidgetManager, ids: IntArray) {
            val ctx = LanguageStore.wrap(ctx0, LanguageStore.resolve(ctx0))
            val prefs = ctx0.getSharedPreferences("gold_ai_quant", Context.MODE_PRIVATE)
            val asset = prefs.getString("asset", "XAU") ?: "XAU"
            val raw = prefs.getString(if (asset == "XAU") "last_decision" else "last_decision_$asset", null)
            val d = raw?.let { try { DecisionParser.parse(it) } catch (e: Exception) { null } }
            val p2 = { v: Double? -> v?.let { String.format(Locale.US, "%,.2f", it) } ?: "—" }
            val hold = prefs.getString("position_$asset", "CASH") == "HOLD"
            val name = ctx.getString(when (asset) { "BTC" -> R.string.ia_name_btc; "ETH" -> R.string.ia_name_eth
                "SOL" -> R.string.ia_name_sol; else -> R.string.ia_name_xau })
            val idea = d?.let { try { IdeaAlerts.now(it, asset, hold)?.idea } catch (e: Exception) { null } }
            val chg = d?.quoteChangePct
            val up = (chg ?: 0.0) >= 0
            val closes = prefs.getString("spark_$asset", null)?.split(',')?.mapNotNull { it.toDoubleOrNull() }.orEmpty()
            val sparkColor = if (closes.size >= 2) (if (closes.last() >= closes.first()) GREEN else RED) else DIM
            val bmp = spark(closes, sparkColor)
            val open = PendingIntent.getActivity(ctx0, 11, Intent(ctx0, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP), PendingIntent.FLAG_IMMUTABLE)
            for (id in ids) {
                val v = RemoteViews(ctx0.packageName, R.layout.widget_price)
                v.setTextViewText(R.id.w_pair, if (asset == "XAU") "XAU/USD" else "$asset/USD")
                v.setTextViewText(R.id.w_price, d?.quote?.let(p2) ?: "—")
                v.setTextViewText(R.id.w_chg, chg?.let {
                    (if (up) "▲ " else "▼ ") + String.format(Locale.US, "%.2f%%", kotlin.math.abs(it)) + " · " + ctx.getString(R.string.w_today)
                } ?: "")
                v.setTextColor(R.id.w_chg, if (up) GREEN else RED)
                if (bmp != null) { v.setImageViewBitmap(R.id.w_spark, bmp); v.setViewVisibility(R.id.w_spark, View.VISIBLE) }
                else v.setViewVisibility(R.id.w_spark, View.GONE)
                v.setTextViewText(R.id.w_time, d?.quoteTime?.let {
                    ctx.getString(R.string.updated_at, DateTimeFormatter.ofPattern("HH:mm").format(it.atZone(ZoneId.systemDefault())))
                } ?: ctx.getString(R.string.widget_empty))
                val wide = mgr.getAppWidgetOptions(id).getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 250) >= WIDE_DP
                val show = if (wide && idea != null) View.VISIBLE else View.GONE
                v.setViewVisibility(R.id.w_idea_col, show)
                v.setViewVisibility(R.id.w_sep, show)
                if (idea != null) {
                    val (t, l1, l2) = ideaLines(ctx, idea, p2)
                    v.setTextViewText(R.id.w_who, ctx.getString(if (hold) R.string.ia_t_hold else R.string.ia_t_cash, name))
                    v.setTextViewText(R.id.w_act, ctx.getString(t))
                    v.setTextColor(R.id.w_act, when (idea.kind) {
                        SimpleAdvice.Kind.BUY_NOW -> GREEN
                        SimpleAdvice.Kind.SELL_REBUY -> 0xFFF0A46A.toInt()
                        SimpleAdvice.Kind.HOLD_SELL_ABOVE -> 0xFF8FC1EA.toInt()
                        SimpleAdvice.Kind.NONE -> DIM
                        else -> 0xFFE6C55A.toInt()
                    })
                    v.setTextViewText(R.id.w_l1, l1)
                    v.setTextViewText(R.id.w_l2, l2)
                    v.setViewVisibility(R.id.w_l2, if (l2.isEmpty()) View.GONE else View.VISIBLE)
                    v.setTextViewText(R.id.w_note, ctx.getString(R.string.sa_idea))
                }
                v.setOnClickPendingIntent(R.id.w_root, open)
                mgr.updateAppWidget(id, v)
            }
        }
    }
}
