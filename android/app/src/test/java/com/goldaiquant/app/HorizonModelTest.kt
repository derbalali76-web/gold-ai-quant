package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HorizonModelTest {
    private fun fixture(name: String): Decision =
        DecisionParser.parse(javaClass.classLoader!!.getResourceAsStream("fixtures/$name")!!.bufferedReader().use { it.readText() })

    @Test fun parsesReasonRefsLevelsAndTrendPerHorizon() {
        val d = fixture("wait_demo.json")
        assertNotNull(d.reasonShort)
        assertEquals("rs.short", d.reasonShort!!.code)
        val week = d.outlooks.first { it.horizon == "WEEK" }
        assertNotNull(week.reason)
        assertNotNull(week.levels)
        assertNotNull(week.trend)
        assertTrue("daily levels never carry a numeric strength", week.levels!!.supports.all { it.strength == null })
        assertTrue(week.levels!!.supports.all { it.timeframes == listOf("D1") })
    }

    @Test fun selectionFallsBackToHoursAndKeepsAvailableSavedChoice() {
        val d = fixture("wait_demo.json")
        assertEquals("HOURS", HorizonModel.resolve(null, d))
        assertEquals("WEEK", HorizonModel.resolve("WEEK", d))
        assertEquals("MONTH", HorizonModel.resolve("MONTH", d))
        assertEquals("HOURS", HorizonModel.resolve("YEAR", d))
        assertEquals("WEEK", HorizonModel.resolve("WEEK", null))
    }

    @Test fun eachHorizonHasItsOwnIndependentCard() {
        val d = fixture("live_qualified_stub.json")
        val h = HorizonModel.card(d, "HOURS")
        val w = HorizonModel.card(d, "WEEK")
        val m = HorizonModel.card(d, "MONTH")
        assertEquals(Action.BUY, h.action)
        assertEquals(d.entryMin, h.entryLow)
        assertEquals(d.tp1, h.target)
        assertEquals(d.horizonMinutes, h.durationMinutes)
        assertNotNull(h.outcomes)
        assertEquals(ProbState.AVAILABLE, h.probState)
        // WEEK / MONTH are separate analyses: other fields, never HOURS numbers, never probabilities
        assertEquals("WEEK", w.horizon)
        assertEquals("MONTH", m.horizon)
        assertNull(w.outcomes)
        assertEquals(ProbState.HORIZON_UNSUPPORTED, w.probState)
        assertEquals(ProbState.HORIZON_UNSUPPORTED, m.probState)
        assertTrue(w.entryLow != h.entryLow || w.action != h.action)
        assertNotNull(w.durationDays)
        assertNull(w.durationMinutes)
    }

    @Test fun demoNeverShowsProbabilitiesForAnyHorizon() {
        val d = fixture("buy_demo_stub.json")
        val h = HorizonModel.card(d, "HOURS")
        assertEquals(ProbState.DEMO, h.probState)
        assertNull(h.outcomes)
    }

    @Test fun unavailableDecisionYieldsUnavailableCardsWithoutNumbers() {
        val d = fixture("unavailable_live.json")
        val h = HorizonModel.card(d, "HOURS")
        assertEquals(Action.UNAVAILABLE, h.action)
        assertEquals(ProbState.NONE, h.probState)
        assertNull(h.entryLow)
        assertEquals(Action.UNAVAILABLE, HorizonModel.card(d, "MONTH").action)
    }

    private fun lvl(lo: Double, hi: Double) = Level("X", (lo + hi) / 2, lo, hi, null, "", 3, listOf("H1"), false)

    private fun buyCard() = HorizonCard("HOURS", Action.BUY, 1, null, 100.0, 100.0, 95.0, 110.0, 240, null, null, null,
        emptyList(), emptyList(), null, null, ProbState.NONE, null, true, null, null, 0, null, null)

    private fun sellCard() = buyCard().copy(action = Action.SELL, stop = 105.0, target = 90.0)

    @Test fun buyLevelRelations() {
        val c = buyCard()
        assertEquals(LevelRelation.OBSTACLE_BEFORE_TARGET, HorizonModel.relation(lvl(104.0, 106.0), false, c))
        assertEquals(LevelRelation.NOT_IN_PATH, HorizonModel.relation(lvl(112.0, 114.0), false, c))
        assertEquals(LevelRelation.PROTECTS_STOP, HorizonModel.relation(lvl(96.0, 98.0), true, c))
        assertEquals(LevelRelation.STOP_INSIDE_ZONE, HorizonModel.relation(lvl(94.0, 96.0), true, c))
    }

    @Test fun sellLevelRelationsAreMirrored() {
        val c = sellCard()
        assertEquals(LevelRelation.OBSTACLE_BEFORE_TARGET, HorizonModel.relation(lvl(93.0, 95.0), true, c))
        assertEquals(LevelRelation.PROTECTS_STOP, HorizonModel.relation(lvl(101.0, 103.0), false, c))
        assertEquals(LevelRelation.STOP_INSIDE_ZONE, HorizonModel.relation(lvl(104.0, 106.0), false, c))
        assertEquals(LevelRelation.NOT_IN_PATH, HorizonModel.relation(lvl(85.0, 87.0), true, c))
    }

    @Test fun noTradeMeansNoRelation() {
        val c = buyCard().copy(action = Action.WAIT)
        assertEquals(LevelRelation.NO_TRADE_CONTEXT, HorizonModel.relation(lvl(104.0, 106.0), false, c))
    }
}
