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
    enum class Msg { NEW, TARGET, FAILED_STOP, FAILED_TURN, EXPIRED }

    data class Active(val kind: SimpleAdvice.Kind, val price: Double, val buyAt: Double?, val sellAt: Double?,
                      val stop: Double?, val at: Long)

    data class Step(val msg: Msg?, val idea: Active?, val state: Active?, val coolUntil: Long)

    const val WINDOW_MS = 24L * 3600_000
    const val COOL_MS = 60L * 60_000

    private val TRADE = setOf(SimpleAdvice.Kind.BUY_NOW, SimpleAdvice.Kind.HOLD_SELL_ABOVE, SimpleAdvice.Kind.SELL_REBUY)
    private val WATCH = setOf(SimpleAdvice.Kind.WAIT_DIP, SimpleAdvice.Kind.WAIT)

    /** The idea shown behind «ماذا أفعل؟» on the HOURS card, plus the cancel level of a sell-and-rebuy (the
     *  nearest resistance above the price) and the tested side (true UP, false DOWN, null none). */
    data class Now(val idea: SimpleAdvice.Idea, val upStop: Double?, val testedUp: Boolean?, val trend: String?)

    fun now(d: Decision, asset: String, hold: Boolean, price: Double? = d.quote): Now? {
        if (d.isDemo || d.marketClosed || price == null) return null
        val c = HorizonModel.card(d, "HOURS")
        val lvl = LiveLevels.reanchor(c.levels, price)
        val tested = HorizonScenarios.of(c.copy(levels = lvl), d.brief.takeIf { LiveLevels.briefConsistent(it, price) }, d.isDemo).likely
        val testedUp = when (tested) { HorizonScenarios.Likely.UP -> true; HorizonScenarios.Likely.DOWN -> false; else -> null }
        val sup = lvl?.supports.orEmpty().map { it.price }
        val res = lvl?.resistances.orEmpty().map { it.price }
        val idea = SimpleAdvice.resolve(SimpleAdvice.decide(c.trend?.direction, price, sup, res, hold, asset), testedUp)
        return Now(idea, res.filter { it > price }.minOrNull(), testedUp, SimpleAdvice.trendCodeOf(c.trend?.direction))
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
            return if (end == null) Step(null, null, prev, coolUntil) else Step(end, prev, null, nowMs + COOL_MS)
        }
        if (nowMs < coolUntil) return Step(null, null, prev, coolUntil)
        val stale = prev != null && nowMs - prev.at >= WINDOW_MS
        if (i.kind !in TRADE && i.kind !in WATCH) return Step(null, null, if (stale) null else prev, coolUntil)
        if (prev != null && !stale && prev.kind == i.kind) return Step(null, null, prev, coolUntil)
        val stop = if (i.kind == SimpleAdvice.Kind.SELL_REBUY) n.upStop else i.invalid
        val a = Active(i.kind, price, i.buyAt, i.sellAt, stop, nowMs)
        return Step(Msg.NEW, a, a, coolUntil)
    }

    fun encode(a: Active?): String = a?.let {
        listOf(it.kind.name, it.price, it.buyAt ?: "", it.sellAt ?: "", it.stop ?: "", it.at).joinToString("|")
    } ?: ""

    fun decode(s: String?): Active? {
        val p = s?.split('|') ?: return null
        if (p.size != 6) return null
        val k = SimpleAdvice.Kind.values().firstOrNull { it.name == p[0] } ?: return null
        return Active(k, p[1].toDoubleOrNull() ?: return null, p[2].toDoubleOrNull(), p[3].toDoubleOrNull(),
            p[4].toDoubleOrNull(), p[5].toLongOrNull() ?: return null)
    }
}
