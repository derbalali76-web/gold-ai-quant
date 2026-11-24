package com.goldaiquant.app

/**
 * 2026-11-24 (owner report, SOL 69.63 while «الدعم» showed 70.58): the server computes levels at one moment while the
 * screen shows the live price. A level that the price has crossed changes role: it is no longer support (it is above
 * the price) or resistance (below it). This re-splits the SAME levels around the live price. Nothing is added or invented.
 */
object LiveLevels {
    fun reanchor(lv: Levels?, price: Double?): Levels? {
        if (lv == null || price == null || price <= 0.0) return lv
        val all = lv.supports + lv.resistances
        val sup = all.filter { it.price < price }.sortedByDescending { it.price }
        val res = all.filter { it.price > price }.sortedBy { it.price }
        return lv.copy(supports = sup, resistances = res)
    }

    /** The hours brief carries fixed triggers; once the price is outside them they are stale and must not be shown. */
    fun briefConsistent(b: Brief?, price: Double?): Boolean {
        if (b == null || price == null) return true
        val bear = b.scenarios.firstOrNull { it.kind == "BEAR" }?.trigger
        val bull = b.scenarios.firstOrNull { it.kind == "BULL" }?.trigger
        return (bear == null || bear < price) && (bull == null || bull > price)
    }
}
