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

    enum class Advice { SELL_NOW, WAIT_BUY_LOWER, KEEP_SELL_HIGHER, BUY_NOW, DONT_BUY, NOTHING }

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

    enum class Mix { DIP_IN_UPTREND, BOUNCE_IN_DOWNTREND }

    /**
     * advice-0.1.0 (owner-approved 2026-11-17, pre-registered in the public ledger before any outcome):
     * one instruction from the HOURS and WEEK views, whatever tab is open.
     *  - hours DOWN + week UP (a dip inside a weekly rise): holder sells now and buys back at the hours down target,
     *    cash waits to buy there; exit = the hours up trigger (rebuy / buy if it is crossed first);
     *  - hours UP + week DOWN (a bounce inside a weekly fall): holder keeps and sells at the hours up target
     *    (exit: sell below the hours down trigger); cash does not buy;
     *  - otherwise the first horizon with a direction (hours, then week) drives:
     *    DOWN → holder sells now / cash waits, both at its down target, exit above its up trigger;
     *    UP → holder keeps and sells at its up target / cash buys now, exit below its down trigger;
     *  - no direction (none, «stays between») → nothing.
     */
    data class Plan(val advice: Advice, val at: Double?, val exit: Double?, val mix: Mix?, val basis: String?)

    private fun dir(v: View?) = when (v?.likely) { Likely.DOWN -> -1; Likely.UP -> 1; else -> 0 }
    private fun downAt(v: View) = v.down?.let { it.target ?: it.trigger }
    private fun upAt(v: View) = v.up?.let { it.target ?: it.trigger }

    fun decide(hours: View?, week: View?, hold: Boolean): Plan {
        val h = dir(hours); val w = dir(week)
        if (h == -1 && w == 1) {
            val at = downAt(hours!!); val exit = hours.up?.trigger
            return Plan(if (hold) Advice.SELL_NOW else Advice.WAIT_BUY_LOWER, at, exit, Mix.DIP_IN_UPTREND, "HOURS")
        }
        if (h == 1 && w == -1) {
            return if (hold) Plan(Advice.KEEP_SELL_HIGHER, upAt(hours!!), hours.down?.trigger, Mix.BOUNCE_IN_DOWNTREND, "HOURS")
            else Plan(Advice.DONT_BUY, null, null, Mix.BOUNCE_IN_DOWNTREND, "HOURS")
        }
        val (v, basis) = when { h != 0 -> hours!! to "HOURS"; w != 0 -> week!! to "WEEK"; else -> return Plan(Advice.NOTHING, null, null, null, null) }
        return if (dir(v) == -1) Plan(if (hold) Advice.SELL_NOW else Advice.WAIT_BUY_LOWER, downAt(v), v.up?.trigger, null, basis)
        else Plan(if (hold) Advice.KEEP_SELL_HIGHER else Advice.BUY_NOW, if (hold) upAt(v) else null, v.down?.trigger, null, basis)
    }
}
