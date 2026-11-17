package com.goldaiquant.app

/**
 * Beginner screen (approved by the owner 2026-11-17): for each horizon card, two scenarios (down / up) built from
 * that card's levels, a «most likely» mark ONLY when evidence that already passed a test supports it, and one
 * plain instruction behind «ماذا أفعل؟». The evidence itself is never shown on this screen.
 *
 * Evidence accepted, in this order (nothing else can mark a side):
 *  1. a validated trade plan of this horizon (plan.recommendation, not demo): its side;
 *  2. HOURS only: the pre-registered next-24h table (outcome3-0.1.0) when its cell passed the usable test and its
 *     two levels are exactly today's two scenario triggers: DOWN / UP, or NONE = «stays between»;
 *  3. the card's own action when it is a validated BUY / SELL (WEEK / MONTH rules, HOURS court).
 * A WAIT, a tilt, a bias or an unvalidated odds number never marks a side.
 */
object HorizonScenarios {
    enum class Likely { DOWN, UP, BETWEEN, NONE }

    data class Side(val trigger: Double, val target: Double?)

    data class View(val down: Side?, val up: Side?, val likely: Likely)

    enum class Advice { SELL_NOW, WAIT_BUY_LOWER, KEEP_SELL_HIGHER, BUY_NOW, NOTHING }

    private fun same(a: Double, b: Double) = kotlin.math.abs(a - b) <= maxOf(0.011, kotlin.math.abs(b) * 1e-7)

    fun of(c: HorizonCard, brief: Brief?, demo: Boolean): View {
        var down: Side? = null
        var up: Side? = null
        if (c.horizon == "HOURS" && brief != null) {
            val bear = brief.scenarios.firstOrNull { it.kind == "BEAR" }
            val bull = brief.scenarios.firstOrNull { it.kind == "BULL" }
            if (bear != null) down = Side(bear.trigger, bear.target)
            if (bull != null) up = Side(bull.trigger, bull.target)
        }
        val sup = c.levels?.supports.orEmpty()
        val res = c.levels?.resistances.orEmpty()
        if (down == null && sup.isNotEmpty()) down = Side(sup[0].price, sup.getOrNull(1)?.price)
        if (up == null && res.isNotEmpty()) up = Side(res[0].price, res.getOrNull(1)?.price)

        val plan = c.plan
        val likely = when {
            plan?.recommendation == true && !demo && plan.side == "SELL" -> Likely.DOWN
            plan?.recommendation == true && !demo && plan.side == "BUY" -> Likely.UP
            c.horizon == "HOURS" && outcome(brief, down, up) != null -> outcome(brief, down, up)!!
            c.action == Action.SELL -> Likely.DOWN
            c.action == Action.BUY -> Likely.UP
            else -> Likely.NONE
        }
        // a side cannot be «likely» without its own scenario
        val ok = when (likely) {
            Likely.DOWN -> down != null; Likely.UP -> up != null; Likely.BETWEEN -> down != null && up != null
            Likely.NONE -> true
        }
        return View(down, up, if (ok) likely else Likely.NONE)
    }

    private fun outcome(b: Brief?, down: Side?, up: Side?): Likely? {
        val o = b?.outcome3 ?: return null
        if (down == null || up == null || !same(o.downLevel, down.trigger) || !same(o.upLevel, up.trigger)) return null
        return when (o.likely) { "DOWN" -> Likely.DOWN; "UP" -> Likely.UP; "NONE" -> Likely.BETWEEN; else -> null }
    }

    /** The one instruction for «ماذا أفعل؟» and the price it names (null for BUY_NOW / NOTHING). */
    fun advice(v: View, hold: Boolean): Pair<Advice, Double?> = when (v.likely) {
        Likely.DOWN -> {
            val at = v.down!!.target ?: v.down.trigger
            if (hold) Advice.SELL_NOW to at else Advice.WAIT_BUY_LOWER to at
        }
        Likely.UP -> if (hold) Advice.KEEP_SELL_HIGHER to (v.up!!.target ?: v.up.trigger) else Advice.BUY_NOW to null
        else -> Advice.NOTHING to null
    }
}
