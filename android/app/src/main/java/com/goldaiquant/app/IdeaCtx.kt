package com.goldaiquant.app

import android.content.SharedPreferences
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URI

/**
 * What the «ماذا أفعل؟» idea needs besides the asset's own analysis (owner 2026-11-26, «نفذ كل ما ذكرته»):
 * bitcoin's trend (altcoins follow it), the economic calendar (no buy-now / sell-now right before a major event),
 * the crypto derivatives crowding and the public record of each idea kind. Kept in the phone's preferences so the
 * screen, the notifications and the widgets use the same inputs. Every part is optional: missing data = no filter.
 */
object IdeaCtx {
    private const val BTC_MAX_AGE_MS = 15 * 60_000L
    private const val CAL_MAX_AGE_MS = 6 * 3600_000L
    private const val DERIV_MAX_AGE_MS = 15 * 60_000L
    private const val REC_MAX_AGE_MS = 3 * 3600_000L
    const val RECORD_URL = "https://raw.githubusercontent.com/derbalali76-web/ai-quant-ledger/main/studies/beginner_ideas_stats.json"

    fun btc(p: SharedPreferences): Decision? =
        p.getString("last_decision_BTC", null)?.let { try { DecisionParser.parse(it) } catch (e: Exception) { null } }

    fun btcTrend(p: SharedPreferences, horizon: String): String? =
        btc(p)?.takeIf { !it.isDemo }?.let { HorizonModel.card(it, horizon).trend?.direction }

    fun calendar(p: SharedPreferences): CalendarInfo? = p.getString("cal_json", null)?.let(MarketParser::calendar)

    /** Funding / open interest per asset from the server (/derivs), or null. */
    fun derivs(p: SharedPreferences, asset: String): Derivs? = p.getString("derivs_json", null)?.let { Derivs.parse(it, asset) }

    /** The public record of an idea kind on a horizon: (scored, success rate, mean edge %), or null. */
    fun record(p: SharedPreferences, kind: String, horizon: String): RecordStat? =
        p.getString("rec_json", null)?.let { RecordStat.parse(it, kind, horizon) }

    private fun get(url: String, token: String?): String? = try {
        val c = (URI(url).toURL().openConnection() as HttpURLConnection).apply {
            connectTimeout = 10_000; readTimeout = 60_000
            setRequestProperty("Accept", "application/json")
            if (!token.isNullOrBlank()) setRequestProperty("X-Goldquant-Token", token.trim())
        }
        try { if (c.responseCode == 200) c.inputStream.bufferedReader().use { it.readText() }.take(400_000) else null }
        finally { c.disconnect() }
    } catch (e: Exception) { null }

    /** Refreshes whatever is stale. [needBtc] when an altcoin is shown or followed. Never throws. */
    suspend fun refresh(p: SharedPreferences, needBtc: Boolean) = withContext(Dispatchers.IO) {
        val url = p.getString("server_url", null) ?: "https://gold-ai-quant.onrender.com"
        if (UrlPolicy.check(url) != null) return@withContext
        val tok = p.getString("token", "") ?: ""
        val now = System.currentTimeMillis()
        if (needBtc && now - p.getLong("ctx_btc_at", 0L) > BTC_MAX_AGE_MS) try {
            val f = ApiClient(url, tok).decision("LIVE", 0, "BTC")
            p.edit().putString("last_decision_BTC", f.raw).putLong("ctx_btc_at", now).apply()
        } catch (e: Exception) { }
        if (now - p.getLong("cal_at", 0L) > CAL_MAX_AGE_MS) get(url.trimEnd('/') + "/calendar", tok)?.let {
            if (MarketParser.calendar(it) != null) p.edit().putString("cal_json", it).putLong("cal_at", now).apply()
        }
        if (now - p.getLong("derivs_at", 0L) > DERIV_MAX_AGE_MS) get(url.trimEnd('/') + "/derivs", tok)?.let {
            p.edit().putString("derivs_json", it).putLong("derivs_at", now).apply()
        }
        if (now - p.getLong("rec_at", 0L) > REC_MAX_AGE_MS) get(RECORD_URL, null)?.let {
            p.edit().putString("rec_json", it).putLong("rec_at", now).apply()
        }
    }

    /** The idea for one card, with every filter: live levels, ATR gaps, bitcoin filter, tested side, events. */
    data class Built(val idea: SimpleAdvice.Idea, val testedUp: Boolean?, val upStop: Double?, val trend: String?,
                     val event: CalEvent?)

    fun build(d: Decision, c: HorizonCard, asset: String, hold: Boolean, price: Double?, p: SharedPreferences?,
              now: java.time.Instant = java.time.Instant.now()): Built {
        val lvl = LiveLevels.reanchor(c.levels, price)
        val tested = HorizonScenarios.of(c.copy(levels = lvl), d.brief.takeIf { LiveLevels.briefConsistent(it, price) }, d.isDemo).likely
        val testedUp = when (tested) { HorizonScenarios.Likely.UP -> true; HorizonScenarios.Likely.DOWN -> false; else -> null }
        val sup = lvl?.supports.orEmpty().map { it.price }
        val res = lvl?.resistances.orEmpty().map { it.price }
        val btcTrend = if (asset in SimpleAdvice.FOLLOWS_BTC && p != null) btcTrend(p, c.horizon) else null
        val ev = p?.let { SimpleAdvice.eventSoon(calendar(it), now) }
        val bp = if (c.horizon == "HOURS") d.buyPressure4h else null
        val raw = SimpleAdvice.decide(c.trend?.direction, price, sup, res, hold, asset, d.levels?.atrH1, btcTrend, bp)
        val idea = SimpleAdvice.withEvent(SimpleAdvice.resolve(raw, testedUp), ev)
        return Built(idea, testedUp, price?.let { px -> res.filter { it > px }.minOrNull() }, SimpleAdvice.trendCodeOf(c.trend?.direction), ev)
    }
}

/** Perpetual-futures crowding for one asset (server /derivs, from a public exchange API). */
data class Derivs(val fundingHourly: Double?, val openInterestUsd: Double?, val oiChange24hPct: Double?) {
    /** Longs pay a lot = crowded long; shorts pay a lot = crowded short. Threshold: 0.01 % per hour (≈ 88 % a year). */
    val crowdedLong: Boolean get() = (fundingHourly ?: 0.0) >= CROWD
    val crowdedShort: Boolean get() = (fundingHourly ?: 0.0) <= -CROWD

    companion object {
        const val CROWD = 0.0001
        fun parse(body: String, asset: String): Derivs? = try {
            val o = org.json.JSONObject(body).optJSONObject("assets")?.optJSONObject(asset)
            o?.let {
                fun d(k: String) = if (it.has(k) && !it.isNull(k)) it.getDouble(k) else null
                Derivs(d("funding_hourly"), d("open_interest_usd"), d("oi_change_24h_pct"))
            }
        } catch (e: Exception) { null }
    }
}

/** The public ledger's result for one idea kind and horizon (beginner ideas). */
data class RecordStat(val n: Int, val successRate: Double?, val meanEdgePct: Double?, val verdict: String) {
    companion object {
        fun parse(body: String, kind: String, horizon: String): RecordStat? = try {
            val o = org.json.JSONObject(body).optJSONObject("by_kind_horizon")?.optJSONObject("$kind|$horizon")
            o?.let {
                RecordStat(it.optInt("n"), if (it.has("success_rate")) it.getDouble("success_rate") else null,
                    if (it.has("mean_edge_pct")) it.getDouble("mean_edge_pct") else null, it.optString("verdict"))
            }
        } catch (e: Exception) { null }
    }
}
