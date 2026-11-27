package com.goldaiquant.app

/**
 * Beginner «ماذا أفعل؟» (owner-approved 2026-11-22): one idea from the selected horizon's trend and where the price
 * sits between that horizon's nearest support and resistance. Spot only: a cash user is never told to sell.
 * Every idea is shown as experimental; nothing here is a guarantee.
 */
object SimpleAdvice {
    enum class Kind {
        BUY_NOW,          // cash · rising · price not high → buy now, target the resistance
        WAIT_DIP,         // cash · rising · price high → wait for a pull-back, buy near the support
        WAIT,             // cash · falling (or sideways and not low) → wait, watch the support
        HOLD_SELL_ABOVE,  // holder · rising (or at support) → keep, sell above the resistance
        SELL_REBUY,       // holder · high in a rise, or falling with room down → sell now, buy back near the support
        CONFLICT,         // tested «most likely» side contradicts the idea: show hold/wait, no trade idea
        EVENT,            // a major economic event is close: no buy-now / sell-now until it has passed
        NONE,             // no levels or no price
    }

    /** Why an idea was changed by a filter (shown to the user). */
    enum class Note { BTC_DOWN, SELLERS }

    data class Idea(val kind: Kind, val buyAt: Double?, val sellAt: Double?, val invalid: Double?, val position: Double?,
                    val note: Note? = null)

    const val HIGH = 0.66
    const val LOW = 0.25

    /**
     * Owner-approved 2026-11-24: a sell-and-rebuy is only shown when the price sits at least this far above the
     * buy-back level. Gold: 15 USD. Digital assets: 0.65 % of the price. Below that the fees and spread eat the gap.
     */
    const val GOLD_MIN_GAP_USD = 15.0
    const val CRYPTO_MIN_GAP_PCT = 0.0065

    /** 2026-11-26 (owner: «نفذ كل ما ذكرته»): the gap also scales with the market's hourly movement (ATR of H1):
     *  never below the owner's floor, but at least [ATR_GAP_K] hourly ranges on a wild day. */
    const val ATR_GAP_K = 1.0
    /** Cancel level when there is no lower support: [ATR_INV_K] hourly ranges below the support (was 1.5 % flat). */
    const val ATR_INV_K = 1.5
    /** Altcoins (ETH, SOL) follow bitcoin: no «buy now» on them while bitcoin's trend on the same horizon is down. */
    val FOLLOWS_BTC = setOf("ETH", "SOL")
    /** 2026-11-27 (research entry-0.1): on digital assets, no «buy now» while sellers dominated the last 4 hours
     *  (taker-buy share of the volume < 0.5). On two years of history it halved the loss per trade in both periods. */
    val CRYPTO = setOf("BTC", "ETH", "SOL")
    const val BUYERS_MIN = 0.5

    fun minGap(asset: String, price: Double, atr: Double? = null): Double =
        maxOf(if (asset == "XAU") GOLD_MIN_GAP_USD else price * CRYPTO_MIN_GAP_PCT, (atr ?: 0.0) * ATR_GAP_K)

    fun decide(trend: String?, price: Double?, supports: List<Double>, resistances: List<Double>, hold: Boolean,
               asset: String = "XAU", atr: Double? = null, btcTrend: String? = null, buyPressure: Double? = null): Idea {
        val p = price ?: return Idea(Kind.NONE, null, null, null, null)
        val s = supports.filter { it < p }.maxOrNull() ?: supports.minOrNull()
        val r = resistances.filter { it > p }.minOrNull() ?: resistances.maxOrNull()
        if (s == null || r == null || r <= s) return Idea(Kind.NONE, null, null, null, null)
        val pos = ((p - s) / (r - s)).coerceIn(0.0, 1.0)
        val high = pos > HIGH
        val low = pos < LOW
        val below = supports.filter { it < s }.maxOrNull() ?: atr?.takeIf { it > 0 }?.let { s - ATR_INV_K * it } ?: s * 0.985
        val btcDown = asset in FOLLOWS_BTC && trendCodeOf(btcTrend) == "DOWN"
        val sellers = asset in CRYPTO && buyPressure != null && buyPressure < BUYERS_MIN
        val dir = trendCodeOf(trend)
        // sell now and buy back at s, only when the gap covers the minimum; otherwise hold and say so
        fun sellRebuy(): Idea =
            if (p - s >= minGap(asset, p, atr)) Idea(Kind.SELL_REBUY, s, p, null, pos)
            else Idea(Kind.HOLD_SELL_ABOVE, null, r, below, pos)
        return if (!hold) when {
            dir == "UP" && !high && btcDown -> Idea(Kind.WAIT_DIP, s, r, below, pos, Note.BTC_DOWN)
            dir == "UP" && !high && sellers -> Idea(Kind.WAIT_DIP, s, r, below, pos, Note.SELLERS)
            dir == "UP" && !high -> Idea(Kind.BUY_NOW, p, r, below, pos)
            dir == "UP" -> Idea(Kind.WAIT_DIP, s, r, below, pos)
            dir == "SIDEWAYS" && low && btcDown -> Idea(Kind.WAIT_DIP, s, r, below, pos, Note.BTC_DOWN)
            dir == "SIDEWAYS" && low && sellers -> Idea(Kind.WAIT_DIP, s, r, below, pos, Note.SELLERS)
            dir == "SIDEWAYS" && low -> Idea(Kind.BUY_NOW, p, r, below, pos)
            else -> Idea(Kind.WAIT, s, null, below, pos)
        } else when {
            dir == "UP" && high -> sellRebuy()
            dir == "UP" -> Idea(Kind.HOLD_SELL_ABOVE, null, r, below, pos)
            low -> Idea(Kind.HOLD_SELL_ABOVE, null, r, below, pos)  // don't sell at the bottom
            dir == "DOWN" -> sellRebuy()
            high -> sellRebuy()                                     // sideways near the top
            else -> Idea(Kind.HOLD_SELL_ABOVE, null, r, below, pos)
        }
    }

    fun trendCodeOf(dir: String?): String? = when (dir) {
        "UP" -> "UP"; "DOWN" -> "DOWN"; "SIDEWAYS", "NEUTRAL" -> "SIDEWAYS"; else -> null
    }

    /**
     * Owner-approved 2026-11-24: when the tested «most likely» side of the same screen contradicts the idea
     * (tested UP vs sell-now, tested DOWN vs buy-now) the idea is withdrawn. [testedUp] = true UP, false DOWN, null none.
     */
    fun resolve(idea: Idea, testedUp: Boolean?): Idea = when {
        testedUp == true && idea.kind == Kind.SELL_REBUY -> Idea(Kind.CONFLICT, null, null, null, idea.position)
        testedUp == false && idea.kind == Kind.BUY_NOW -> Idea(Kind.CONFLICT, null, null, null, idea.position)
        else -> idea
    }

    /** A major event (importance 3) from [EVENT_BEFORE_H] hours before to [EVENT_AFTER_H] after it: buy-now and
     *  sell-now ideas are held (display only; the public ledger cannot see the calendar and does not score this). */
    const val EVENT_BEFORE_H = 2L
    const val EVENT_AFTER_H = 1L

    fun eventSoon(cal: CalendarInfo?, now: java.time.Instant = java.time.Instant.now()): CalEvent? =
        cal?.events?.filter { it.importance >= 3 }?.firstOrNull {
            !now.isBefore(it.time.minusSeconds(EVENT_BEFORE_H * 3600)) && !now.isAfter(it.time.plusSeconds(EVENT_AFTER_H * 3600))
        }

    fun withEvent(idea: Idea, ev: CalEvent?): Idea =
        if (ev != null && (idea.kind == Kind.BUY_NOW || idea.kind == Kind.SELL_REBUY))
            Idea(Kind.EVENT, null, null, null, idea.position) else idea
}
