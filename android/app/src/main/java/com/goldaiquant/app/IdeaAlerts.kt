package com.goldaiquant.app

/**
 * Opportunity notifications (owner-approved 2026-11-25): the «ماذا أفعل؟» idea of the HOURS card, for the user's
 * own position on this asset (cash or holder), sent once when it appears, then ONE follow-up when it ends:
 *  - target reached, or
 *  - failed: the price touched the cancel level, or the tested «most likely» side turned against it, or
 *  - expired: 24 h without either.
 * Rules: a trade idea (buy now / keep and sell higher / sell now and buy back) is followed until it ends; a watch
 * idea (wait for a dip / wait) is replaced by the next different idea. At most one message per check, and no new
 * idea for [COOL_MS] after one ends. Same rule as the screen (SimpleAdvice + LiveLevels + the conflict filter).
 * Educational ideas only: never a guarantee, never an order.
 */
object IdeaAlerts {
    enum class Msg { NEW, UPDATED, WITHDRAWN, TARGET, FAILED_STOP, FAILED_TURN, EXPIRED }

    data class Active(val kind: SimpleAdvice.Kind, val price: Double, val buyAt: Double?, val sellAt: Double?,
                      val stop: Double?, val at: Long, val updAt: Long = 0L, val withdrawn: Boolean = false)

    /** [before] = the idea as it was announced, for an UPDATED message («new level instead of the old one»). */
    data class Step(val msg: Msg?, val idea: Active?, val state: Active?, val coolUntil: Long, val before: Active? = null)

    /** Owner 2026-11-26: when the same idea's levels move (the resistance went from 79 to 78 to 76), say so, so the
     *  user does not keep the first target. A level counts as moved beyond this share of the price; one update per
     *  [UPD_MS] at most. */
    const val MOVE_PCT = 0.003
    const val UPD_MS = 60L * 60_000

    const val WINDOW_MS = 24L * 3600_000
    const val COOL_MS = 60L * 60_000

    private fun moved(a: Double?, b: Double?, price: Double) = when {
        a == null && b == null -> false
        a == null || b == null -> true
        else -> kotlin.math.abs(a - b) >= price * MOVE_PCT
    }

    /** The same idea with new levels, or null when nothing moved enough (or an update was sent less than UPD_MS ago). */
    private fun update(prev: Active, n: Now, price: Double, nowMs: Long): Active? {
        val i = n.idea
        if (i.kind != prev.kind || nowMs - prev.updAt < UPD_MS) return null
        val stop = if (i.kind == SimpleAdvice.Kind.SELL_REBUY) n.upStop else i.invalid
        val buyMatters = i.kind != SimpleAdvice.Kind.BUY_NOW  // a buy-now's entry is the market price, not a level
        val mb = buyMatters && moved(prev.buyAt, i.buyAt, price)
        val ms = moved(prev.sellAt, i.sellAt, price)
        val mc = moved(prev.stop, stop, price)
        if (!mb && !ms && !mc) return null
        return prev.copy(buyAt = if (mb) i.buyAt else prev.buyAt, sellAt = if (ms) i.sellAt else prev.sellAt,
            stop = if (mc) stop else prev.stop, updAt = nowMs)
    }

    private val TRADE = setOf(SimpleAdvice.Kind.BUY_NOW, SimpleAdvice.Kind.HOLD_SELL_ABOVE, SimpleAdvice.Kind.SELL_REBUY)
    private val WATCH = setOf(SimpleAdvice.Kind.WAIT_DIP, SimpleAdvice.Kind.WAIT)

    /** The idea shown behind «ماذا أفعل؟» on the HOURS card, plus the cancel level of a sell-and-rebuy (the
     *  nearest resistance above the price) and the tested side (true UP, false DOWN, null none). */
    data class Now(val idea: SimpleAdvice.Idea, val upStop: Double?, val testedUp: Boolean?, val trend: String?)

    fun now(d: Decision, asset: String, hold: Boolean, price: Double? = d.quote,
            prefs: android.content.SharedPreferences? = null): Now? {
        if (d.isDemo || d.marketClosed || price == null) return null
        val b = IdeaCtx.build(d, HorizonModel.card(d, "HOURS"), asset, hold, price, prefs)
        return Now(b.idea, b.upStop, b.testedUp, b.trend)
    }

    fun step(prev: Active?, coolUntil: Long, n: Now, price: Double, nowMs: Long): Step {
        val i = n.idea
        if (prev != null && prev.kind in TRADE) {
            val end: Msg? = when (prev.kind) {
                SimpleAdvice.Kind.BUY_NOW -> when {
                    prev.sellAt != null && price >= prev.sellAt -> Msg.TARGET
                    prev.stop != null && price <= prev.stop -> Msg.FAILED_STOP
                    i.kind == SimpleAdvice.Kind.CONFLICT || n.trend == "DOWN" -> Msg.FAILED_TURN
                    else -> null
                }
                SimpleAdvice.Kind.HOLD_SELL_ABOVE -> when {
                    prev.sellAt != null && price >= prev.sellAt -> Msg.TARGET
                    prev.stop != null && price <= prev.stop -> Msg.FAILED_STOP
                    i.kind == SimpleAdvice.Kind.SELL_REBUY -> Msg.FAILED_TURN  // the screen now says sell
                    else -> null
                }
                else -> when {  // SELL_REBUY: the target is the buy-back level, the cancel level is above
                    prev.buyAt != null && price <= prev.buyAt -> Msg.TARGET
                    prev.stop != null && price >= prev.stop -> Msg.FAILED_STOP
                    i.kind == SimpleAdvice.Kind.CONFLICT || (n.trend == "UP" && i.kind != SimpleAdvice.Kind.SELL_REBUY) -> Msg.FAILED_TURN
                    else -> null
                }
            } ?: if (nowMs - prev.at >= WINDOW_MS) Msg.EXPIRED else null
            if (end != null) return Step(end, prev, null, nowMs + COOL_MS)
            // owner 2026-11-26: the screen no longer offers this trade (e.g. buy-now → wait) but nothing ended it:
            // say so once, with what to do if it was followed; keep following its target and cancel level.
            val offered = when (prev.kind) {
                SimpleAdvice.Kind.BUY_NOW -> i.kind == SimpleAdvice.Kind.BUY_NOW
                SimpleAdvice.Kind.SELL_REBUY -> i.kind == SimpleAdvice.Kind.SELL_REBUY
                else -> true
            }
            if (!offered && !prev.withdrawn) {
                val w = prev.copy(withdrawn = true)
                return Step(Msg.WITHDRAWN, w, w, coolUntil)
            }
            val u = update(prev, n, price, nowMs) ?: return Step(null, null, prev, coolUntil)
            return Step(Msg.UPDATED, u, u, coolUntil, prev)
        }
        if (nowMs < coolUntil) return Step(null, null, prev, coolUntil)
        val stale = prev != null && nowMs - prev.at >= WINDOW_MS
        if (i.kind !in TRADE && i.kind !in WATCH) return Step(null, null, if (stale) null else prev, coolUntil)
        if (prev != null && !stale && prev.kind == i.kind) {
            val u = update(prev, n, price, nowMs) ?: return Step(null, null, prev, coolUntil)
            return Step(Msg.UPDATED, u, u, coolUntil, prev)
        }
        val stop = if (i.kind == SimpleAdvice.Kind.SELL_REBUY) n.upStop else i.invalid
        val a = Active(i.kind, price, i.buyAt, i.sellAt, stop, nowMs)
        return Step(Msg.NEW, a, a, coolUntil)
    }

    fun encode(a: Active?): String = a?.let {
        listOf(it.kind.name, it.price, it.buyAt ?: "", it.sellAt ?: "", it.stop ?: "", it.at, it.updAt,
            if (it.withdrawn) 1 else 0).joinToString("|")
    } ?: ""

    fun decode(s: String?): Active? {
        val p = s?.split('|') ?: return null
        if (p.size !in 6..8) return null
        val k = SimpleAdvice.Kind.values().firstOrNull { it.name == p[0] } ?: return null
        return Active(k, p[1].toDoubleOrNull() ?: return null, p[2].toDoubleOrNull(), p[3].toDoubleOrNull(),
            p[4].toDoubleOrNull(), p[5].toLongOrNull() ?: return null, p.getOrNull(6)?.toLongOrNull() ?: 0L,
            p.getOrNull(7) == "1")
    }
}
