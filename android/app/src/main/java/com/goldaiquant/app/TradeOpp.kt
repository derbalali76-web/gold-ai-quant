package com.goldaiquant.app

import org.json.JSONObject

/** Experimental live paper trades (public ledger trade_engine/state.json, rule te-live-h1-0.1). Read-only: the app
 *  never computes a trade itself and never shows a probability of success. */
data class TeOrder(val seq: Int, val t: String, val limit: Double, val stop: Double, val target: Double,
                   val entryUntil: String, val holdBars: Int, val status: String,   // PENDING | OPEN
                   val entry: Double?, val fillTime: String?)

data class TeClosed(val seq: Int, val status: String, val limit: Double, val entry: Double?, val exit: Double?,
                    val net: Double?, val exitTime: String?)                         // TARGET | STOP | TIME | NOT_FILLED | NO_DATA

data class TeRecord(val orders: Int, val notFilled: Int, val closed: Int, val wins: Int, val losses: Int,
                    val meanNetPct: Double?)

data class TeState(val updatedAt: String, val price: Double?, val active: TeOrder?, val lastClosed: TeClosed?,
                   val record: TeRecord) {
    val hasTrade get() = active != null
}

object TradeOpp {
    const val URL = "https://raw.githubusercontent.com/derbalali76-web/ai-quant-ledger/main/trade_engine/state.json"

    private fun JSONObject.d(k: String): Double? = if (has(k) && !isNull(k)) optDouble(k).takeIf { it.isFinite() } else null
    private fun JSONObject.s(k: String): String? = if (has(k) && !isNull(k)) optString(k) else null

    fun parse(body: String?): TeState? {
        val o = try { JSONObject(body ?: return null) } catch (e: Exception) { return null }
        if (!o.optString("engine").startsWith("te-live")) return null
        val a = o.optJSONArray("active")?.optJSONObject(0)?.let { x ->
            val lim = x.d("limit"); val st = x.d("stop"); val tg = x.d("target")
            if (lim == null || st == null || tg == null || !(st < lim && lim < tg)) null
            else TeOrder(x.optInt("seq"), x.optString("t"), lim, st, tg, x.optString("entry_until"), x.optInt("hold_bars", 30),
                if (x.optString("status") == "OPEN") "OPEN" else "PENDING", x.d("entry"), x.s("fill_time"))
        }
        val c = o.optJSONObject("last_closed")?.let { x ->
            TeClosed(x.optInt("seq"), x.optString("status"), x.d("limit") ?: 0.0, x.d("entry"), x.d("exit"), x.d("net"), x.s("exit_time"))
        }
        val r = o.optJSONObject("record") ?: JSONObject()
        return TeState(o.optString("updated_at"), o.d("price"), a, c,
            TeRecord(r.optInt("orders"), r.optInt("not_filled"), r.optInt("closed"), r.optInt("wins"), r.optInt("losses"), r.d("mean_net_pct")))
    }

    /** Distance of a level from the entry price, in percent (before costs). */
    fun pctFrom(entry: Double, level: Double): Double = (level / entry - 1) * 100
}
