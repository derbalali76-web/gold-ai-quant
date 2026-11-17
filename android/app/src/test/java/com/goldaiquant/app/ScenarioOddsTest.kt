package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ScenarioOddsTest {
    private fun sc(kind: String, trigger: Double) =
        Scenario(kind, trigger, if (kind == "BULL") "R1" else "S1", null, null, null)

    private fun brief(down: Double, lo: Double = 3852.90, hi: Double = 3869.61) = Brief("2026-11-17", "DOWN",
        listOf(sc("BEAR", 3852.90), sc("BULL", 3869.61)),
        firstTouch = FirstTouch(down, 1 - down, 1888, 728, 48, lo, hi))

    @Test fun percentagesAddUpAndMarkTheLikelySide() {
        val o = ScenarioOdds.of(brief(0.414))!!
        assertEquals(41, o.downPct); assertEquals(59, o.upPct); assertEquals("BULL", o.likely)
        assertEquals(59, o.pct("BULL")); assertEquals(41, o.pct("BEAR"))
        val d = ScenarioOdds.of(brief(0.705))!!
        assertEquals(100, d.downPct + d.upPct); assertEquals("BEAR", d.likely)
    }

    @Test fun tieHasNoLikelySide() {
        assertNull(ScenarioOdds.of(brief(0.5))!!.likely)
    }

    @Test fun hiddenWhenLevelsAreNotTodaysScenarios() {
        assertNull(ScenarioOdds.of(brief(0.41, lo = 3833.62)))
        assertNull(ScenarioOdds.of(Brief("d", "UP", listOf(sc("BEAR", 3852.90), sc("BULL", 3869.61)))))
        assertNull(ScenarioOdds.of(null))
    }
}
