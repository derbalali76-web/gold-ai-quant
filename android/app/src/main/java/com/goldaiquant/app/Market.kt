package com.goldaiquant.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder
import java.time.Instant

/** Closed candles for the in-app chart (index = bar open time). */
data class Candles(val tf: String, val t: List<Long>, val o: List<Double>, val h: List<Double>, val l: List<Double>,
                   val c: List<Double>) {
    val size: Int get() = c.size
}

data class CalEvent(val time: Instant, val name: String, val importance: Int)
data class CalendarInfo(val state: String, val updatedAt: Instant?, val events: List<CalEvent>)
data class LiveTick(val price: Double, val at: Long)

/** Experimental 80 % interval for the CLOSE (price-range engine; qualified horizons only; never a recommendation). */
data class RangeH(val horizon: String, val low: Double, val high: Double, val closeAtIssue: Double, val issuedAt: String,
                  val eventName: String?, val eventTime: String?)
data class RangeInfo(val asset: String, val available: Boolean, val display: String?, val horizons: Map<String, RangeH>)

/** Touch probability (validated per asset and horizon; never a direction or a recommendation). */
data class TouchResult(val price: Double, val side: Int, val status: String, val probability: Double?, val usual: Double?)
data class TouchHorizon(val results: List<TouchResult>, val weak: Boolean)
data class TouchInfo(val asset: String, val available: Boolean, val price: Double?, val horizons: Map<String, TouchHorizon>)

object MarketParser {
    fun candles(body: String): Candles? = try {
        val o = JSONObject(body)
        fun arr(k: String): List<Double> { val a = o.getJSONArray(k); return (0 until a.length()).map { a.getDouble(it) } }
        val t = o.getJSONArray("t").let { a -> (0 until a.length()).map { a.getLong(it) } }
        val c = Candles(o.optString("tf", "H1"), t, arr("o"), arr("h"), arr("l"), arr("c"))
        if (c.t.size != c.c.size || c.o.size != c.c.size || c.h.size != c.c.size || c.l.size != c.c.size || c.size < 2) null
        else c
    } catch (e: Exception) { null }

    fun calendar(body: String): CalendarInfo? = try {
        val o = JSONObject(body)
        val ev = o.optJSONArray("events")
        val list = (0 until (ev?.length() ?: 0)).mapNotNull { i ->
            val e = ev!!.getJSONObject(i)
            try { CalEvent(Instant.parse(e.getString("time_utc").replace("+00:00", "Z")), e.optString("name"), e.optInt("importance", 1)) }
            catch (x: Exception) { null }
        }
        val upd = o.optString("updated_at").takeIf { it.isNotBlank() && it != "null" }?.let {
            try { Instant.parse(it.replace("+00:00", "Z")) } catch (x: Exception) { null }
        }
        CalendarInfo(o.optString("state", "NOT_CONFIGURED"), upd, list)
    } catch (e: Exception) { null }

    fun touch(body: String): TouchInfo? = try {
        val o = JSONObject(body)
        val hz = o.optJSONObject("horizons")
        val map = mutableMapOf<String, TouchHorizon>()
        hz?.keys()?.forEach { k ->
            val h = hz.getJSONObject(k)
            val a = h.optJSONArray("results")
            val res = (0 until (a?.length() ?: 0)).mapNotNull { i ->
                val e = a!!.optJSONObject(i) ?: return@mapNotNull null
                val p = if (e.has("probability") && !e.isNull("probability")) e.getDouble("probability") else null
                val u = if (e.has("usual") && !e.isNull("usual")) e.getDouble("usual") else null
                if (p != null && p !in 0.0..1.0) return@mapNotNull null
                TouchResult(e.getDouble("price"), e.optInt("side", 1), e.optString("status", "OK"), p, u?.takeIf { it in 0.0..1.0 })
            }
            map[k] = TouchHorizon(res, h.optBoolean("weak", false))
        }
        TouchInfo(o.optString("asset"), o.optBoolean("available", false),
            if (o.has("price") && !o.isNull("price")) o.getDouble("price") else null, map)
    } catch (e: Exception) { null }

    fun range(body: String): RangeInfo? = try {
        val o = JSONObject(body)
        val hz = o.optJSONObject("horizons")
        val map = mutableMapOf<String, RangeH>()
        hz?.keys()?.forEach { k ->
            val h = hz.getJSONObject(k)
            val lo = h.getDouble("low"); val hi = h.getDouble("high")
            if (!(lo < hi) || !lo.isFinite() || !hi.isFinite()) return@forEach
            val ev = h.optJSONObject("event")
            map[k] = RangeH(k, lo, hi, h.optDouble("close_at_issue"), h.optString("issued_at"),
                ev?.optString("name")?.takeIf { it.isNotBlank() }, ev?.optString("time_utc")?.takeIf { it.isNotBlank() })
        }
        val disp = o.optString("display").takeIf { !o.isNull("display") && it in map }
        RangeInfo(o.optString("asset"), o.optBoolean("available", false) && map.isNotEmpty(), disp, map)
    } catch (e: Exception) { null }

    /** Binance public ticker: {"symbol":"BTCUSDT","price":"91234.5"} */
    fun tickerPrice(body: String): Double? = try {
        JSONObject(body).getString("price").toDouble().takeIf { it > 0 }
    } catch (e: Exception) { null }
}

class MarketClient(private val baseUrl: String, private val token: String = "") {
    private fun get(url: String, auth: Boolean, readMs: Int = 30_000): String? {
        return try {
            val conn = (URI(url).toURL().openConnection() as HttpURLConnection).apply {
                connectTimeout = 10_000; readTimeout = readMs
                setRequestProperty("Accept", "application/json")
                if (auth && token.isNotBlank()) setRequestProperty("X-Goldquant-Token", token.trim())
            }
            try { if (conn.responseCode == 200) conn.inputStream.bufferedReader().use { it.readText() }.take(300_000) else null }
            finally { conn.disconnect() }
        } catch (e: Exception) { null }
    }

    suspend fun bars(asset: String, tf: String, limit: Int = 120): Candles? = withContext(Dispatchers.IO) {
        if (UrlPolicy.check(baseUrl) != null) return@withContext null
        get(baseUrl.trimEnd('/') + "/bars?asset=" + URLEncoder.encode(asset, "UTF-8") + "&tf=" + tf + "&limit=" + limit,
            true, 90_000)?.let(MarketParser::candles)
    }

    suspend fun range(asset: String): RangeInfo? = withContext(Dispatchers.IO) {
        if (UrlPolicy.check(baseUrl) != null) return@withContext null
        get(baseUrl.trimEnd('/') + "/range?asset=" + URLEncoder.encode(asset, "UTF-8"), true, 90_000)?.let(MarketParser::range)
    }

    suspend fun touch(asset: String, prices: List<Double>): TouchInfo? = withContext(Dispatchers.IO) {
        if (UrlPolicy.check(baseUrl) != null || prices.isEmpty()) return@withContext null
        val list = prices.take(8).joinToString(",") { String.format(java.util.Locale.US, "%.6f", it) }
        get(baseUrl.trimEnd('/') + "/touch?asset=" + URLEncoder.encode(asset, "UTF-8") + "&prices=" +
            URLEncoder.encode(list, "UTF-8"), true, 90_000)?.let(MarketParser::touch)
    }

    suspend fun calendar(): CalendarInfo? = withContext(Dispatchers.IO) {
        if (UrlPolicy.check(baseUrl) != null) return@withContext null
        get(baseUrl.trimEnd('/') + "/calendar", true, 90_000)?.let(MarketParser::calendar)
    }

    companion object {
        /** Live crypto price straight from Binance's public market-data host (no key, no account). */
        suspend fun livePrice(asset: String): Double? = withContext(Dispatchers.IO) {
            val sym = when (asset) { "BTC" -> "BTCUSDT"; "ETH" -> "ETHUSDT"; "SOL" -> "SOLUSDT"; else -> return@withContext null }
            MarketClient("", "").get("https://data-api.binance.vision/api/v3/ticker/price?symbol=$sym", false, 8_000)
                ?.let(MarketParser::tickerPrice)
        }
    }
}
