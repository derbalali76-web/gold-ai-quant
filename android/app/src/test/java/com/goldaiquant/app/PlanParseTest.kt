package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PlanParseTest {
    private fun load(name: String): Decision = DecisionParser.parse(
        javaClass.classLoader!!.getResource("fixtures/$name")!!.readText())

    @Test fun liveValidatedTradeIsARecommendationWithFullPlan() {
        val c = HorizonModel.card(load("live_qualified_stub.json"), "HOURS")
        val p = c.plan!!
        assertEquals("BUY_NOW", p.setup)
        assertTrue(p.recommendation)
        assertNotNull(p.stop); assertNotNull(p.target); assertNotNull(p.entryLow)
    }

    @Test fun demoTradeIsNeverARecommendation() {
        val p = HorizonModel.card(load("buy_demo_stub.json"), "HOURS").plan!!
        assertEquals("BUY_NOW", p.setup)
        assertFalse(p.recommendation)
    }

    @Test fun watchLevelHasNoStopOrTarget() {
        val p = HorizonModel.card(load("wait_demo.json"), "HOURS").plan!!
        assertTrue(p.setup == "WAIT_TO_BUY" || p.setup == "WAIT_TO_SELL" || p.setup == "WAIT")
        assertFalse(p.recommendation)
        assertNull(p.stop); assertNull(p.target)
    }

    @Test fun unavailableStaysUnavailable() {
        val p = HorizonModel.card(load("unavailable_live.json"), "HOURS").plan
        assertTrue(p == null || p.setup == "UNAVAILABLE") // no outlooks at all when the data are unusable
    }

    @Test fun dailyBriefIsParsedAsScenariosOnly() {
        listOf("wait_demo.json", "buy_demo_stub.json", "live_qualified_stub.json").forEach { f ->
            val b = load(f).brief ?: return@forEach
            assertTrue(b.scenarios.isNotEmpty())
            b.scenarios.forEach { assertTrue(it.kind == "BULL" || it.kind == "BEAR") }
        }
    }

    @Test fun briefEvents() {
        val body = javaClass.classLoader!!.getResource("fixtures/wait_demo.json")!!.readText()
        val o = org.json.JSONObject(body)
        val b = o.optJSONObject("daily_brief") ?: return
        b.put("events", org.json.JSONArray().put(org.json.JSONObject().put("kind", "BULL").put("level", 2010.5)
            .put("level_name", "R1").put("target", 2020.0).put("target_name", "R2").put("hour_utc", "2026-11-16T09:00:00Z")))
        val d = DecisionParser.parse(o.toString())
        val e = d.brief!!.events.single()
        org.junit.Assert.assertEquals("R1", e.levelName)
        org.junit.Assert.assertEquals(2020.0, e.target!!, 1e-9)
    }
}
