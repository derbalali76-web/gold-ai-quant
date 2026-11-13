package com.goldaiquant.app

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class DecisionParserTest {
    private fun fixture(name: String): String =
        javaClass.classLoader!!.getResourceAsStream("fixtures/$name")!!.bufferedReader().use { it.readText() }

    private fun expectFailure(raw: String) {
        try { DecisionParser.parse(raw); fail("expected ParseException") } catch (e: ParseException) { }
    }

    @Test fun parsesRealBackendWait() {
        val d = DecisionParser.parse(fixture("wait_demo.json"))
        assertEquals(Action.WAIT, d.action)
        assertTrue(d.isDemo)
        assertNull(d.displayableProbability)
    }

    @Test fun parsesUnavailable() {
        val d = DecisionParser.parse(fixture("unavailable_live.json"))
        assertEquals(Action.UNAVAILABLE, d.action)
        assertNull(d.quote)
    }

    @Test fun parsesTradeFixturesWithConsistentLevels() {
        for (name in listOf("buy_demo_stub.json", "sell_demo_stub.json")) {
            val d = DecisionParser.parse(fixture(name))
            assertTrue(d.action == Action.BUY || d.action == Action.SELL)
            assertTrue(d.entryMin!! <= d.entryMax!!)
            assertNull("DEMO never shows probability", d.displayableProbability)
        }
    }

    @Test fun rejectsInvertedBuyLevels() {
        val o = JSONObject(fixture("buy_demo_stub.json"))
        o.put("stop_loss", o.getDouble("entry_max") + 5.0)
        expectFailure(o.toString())
    }

    @Test fun rejectsDemoWithoutSyntheticLabel() {
        val o = JSONObject(fixture("wait_demo.json"))
        o.put("spot_or_proxy", "SPOT")
        expectFailure(o.toString())
    }

    @Test fun rejectsUnknownMajorVersionAndGarbage() {
        val o = JSONObject(fixture("wait_demo.json"))
        o.put("schema_version", "2.0.0")
        expectFailure(o.toString())
        expectFailure("<html>proxy error</html>")
        expectFailure("{}")
    }

    @Test fun probabilityHiddenWithoutCalibration() {
        val o = JSONObject(fixture("unavailable_live.json"))
        o.put("probability_target_before_stop", 0.95)
        o.put("calibration_sample_count", 12)
        val d = DecisionParser.parse(o.toString())
        assertNull(d.displayableProbability)
        o.put("calibration_sample_count", 500)
        assertEquals(0.95, DecisionParser.parse(o.toString()).displayableProbability!!, 1e-9)
    }

    @Test fun staleTradeRejected() {
        val o = JSONObject(fixture("buy_demo_stub.json"))
        o.getJSONObject("data_freshness").put("is_fresh", false)
        expectFailure(o.toString())
    }

    @Test fun liveQualifiedShowsThreeOutcomes() {
        val d = DecisionParser.parse(fixture("live_qualified_stub.json"))
        val o = d.displayableOutcomes!!
        assertEquals(1.0, o.first + o.second + o.third, 1e-3)
        assertEquals(4, d.horizonProbs.size)
        assertTrue(d.reasonShortAr!!.isNotBlank())
    }

    @Test fun rejectsProbabilitiesThatDoNotSumToOne() {
        val o = JSONObject(fixture("live_qualified_stub.json"))
        o.put("probability_neither", 0.5)
        expectFailure(o.toString())
    }

    @Test fun waitCarriesShortReasonAndAlternativeEntry() {
        val d = DecisionParser.parse(fixture("wait_demo.json"))
        assertTrue(d.reasonShortAr!!.isNotBlank())
        assertNull(d.displayableOutcomes)
    }

    @Test fun tradeRequiresCourtApproval() {
        val o = JSONObject(fixture("buy_demo_stub.json"))
        assertEquals(3, DecisionParser.parse(o.toString()).court.size)
        o.getJSONArray("court").getJSONObject(2).put("passed", false)
        expectFailure(o.toString())
        o.remove("court")
        expectFailure(o.toString())
    }

    @Test fun waitCarriesCourtAndBudget() {
        val d = DecisionParser.parse(fixture("wait_demo.json"))
        assertTrue(d.court.isNotEmpty() && d.court.any { !it.passed })
        assertTrue(d.budgetLimit != null && d.auditHash != null)
    }

    @Test fun trendAndLevelsParsedAndOrdered() {
        val d = DecisionParser.parse(fixture("wait_demo.json"))
        assertTrue(d.trend != null && d.trend!!.strength!! in 0..100)
        val lv = d.levels!!
        assertTrue(lv.supports.all { it.price < d.quote!! } && lv.resistances.all { it.price > d.quote!! })
        val sp = lv.supports.map { it.price }
        assertEquals(sp.sortedDescending(), sp)
        assertTrue(d.reevaluateAr.isNotEmpty())
    }

    @Test fun rejectsUnvalidatedNumericLevelStrength() {
        val o = JSONObject(fixture("wait_demo.json"))
        o.getJSONObject("levels").getJSONArray("supports").getJSONObject(0).put("strength", 88)
        expectFailure(o.toString())
    }

    @Test fun rejectsLevelOnWrongSide() {
        val o = JSONObject(fixture("wait_demo.json"))
        val s = o.getJSONObject("levels").getJSONArray("supports").getJSONObject(0)
        s.put("zone_high", o.getDouble("quote") + 5.0)
        expectFailure(o.toString())
    }
}
