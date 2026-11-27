package com.goldaiquant.app

import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject

/**
 * «دفتر صفقاتي» (owner 2026-11-27): the owner's real spot trades, kept only on the phone. Each buy is an amount in
 * dollars at a price; a sale closes it. Costs as the owner pays them: digital assets a percentage of the amount for
 * buy + sell together (default 0.15 %), gold a fixed number of dollars per trade for buy + sell together (default 2).
 * It reports the real result: realized net, open buys valued at the last price, money locked, buys open > 30 days.
 */
object Journal {
    data class Trade(val id: Long, val asset: String, val amountUsd: Double, val buyPrice: Double, val buyAt: Long,
                     val sellPrice: Double? = null, val sellAt: Long? = null) {
        val qty: Double get() = amountUsd / buyPrice
        val open: Boolean get() = sellPrice == null
    }

    data class Costs(val cryptoRoundTripPct: Double = 0.15, val goldPerTradeUsd: Double = 2.0)

    data class Summary(val closed: Int, val wins: Int, val realizedUsd: Double, val open: Int, val lockedUsd: Double,
                       val unrealizedUsd: Double?, val stuck: Int)

    const val STUCK_DAYS = 30
    /** The owner's sell rule, shown as a reminder: +0.65 % (digital) / +15 USD per ounce (gold). */
    const val TARGET_PCT = 0.0065
    const val GOLD_TARGET_USD = 15.0

    fun cost(t: Trade, c: Costs): Double =
        if (t.asset == "XAU") c.goldPerTradeUsd else t.amountUsd * c.cryptoRoundTripPct / 100

    /** Net result in dollars of a sale (or of selling now at [price]). */
    fun net(t: Trade, price: Double, c: Costs): Double = t.qty * (price - t.buyPrice) - cost(t, c)

    fun target(t: Trade): Double = if (t.asset == "XAU") t.buyPrice + GOLD_TARGET_USD else t.buyPrice * (1 + TARGET_PCT)

    fun summary(ts: List<Trade>, c: Costs, priceOf: (String) -> Double?, now: Long = System.currentTimeMillis()): Summary {
        val closed = ts.filter { !it.open }
        val open = ts.filter { it.open }
        val nets = closed.map { net(it, it.sellPrice!!, c) }
        val unreal = open.map { t -> priceOf(t.asset)?.let { net(t, it, c) } }
        return Summary(closed.size, nets.count { it > 0 }, nets.sum(), open.size, open.sumOf { it.amountUsd },
            if (unreal.any { it == null }) null else unreal.filterNotNull().sum(),
            open.count { now - it.buyAt > STUCK_DAYS * 86_400_000L })
    }

    fun load(p: SharedPreferences): List<Trade> = try {
        val a = JSONArray(p.getString("journal", "[]"))
        (0 until a.length()).map { i ->
            val o = a.getJSONObject(i)
            Trade(o.getLong("id"), o.getString("asset"), o.getDouble("amount"), o.getDouble("buy"), o.getLong("buy_at"),
                if (o.has("sell")) o.getDouble("sell") else null, if (o.has("sell_at")) o.getLong("sell_at") else null)
        }
    } catch (e: Exception) { emptyList() }

    fun save(p: SharedPreferences, ts: List<Trade>) {
        val a = JSONArray()
        ts.forEach { t ->
            a.put(JSONObject().put("id", t.id).put("asset", t.asset).put("amount", t.amountUsd).put("buy", t.buyPrice)
                .put("buy_at", t.buyAt).apply {
                    t.sellPrice?.let { put("sell", it) }
                    t.sellAt?.let { put("sell_at", it) }
                })
        }
        p.edit().putString("journal", a.toString()).apply()
    }

    fun costs(p: SharedPreferences) = Costs(p.getFloat("j_cost_crypto", 0.15f).toDouble(), p.getFloat("j_cost_gold", 2f).toDouble())
    fun saveCosts(p: SharedPreferences, c: Costs) =
        p.edit().putFloat("j_cost_crypto", c.cryptoRoundTripPct.toFloat()).putFloat("j_cost_gold", c.goldPerTradeUsd.toFloat()).apply()
}
