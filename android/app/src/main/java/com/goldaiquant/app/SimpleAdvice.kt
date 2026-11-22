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
        NONE,             // no levels or no price
    }

    data class Idea(val kind: Kind, val buyAt: Double?, val sellAt: Double?, val invalid: Double?, val position: Double?)

    const val HIGH = 0.66
    const val LOW = 0.25

    fun decide(trend: String?, price: Double?, supports: List<Double>, resistances: List<Double>, hold: Boolean): Idea {
        val p = price ?: return Idea(Kind.NONE, null, null, null, null)
        val s = supports.filter { it < p }.maxOrNull() ?: supports.minOrNull()
        val r = resistances.filter { it > p }.minOrNull() ?: resistances.maxOrNull()
        if (s == null || r == null || r <= s) return Idea(Kind.NONE, null, null, null, null)
        val pos = ((p - s) / (r - s)).coerceIn(0.0, 1.0)
        val high = pos > HIGH
        val low = pos < LOW
        val below = supports.filter { it < s }.maxOrNull() ?: s * 0.985
        val dir = trendCodeOf(trend)
        return if (!hold) when {
            dir == "UP" && !high -> Idea(Kind.BUY_NOW, p, r, below, pos)
            dir == "UP" -> Idea(Kind.WAIT_DIP, s, r, below, pos)
            dir == "SIDEWAYS" && low -> Idea(Kind.BUY_NOW, p, r, below, pos)
            else -> Idea(Kind.WAIT, s, null, below, pos)
        } else when {
            dir == "UP" && high -> Idea(Kind.SELL_REBUY, s, p, null, pos)
            dir == "UP" -> Idea(Kind.HOLD_SELL_ABOVE, null, r, below, pos)
            low -> Idea(Kind.HOLD_SELL_ABOVE, null, r, below, pos)  // don't sell at the bottom
            dir == "DOWN" -> Idea(Kind.SELL_REBUY, s, p, null, pos)
            high -> Idea(Kind.SELL_REBUY, s, p, null, pos)            // sideways near the top
            else -> Idea(Kind.HOLD_SELL_ABOVE, null, r, below, pos)
        }
    }

    fun trendCodeOf(dir: String?): String? = when (dir) {
        "UP" -> "UP"; "DOWN" -> "DOWN"; "SIDEWAYS", "NEUTRAL" -> "SIDEWAYS"; else -> null
    }
}
