package com.goldaiquant.app

/** Which validated BUY/SELL signals are new since the last check (pure logic, unit-tested). */
object SignalWatch {
    data class Signal(val horizon: String, val action: Action)

    /** Validated trade signals in [d]: HOURS from the main decision, WEEK / MONTH from their outlooks. LIVE only. */
    fun signals(d: Decision): List<Signal> {
        if (d.isDemo) return emptyList()
        val trade = { a: Action -> a == Action.BUY || a == Action.SELL }
        val out = mutableListOf<Signal>()
        val hours = d.outlooks.firstOrNull { it.horizon == "HOURS" }
        if (trade(d.action) && hours?.validated == true) out += Signal("HOURS", d.action)
        d.outlooks.filter { it.horizon != "HOURS" && it.validated && trade(it.action) }.forEach { out += Signal(it.horizon, it.action) }
        return out
    }

    /** Returns the signals to announce and the new memory (horizon -> action of the last announced signal).
     *  A horizon that is no longer signalling is forgotten, so the same signal later is announced again. */
    fun diff(d: Decision, last: Map<String, String>): Pair<List<Signal>, Map<String, String>> {
        val now = signals(d)
        val fresh = now.filter { last[it.horizon] != it.action.name }
        return fresh to now.associate { it.horizon to it.action.name }
    }
}
