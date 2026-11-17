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

    @Test fun adviceForEachCase() {
        val down = HorizonScenarios.of(card(a = Action.SELL), null, false)
        assertEquals(Advice.SELL_NOW to 69.0, HorizonScenarios.advice(down, hold = true))
        assertEquals(Advice.WAIT_BUY_LOWER to 69.0, HorizonScenarios.advice(down, hold = false))
        val up = HorizonScenarios.of(card(a = Action.BUY), null, false)
        assertEquals(Advice.KEEP_SELL_HIGHER to 75.0, HorizonScenarios.advice(up, hold = true))
        assertEquals(Advice.BUY_NOW to null, HorizonScenarios.advice(up, hold = false))
        val none = HorizonScenarios.of(card(), null, false)
        assertEquals(Advice.NOTHING to null, HorizonScenarios.advice(none, true))
        val between = HorizonScenarios.of(card("HOURS"), brief("NONE"), false)
        assertEquals(Advice.NOTHING to null, HorizonScenarios.advice(between, false))
    }

    @Test fun noLevelsNoLikely() {
        val c = card(a = Action.SELL).copy(levels = Levels(emptyList(), listOf(lv(74.0)), true, null))
        val v = HorizonScenarios.of(c, null, false)
        assertNull(v.down); assertEquals(Likely.NONE, v.likely)
        assertEquals(HorizonScenarios.Side(74.0, null), v.up)
    }
}
