package com.goldaiquant.app

import com.goldaiquant.app.HorizonScenarios.Advice
import com.goldaiquant.app.HorizonScenarios.Likely
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HorizonScenariosTest {
    private fun lv(p: Double) = Level("X", p, p - 0.5, p + 0.5, 3, "", 3, listOf("H1"), false)
    private fun card(h: String = "WEEK", a: Action = Action.WAIT, plan: Plan? = null, tilt: Int = 0) =
        HorizonCard(h, a, tilt, null, null, null, null, null, null, null, null, null, emptyList(), emptyList(),
            Levels(listOf(lv(70.0), lv(69.0)), listOf(lv(74.0), lv(75.0)), true, null), null, ProbState.NONE, null,
            true, null, null, 0, null, null, plan = plan)
    private fun plan(side: String, rec: Boolean = true) =
        Plan("X", rec, side, null, null, null, null, null, null, null, null, null, emptyList())
    private fun brief(likely: String?, lo: Double = 70.0, hi: Double = 74.0) = Brief("2026-11-17", "BEAR",
        listOf(Scenario("BEAR", 70.0, "S1", 69.0, "S2"), Scenario("BULL", 74.0, "R1", 75.0, "R2")),
        outcome3 = Outcome3(0.5, 0.2, 0.3, likely, 24, lo, hi))

    @Test fun scenariosComeFromTheCardLevels() {
        val v = HorizonScenarios.of(card(), null, false)
        assertEquals(HorizonScenarios.Side(70.0, 69.0), v.down)
        assertEquals(HorizonScenarios.Side(74.0, 75.0), v.up)
        assertEquals(Likely.NONE, v.likely)
    }

    @Test fun waitOrTiltNeverMarksASide() {
        assertEquals(Likely.NONE, HorizonScenarios.of(card(tilt = -1), null, false).likely)
        assertEquals(Likely.NONE, HorizonScenarios.of(card(plan = plan("SELL", rec = false)), null, false).likely)
    }

    @Test fun validatedActionMarksTheSide() {
        assertEquals(Likely.DOWN, HorizonScenarios.of(card(a = Action.SELL), null, false).likely)
        assertEquals(Likely.UP, HorizonScenarios.of(card(a = Action.BUY), null, false).likely)
    }

    @Test fun planWinsButNotInDemo() {
        assertEquals(Likely.UP, HorizonScenarios.of(card(a = Action.SELL, plan = plan("BUY")), null, false).likely)
        assertEquals(Likely.DOWN, HorizonScenarios.of(card(a = Action.SELL, plan = plan("BUY")), null, true).likely)
    }

    @Test fun hoursUseThePreRegisteredTableOnlyOnTheSameLevels() {
        val h = card("HOURS")
        assertEquals(Likely.DOWN, HorizonScenarios.of(h, brief("DOWN"), false).likely)
        assertEquals(Likely.UP, HorizonScenarios.of(h, brief("UP"), false).likely)
        assertEquals(Likely.BETWEEN, HorizonScenarios.of(h, brief("NONE"), false).likely)
        assertEquals(Likely.NONE, HorizonScenarios.of(h, brief(null), false).likely)              // no 5-point lead
        assertEquals(Likely.NONE, HorizonScenarios.of(h, brief("DOWN", lo = 68.0), false).likely)  // other levels
        assertEquals(Likely.NONE, HorizonScenarios.of(card("WEEK"), brief("DOWN"), false).likely)  // hours only
    }

    private val P = HorizonScenarios
    private fun hv(a: Action) = P.of(card("HOURS", a), null, false)      // hours: down 70→69, up 74→75
    private fun wv(a: Action) = P.of(card("WEEK", a).copy(levels = Levels(listOf(lv(64.0), lv(58.0)),
        listOf(lv(80.0), lv(88.0)), true, null)), null, false)                    // week: down 64→58, up 80→88

    @Test fun adviceSingleHorizon() {
        assertEquals(HorizonScenarios.Plan(Advice.SELL_NOW, 69.0, 74.0, null, "HOURS"), P.decide(hv(Action.SELL), wv(Action.WAIT), true))
        assertEquals(HorizonScenarios.Plan(Advice.WAIT_BUY_LOWER, 69.0, 74.0, null, "HOURS"), P.decide(hv(Action.SELL), wv(Action.WAIT), false))
        assertEquals(HorizonScenarios.Plan(Advice.KEEP_SELL_HIGHER, 75.0, 70.0, null, "HOURS"), P.decide(hv(Action.BUY), wv(Action.WAIT), true))
        assertEquals(HorizonScenarios.Plan(Advice.BUY_NOW, null, 70.0, null, "HOURS"), P.decide(hv(Action.BUY), wv(Action.WAIT), false))
        // hours agree with the week: hours drive
        assertEquals(HorizonScenarios.Plan(Advice.SELL_NOW, 69.0, 74.0, null, "HOURS"), P.decide(hv(Action.SELL), wv(Action.SELL), true))
        // hours have no direction: the week drives with its own levels
        assertEquals(HorizonScenarios.Plan(Advice.KEEP_SELL_HIGHER, 88.0, 64.0, null, "WEEK"), P.decide(hv(Action.WAIT), wv(Action.BUY), true))
        assertEquals(HorizonScenarios.Plan(Advice.WAIT_BUY_LOWER, 58.0, 80.0, null, "WEEK"), P.decide(hv(Action.WAIT), wv(Action.SELL), false))
        assertEquals(HorizonScenarios.Plan(Advice.NOTHING, null, null, null, null), P.decide(hv(Action.WAIT), wv(Action.WAIT), true))
        assertEquals(Advice.NOTHING, P.decide(null, null, false).advice)
    }

    @Test fun adviceMixedHorizons() {
        // a dip inside a weekly rise: sell now, buy back lower; exit above the hours up trigger
        assertEquals(HorizonScenarios.Plan(Advice.SELL_NOW, 69.0, 74.0, HorizonScenarios.Mix.DIP_IN_UPTREND, "HOURS"), P.decide(hv(Action.SELL), wv(Action.BUY), true))
        assertEquals(HorizonScenarios.Plan(Advice.WAIT_BUY_LOWER, 69.0, 74.0, HorizonScenarios.Mix.DIP_IN_UPTREND, "HOURS"), P.decide(hv(Action.SELL), wv(Action.BUY), false))
        // a bounce inside a weekly fall: holder sells higher, cash does not buy
        assertEquals(HorizonScenarios.Plan(Advice.KEEP_SELL_HIGHER, 75.0, 70.0, HorizonScenarios.Mix.BOUNCE_IN_DOWNTREND, "HOURS"), P.decide(hv(Action.BUY), wv(Action.SELL), true))
        assertEquals(HorizonScenarios.Plan(Advice.DONT_BUY, null, null, HorizonScenarios.Mix.BOUNCE_IN_DOWNTREND, "HOURS"), P.decide(hv(Action.BUY), wv(Action.SELL), false))
    }

    @Test fun staysBetweenIsNoDirection() {
        val between = P.of(card("HOURS"), brief("NONE"), false)
        assertEquals(Likely.BETWEEN, between.likely)
        assertEquals(Advice.NOTHING, P.decide(between, wv(Action.WAIT), true).advice)
        assertEquals("WEEK", P.decide(between, wv(Action.BUY), true).basis)
    }

    @Test fun noLevelsNoLikely() {
        val c = card(a = Action.SELL).copy(levels = Levels(emptyList(), listOf(lv(74.0)), true, null))
        val v = HorizonScenarios.of(c, null, false)
        assertNull(v.down); assertEquals(Likely.NONE, v.likely)
        assertEquals(HorizonScenarios.Side(74.0, null), v.up)
    }
}
