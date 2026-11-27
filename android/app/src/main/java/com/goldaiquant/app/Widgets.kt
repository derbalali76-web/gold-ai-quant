package com.goldaiquant.app

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.os.Bundle
import android.view.View
import android.widget.RemoteViews
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Home-screen widgets (owner-approved 2026-11-26, design board «ويدجت مقترح»): three sizes the user picks from the
 * widget list — small (price), wide (price + the «ماذا أفعل؟» idea) and list (all assets). The asset of a small or
 * wide widget is chosen per widget (when it is added, by tapping its name, or by editing it); the position (cash /
 * holder) is the same one the app and the idea notifications use. Ideas use the same rule as the screen
 * (IdeaAlerts.now). Data = the analyses the app and the workers saved; WidgetWorker fetches the widgets' assets.
 */
object Widgets {
    val ASSETS = listOf("XAU", "BTC", "ETH", "SOL")
    const val ACT_NEXT = "com.goldaiquant.app.W_NEXT_ASSET"
    const val ACT_POS = "com.goldaiquant.app.W_TOGGLE_POS"
    const val ACT_REFRESH = "com.goldaiquant.app.W_REFRESH"
    val GREEN = 0xFF3DD68C.toInt()
    val RED = 0xFFF07A7E.toInt()
    val DIM = 0xFF8C8A83.toInt()
    val GOLD = 0xFFE6C55A.toInt()

    fun prefs(ctx: Context): SharedPreferences = ctx.getSharedPreferences("gold_ai_quant", Context.MODE_PRIVATE)
    fun asset(p: SharedPreferences, id: Int): String =
        p.getString("w_asset_$id", null)?.takeIf { it in ASSETS } ?: (p.getString("asset", "XAU") ?: "XAU")
    fun setAsset(p: SharedPreferences, id: Int, a: String) = p.edit().putString("w_asset_$id", a).apply()
    fun hold(p: SharedPreferences, a: String) = p.getString("position_$a", "CASH") == "HOLD"
    fun setHold(p: SharedPreferences, a: String, h: Boolean) = p.edit().putString("position_$a", if (h) "HOLD" else "CASH").apply()
    fun key(a: String) = if (a == "XAU") "last_decision" else "last_decision_$a"
    fun decision(p: SharedPreferences, a: String): Decision? =
        p.getString(key(a), null)?.let { try { DecisionParser.parse(it) } catch (e: Exception) { null } }
    fun closes(p: SharedPreferences, a: String): List<Double> =
        p.getString("spark_$a", null)?.split(',')?.mapNotNull { it.toDoubleOrNull() }.orEmpty()
    fun pair(a: String) = if (a == "XAU") "XAU/USD" else "$a/USD"
    fun p2(v: Double?) = v?.let { String.format(Locale.US, "%,.2f", it) } ?: "—"
    fun name(ctx: Context, a: String) = ctx.getString(when (a) { "BTC" -> R.string.ia_name_btc; "ETH" -> R.string.ia_name_eth
        "SOL" -> R.string.ia_name_sol; else -> R.string.ia_name_xau })
    fun lang(ctx: Context): Context = LanguageStore.wrap(ctx, LanguageStore.resolve(ctx))

    fun idea(d: Decision?, a: String, hold: Boolean, p: SharedPreferences? = null): SimpleAdvice.Idea? =
        d?.let { try { IdeaAlerts.now(it, a, hold, it.quote, p)?.idea } catch (e: Exception) { null } }

    fun change(ctx: Context, d: Decision?): Pair<String, Int> {
        val pct = d?.quoteChangePct ?: return "" to DIM
        val up = pct >= 0
        val abs = d.quoteChange?.let { (if (it >= 0) "+" else "−") + String.format(Locale.US, "%,.2f", kotlin.math.abs(it)) + "  " } ?: ""
        return (abs + "(" + (if (up) "+" else "−") + String.format(Locale.US, "%.2f%%", kotlin.math.abs(pct)) + ") " +
            (if (up) "▲" else "▼")) to (if (up) GREEN else RED)
    }

    /** Artwork of the asset (owner-supplied, 2026-11-26). */
    fun art(a: String): Int = when (a) { "BTC" -> R.drawable.wa_btc; "ETH" -> R.drawable.wa_eth; "SOL" -> R.drawable.wa_sol
        else -> R.drawable.wa_xau }

    fun time(ctx: Context, d: Decision?): String = d?.quoteTime?.let {
        ctx.getString(R.string.updated_at, DateTimeFormatter.ofPattern("HH:mm").format(it.atZone(ZoneId.systemDefault())))
    } ?: ctx.getString(R.string.widget_empty)

    /** The "updated at" line doubles as the refresh button (owner 2026-11-27: the widget lagged behind the app). */
    fun stamp(ctx: Context, d: Decision?): String = "⟳  " + time(ctx, d)

    fun spark(values: List<Double>): Bitmap? {
        if (values.size < 2) return null
        val color = if (values.last() >= values.first()) GREEN else RED
        val w = 600; val h = 120
        val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val lo = values.min(); val span = (values.max() - lo).takeIf { it > 0 } ?: 1.0
        val line = Path()
        values.forEachIndexed { k, v ->
            val x = k * (w - 6f) / (values.size - 1) + 3f
            val y = (h - 6f) - ((v - lo) / span).toFloat() * (h - 14f)
            if (k == 0) line.moveTo(x, y) else line.lineTo(x, y)
        }
        val fill = Path(line).apply { lineTo(w - 3f, h.toFloat()); lineTo(3f, h.toFloat()); close() }
        val c = Canvas(bmp)
        c.drawPath(fill, Paint(Paint.ANTI_ALIAS_FLAG).apply {
            shader = android.graphics.LinearGradient(0f, 0f, 0f, h.toFloat(), (color and 0x00FFFFFF) or 0x66000000,
                color and 0x00FFFFFF, android.graphics.Shader.TileMode.CLAMP)
        })
        c.drawPath(line, Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE; strokeWidth = 10f; this.color = (color and 0x00FFFFFF) or 0x44000000
            strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND
        })
        c.drawPath(line, Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE; strokeWidth = 5f; this.color = color; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND
        })
        return bmp
    }

    fun setSpark(v: RemoteViews, viewId: Int, values: List<Double>) {
        val b = spark(values)
        if (b != null) { v.setImageViewBitmap(viewId, b); v.setViewVisibility(viewId, View.VISIBLE) }
        else v.setViewVisibility(viewId, View.INVISIBLE)
    }

    fun openApp(ctx: Context): PendingIntent = PendingIntent.getActivity(ctx, 11, Intent(ctx, MainActivity::class.java)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP), PendingIntent.FLAG_IMMUTABLE)

    fun action(ctx: Context, cls: Class<*>, id: Int, act: String): PendingIntent =
        PendingIntent.getBroadcast(ctx, (act + id).hashCode(), Intent(ctx, cls).setAction(act)
            .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    /** Short word for a list row. */
    fun word(k: SimpleAdvice.Kind?): Pair<Int, Int> = when (k) {
        SimpleAdvice.Kind.BUY_NOW -> R.string.w_w_buy to GREEN
        SimpleAdvice.Kind.WAIT_DIP, SimpleAdvice.Kind.WAIT, SimpleAdvice.Kind.CONFLICT -> R.string.w_w_wait to GOLD
        SimpleAdvice.Kind.HOLD_SELL_ABOVE -> R.string.w_w_keep to 0xFF8FC1EA.toInt()
        SimpleAdvice.Kind.SELL_REBUY -> R.string.w_w_sell to 0xFFF0A46A.toInt()
        else -> R.string.w_w_none to DIM
    }

    private val PROVIDERS = listOf(PriceWidget::class.java, PriceWidgetSmall::class.java, PriceWidgetList::class.java)

    fun ids(ctx: Context, cls: Class<*>): IntArray =
        AppWidgetManager.getInstance(ctx).getAppWidgetIds(ComponentName(ctx, cls))

    /** Assets shown by any widget on the home screen. */
    fun assetsInUse(ctx: Context): Set<String> {
        val p = prefs(ctx)
        if (ids(ctx, PriceWidgetList::class.java).isNotEmpty()) return ASSETS.toSet()
        return (ids(ctx, PriceWidget::class.java) + ids(ctx, PriceWidgetSmall::class.java)).map { asset(p, it) }.toSet()
    }

    /** [busy]: the refresh buttons show "⟳ …" until the fetch finishes and redraws. */
    @Volatile var busy = false

    fun refreshAll(ctx: Context, busy: Boolean = false) {
        this.busy = busy
        val mgr = AppWidgetManager.getInstance(ctx)
        val p = prefs(ctx)
        val l = lang(ctx)
        ids(ctx, PriceWidget::class.java).forEach { mgr.updateAppWidget(it, PriceWidget.build(ctx, l, p, mgr, it)) }
        ids(ctx, PriceWidgetSmall::class.java).forEach { mgr.updateAppWidget(it, PriceWidgetSmall.build(ctx, l, p, it)) }
        ids(ctx, PriceWidgetList::class.java).forEach { mgr.updateAppWidget(it, PriceWidgetList.build(ctx, l, p)) }
    }
}

/** Common behaviour: taps (next asset, cash / holder), cleanup, and a fetch of the widgets' assets. */
abstract class BaseWidget : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, mgr: AppWidgetManager, ids: IntArray) {
        Widgets.refreshAll(ctx)
        WidgetWorker.enqueue(ctx, false)
    }

    override fun onAppWidgetOptionsChanged(ctx: Context, mgr: AppWidgetManager, id: Int, opts: Bundle) = Widgets.refreshAll(ctx)

    override fun onDeleted(ctx: Context, ids: IntArray) {
        val e = Widgets.prefs(ctx).edit()
        ids.forEach { e.remove("w_asset_$it") }
        e.apply()
    }

    override fun onReceive(ctx: Context, intent: Intent) {
        super.onReceive(ctx, intent)
        val id = intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)
        if (id == AppWidgetManager.INVALID_APPWIDGET_ID) return
        val p = Widgets.prefs(ctx)
        when (intent.action) {
            Widgets.ACT_NEXT -> {
                val a = Widgets.asset(p, id)
                Widgets.setAsset(p, id, Widgets.ASSETS[(Widgets.ASSETS.indexOf(a) + 1) % Widgets.ASSETS.size])
            }
            Widgets.ACT_POS -> {
                val a = Widgets.asset(p, id)
                Widgets.setHold(p, a, !Widgets.hold(p, a))
            }
            Widgets.ACT_REFRESH -> {
                Widgets.refreshAll(ctx, busy = true)
                WidgetWorker.enqueue(ctx, true, force = true)
                return
            }
            else -> return
        }
        Widgets.refreshAll(ctx)
        WidgetWorker.enqueue(ctx, true)
    }
}

/** Fetches the latest analysis and the last 24 closed hours for every asset a widget shows, then redraws. */
class WidgetWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val p = Widgets.prefs(applicationContext)
        val url = p.getString("server_url", null) ?: return Result.success()
        val tok = p.getString("token", "") ?: ""
        val now = System.currentTimeMillis()
        val force = inputData.getBoolean("force", false)
        try { IdeaCtx.refresh(p, needBtc = Widgets.assetsInUse(applicationContext).any { it in SimpleAdvice.FOLLOWS_BTC }) } catch (e: Exception) { }
        for (a in Widgets.assetsInUse(applicationContext)) {
            if (!force && now - p.getLong("w_fetched_$a", 0L) < 10 * 60_000L) continue
            try {
                val f = ApiClient(url, tok).decision("LIVE", 0, a)
                p.edit().putString(Widgets.key(a), f.raw).putLong("w_fetched_$a", now).apply()
            } catch (e: Exception) { continue }
            try {
                MarketClient(url, tok).bars(a, "H1")?.takeIf { it.size >= 2 }?.let { c ->
                    p.edit().putString("spark_$a", c.c.takeLast(24).joinToString(",")).apply()
                }
            } catch (e: Exception) { }
        }
        Widgets.refreshAll(applicationContext)
        return Result.success()
    }

    companion object {
        fun enqueue(ctx: Context, now: Boolean, force: Boolean = false) {
            val req = OneTimeWorkRequestBuilder<WidgetWorker>()
                .setInputData(androidx.work.workDataOf("force" to force))
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
            WorkManager.getInstance(ctx).enqueueUniqueWork("widget-fetch",
                if (now) ExistingWorkPolicy.REPLACE else ExistingWorkPolicy.KEEP, req)
        }
    }
}
