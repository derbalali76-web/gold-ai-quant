package com.goldaiquant.app

import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.SharedPreferences
import android.view.View
import android.widget.RemoteViews

/** Wide widget (4×2): the idea for your position | price, today's move, 24 h sparkline. Tap the pair to change the
 *  asset, tap «تملك …؟» to switch cash / holder. Narrow sizes show the price side only. */
class PriceWidget : BaseWidget() {
    companion object {
        private const val WIDE_DP = 230

        /** Called by the app and the workers after new data. */
        fun refresh(ctx: Context) = Widgets.refreshAll(ctx)

        private fun arrow(text: String, up: Boolean?, color: Int): CharSequence {
            if (up == null || text.isEmpty()) return text
            val sb = android.text.SpannableStringBuilder(text).append("  ")
            val st = sb.length
            sb.append(if (up) "▲" else "▼")
            sb.setSpan(android.text.style.ForegroundColorSpan(color), st, sb.length, android.text.Spannable.SPAN_EXCLUSIVE_EXCLUSIVE)
            return sb
        }

        /** Title + up to two lines for the idea, as on the «ماذا أفعل؟» sheet (arrows: target ▲ green, cancel ▼ red). */
        fun ideaLines(ctx: Context, i: SimpleAdvice.Idea): Triple<Int, CharSequence, CharSequence> {
            val p = Widgets::p2
            val g = Widgets.GREEN; val r = Widgets.RED; val y = Widgets.GOLD
            return when (i.kind) {
                SimpleAdvice.Kind.BUY_NOW -> Triple(R.string.sa_buy_now, arrow(ctx.getString(R.string.w_target, p(i.sellAt)), true, g),
                    arrow(ctx.getString(R.string.w_cancel_below, p(i.invalid)), false, r))
                SimpleAdvice.Kind.WAIT_DIP -> Triple(R.string.sa_wait_dip, arrow(ctx.getString(R.string.w_buy_near, p(i.buyAt)), false, y),
                    arrow(ctx.getString(R.string.w_target_after, p(i.sellAt)), true, g))
                SimpleAdvice.Kind.WAIT -> Triple(R.string.sa_wait, arrow(ctx.getString(R.string.w_buy_near, p(i.buyAt)), false, y), "")
                SimpleAdvice.Kind.HOLD_SELL_ABOVE -> Triple(R.string.sa_keep, arrow(ctx.getString(R.string.w_sell_near, p(i.sellAt)), true, g),
                    i.invalid?.let { arrow(ctx.getString(R.string.w_cancel_below, p(it)), false, r) } ?: "")
                SimpleAdvice.Kind.SELL_REBUY -> Triple(R.string.sa_sell_rebuy, ctx.getString(R.string.w_buy_market),
                    arrow(ctx.getString(R.string.w_rebuy_near, p(i.buyAt)), false, y))
                SimpleAdvice.Kind.CONFLICT -> Triple(R.string.sa_wait, ctx.getString(R.string.w_conflict), "")
                SimpleAdvice.Kind.EVENT -> Triple(R.string.sa_event, ctx.getString(R.string.w_event), "")
                SimpleAdvice.Kind.NONE -> Triple(R.string.sa_none, "", "")
            }
        }

        private fun chip(k: SimpleAdvice.Kind?): Int = when (k) {
            SimpleAdvice.Kind.BUY_NOW -> R.drawable.wchip_green
            SimpleAdvice.Kind.HOLD_SELL_ABOVE -> R.drawable.wchip_blue
            SimpleAdvice.Kind.SELL_REBUY -> R.drawable.wchip_orange
            SimpleAdvice.Kind.NONE, null -> R.drawable.wchip_dim
            else -> R.drawable.wchip_gold
        }

        fun build(ctx0: Context, ctx: Context, p: SharedPreferences, mgr: AppWidgetManager, id: Int): RemoteViews {
            val a = Widgets.asset(p, id)
            val d = Widgets.decision(p, a)
            val hold = Widgets.hold(p, a)
            val o = mgr.getAppWidgetOptions(id)
            val wDp = o.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 250)
            val hDp = o.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 0).takeIf { it > 0 }
                ?: o.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 110)
            val strip = hDp in 1..109
            val v = RemoteViews(ctx0.packageName, if (strip) R.layout.widget_strip else R.layout.widget_price)
            if (!strip && wDp < 260) v.setInt(R.id.w_card, "setBackgroundResource", R.drawable.wf_compact)
            v.setImageViewResource(R.id.w_art, Widgets.art(a))
            v.setTextViewText(R.id.w_pair, Widgets.pair(a) + " ▾")
            v.setTextViewText(R.id.w_price, Widgets.p2(d?.quote))
            val (chg, col) = Widgets.change(ctx, d)
            v.setTextViewText(R.id.w_chg, chg); v.setTextColor(R.id.w_chg, col)
            if (!strip) {
                Widgets.setSpark(v, R.id.w_spark, Widgets.closes(p, a))
                v.setTextViewText(R.id.w_time, Widgets.time(ctx, d))
            }
            val show = if (wDp >= WIDE_DP) View.VISIBLE else View.GONE
            v.setViewVisibility(R.id.w_idea_col, show)
            v.setViewVisibility(R.id.w_sep, show)
            v.setViewVisibility(R.id.w_art, show)
            v.setTextViewText(R.id.w_who, ctx.getString(if (hold) R.string.ia_t_hold else R.string.ia_t_cash, Widgets.name(ctx, a)) + "  ⇄")
            val idea = Widgets.idea(d, a, hold, p)
            v.setInt(R.id.w_act, "setBackgroundResource", chip(idea?.kind))
            if (idea != null) {
                val (t, l1, l2) = ideaLines(ctx, idea)
                v.setTextViewText(R.id.w_act, ctx.getString(t))
                v.setTextColor(R.id.w_act, Widgets.word(idea.kind).second)
                v.setTextViewText(R.id.w_l1, l1)
                if (!strip) {
                    v.setTextViewText(R.id.w_l2, l2)
                    v.setViewVisibility(R.id.w_l2, if (l2.isEmpty()) View.GONE else View.VISIBLE)
                    v.setTextViewText(R.id.w_note, "⚗  " + ctx.getString(R.string.sa_idea))
                }
            } else {
                v.setTextViewText(R.id.w_act, "—"); v.setTextColor(R.id.w_act, Widgets.DIM)
                v.setTextViewText(R.id.w_l1, ctx.getString(R.string.widget_empty))
                if (!strip) { v.setViewVisibility(R.id.w_l2, View.GONE); v.setTextViewText(R.id.w_note, "") }
            }
            v.setOnClickPendingIntent(R.id.w_root, Widgets.openApp(ctx0))
            v.setOnClickPendingIntent(R.id.w_pair, Widgets.action(ctx0, PriceWidget::class.java, id, Widgets.ACT_NEXT))
            v.setOnClickPendingIntent(R.id.w_who, Widgets.action(ctx0, PriceWidget::class.java, id, Widgets.ACT_POS))
            return v
        }
    }
}

/** Small widget (2×2): price, today's move, sparkline. Tap the pair to change the asset. */
class PriceWidgetSmall : BaseWidget() {
    companion object {
        fun build(ctx0: Context, ctx: Context, p: SharedPreferences, id: Int): RemoteViews {
            val a = Widgets.asset(p, id)
            val d = Widgets.decision(p, a)
            val v = RemoteViews(ctx0.packageName, R.layout.widget_small)
            v.setTextViewText(R.id.ws_pair, a + " ▾")
            v.setTextViewText(R.id.ws_price, Widgets.p2(d?.quote))
            val (chg, col) = Widgets.change(ctx, d)
            v.setTextViewText(R.id.ws_chg, chg); v.setTextColor(R.id.ws_chg, col)
            Widgets.setSpark(v, R.id.ws_spark, Widgets.closes(p, a))
            v.setImageViewResource(R.id.ws_art, Widgets.art(a))
            v.setTextViewText(R.id.ws_time, Widgets.time(ctx, d))
            v.setOnClickPendingIntent(R.id.ws_root, Widgets.openApp(ctx0))
            v.setOnClickPendingIntent(R.id.ws_pair, Widgets.action(ctx0, PriceWidgetSmall::class.java, id, Widgets.ACT_NEXT))
            return v
        }
    }
}

/** List widget (4×2): every asset — price, today's move, sparkline and one word for your idea on it. */
class PriceWidgetList : BaseWidget() {
    companion object {
        private val ROWS = listOf(
            intArrayOf(R.id.wl_n0, R.id.wl_s0, R.id.wl_p0, R.id.wl_c0, R.id.wl_i0, R.id.wl_a0),
            intArrayOf(R.id.wl_n1, R.id.wl_s1, R.id.wl_p1, R.id.wl_c1, R.id.wl_i1, R.id.wl_a1),
            intArrayOf(R.id.wl_n2, R.id.wl_s2, R.id.wl_p2, R.id.wl_c2, R.id.wl_i2, R.id.wl_a2),
            intArrayOf(R.id.wl_n3, R.id.wl_s3, R.id.wl_p3, R.id.wl_c3, R.id.wl_i3, R.id.wl_a3))

        fun build(ctx0: Context, ctx: Context, p: SharedPreferences): RemoteViews {
            val v = RemoteViews(ctx0.packageName, R.layout.widget_list)
            var latest: Decision? = null
            Widgets.ASSETS.forEachIndexed { k, a ->
                val r = ROWS[k]
                val d = Widgets.decision(p, a)
                if (d?.quoteTime != null && (latest?.quoteTime == null || d.quoteTime!! > latest!!.quoteTime!!)) latest = d
                v.setTextViewText(r[0], if (a == "XAU") Widgets.name(ctx, a) else a)
                v.setImageViewResource(r[5], Widgets.art(a))
                Widgets.setSpark(v, r[1], Widgets.closes(p, a))
                v.setTextViewText(r[2], Widgets.p2(d?.quote))
                val c = d?.quoteChangePct
                v.setTextViewText(r[3], c?.let { (if (it >= 0) "▲ " else "▼ ") + String.format(java.util.Locale.US, "%.1f%%", kotlin.math.abs(it)) } ?: "")
                v.setTextColor(r[3], if ((c ?: 0.0) >= 0) Widgets.GREEN else Widgets.RED)
                val (w, col) = Widgets.word(Widgets.idea(d, a, Widgets.hold(p, a), p)?.kind)
                v.setTextViewText(r[4], ctx.getString(w)); v.setTextColor(r[4], col)
            }
            v.setTextViewText(R.id.wl_time, Widgets.time(ctx, latest))
            v.setOnClickPendingIntent(R.id.wl_root, Widgets.openApp(ctx0))
            return v
        }
    }
}
