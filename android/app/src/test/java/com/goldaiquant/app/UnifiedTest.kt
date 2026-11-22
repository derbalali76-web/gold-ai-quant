package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UnifiedTest {
    private fun fixture(name: String) = javaClass.classLoader!!.getResource("ledger/$name")!!.readText()

    private fun one(holder: String, cash: String, radar: String) = """{"schema":"decision-state-2","updated_at":"2026-11-22T12:00:00Z",
      "assets":{"BTC":{"asset":"BTC","price":{"value":100.0,"at":"2026-11-22T11:30:00Z"},"gates":{"ok":true,"reasons":[]},
      "view":{"holder":$holder,"cash":$cash},"radar":$radar}}}"""

    private val wait = """{"verdict":"WAIT","signal_id":"s1","plan":null,"why":["not_yet_qualified"]}"""
    private val sell = """{"verdict":"SELL_THEN_REBUY","signal_id":"s1","why":[],
      "plan":{"sell":100.0,"rebuy_at":95.0,"invalidate_above":102.0,"duration_h":60,"adaptive":true}}"""
    private val buy = """{"verdict":"BUY_LIMIT","signal_id":"s1","why":[],
      "plan":{"entry":95.0,"target":null,"invalidate_below":93.0,"duration_h":150,"adaptive":true}}"""
    private val qItem = """[{"id":"s1","source":"advice-0.1.0","state":"QUALIFIED","holder":"SELL_OWNED","cash":"WAIT","level":95.0}]"""
    private val fItem = """[{"id":"s1","source":"advice-0.1.0","state":"FORMING","holder":"SELL_OWNED","cash":"WAIT","level":95.0}]"""

    @Test fun realLedgerSampleParsesAndShowsWaitEverywhere() {
        val u = Unified.parse(fixture("decision_state_sample.json"))!!
        assertEquals(setOf("XAU", "BTC", "ETH", "SOL", "PAXG"), u.assets.keys)
        u.assets.values.forEach { a ->
            assertEquals(Verdict.WAIT, a.holder.verdict); assertEquals(Verdict.WAIT, a.cash.verdict)
            assertTrue(a.holder.why.isNotEmpty() && a.cash.why.isNotEmpty())
            assertTrue(a.qualified.isEmpty())
        }
        assertEquals(listOf("price_only_asset"), u.assets["PAXG"]!!.holder.why)
        assertEquals(1, u.assets["BTC"]!!.forming.size)
    }

    @Test fun qualifiedPreemptiveSellForHolder() {
        val a = Unified.parse(one(sell, wait, qItem))!!.assets["BTC"]!!
        assertEquals(Verdict.SELL_THEN_REBUY, a.holder.verdict)
        assertEquals(95.0, a.holder.plan!!.rebuyAt!!, 0.0)
        assertEquals(102.0, a.holder.plan!!.invalidateAbove!!, 0.0)
        assertEquals(60, a.holder.plan!!.durationH)
        assertEquals(Verdict.WAIT, a.cash.verdict)
        assertEquals(1, a.qualified.size)
    }

    @Test fun qualifiedLimitBuyForCashWithDurationOver24h() {
        val a = Unified.parse(one(wait, buy, qItem))!!.assets["BTC"]!!
        assertEquals(Verdict.BUY_LIMIT, a.cash.verdict)
        assertEquals(150, a.cash.plan!!.durationH)
        assertEquals(Verdict.WAIT, a.holder.verdict)
    }

    @Test fun cashUserIsNeverToldToSell() {
        val a = Unified.parse(one(wait, sell, qItem))!!.assets["BTC"]!!
        assertEquals(Verdict.WAIT, a.cash.verdict)
        assertTrue(a.qualified.isEmpty())       // the orphan QUALIFIED item is demoted too
    }

    @Test fun orderWithoutQualifiedRadarItemIsNotShown() {
        val a = Unified.parse(one(sell, wait, fItem))!!.assets["BTC"]!!
        assertEquals(Verdict.WAIT, a.holder.verdict)
        assertEquals(listOf("state_inconsistent"), a.holder.why)
        val b = Unified.parse(one(wait, wait, qItem))!!.assets["BTC"]!!
        assertTrue(b.qualified.isEmpty())        // «no opportunity» never sits beside a QUALIFIED item
    }

    @Test fun incompletePlanDegradesToWait() {
        val bad = """{"verdict":"SELL_THEN_REBUY","signal_id":"s1","plan":{"sell":100.0,"rebuy_at":105.0,"invalidate_above":102.0}}"""
        assertEquals(Verdict.WAIT, Unified.parse(one(bad, wait, qItem))!!.assets["BTC"]!!.holder.verdict)
    }

    @Test fun wrongSchemaOrGarbage() {
        assertNull(Unified.parse("""{"schema":"decision-state-1","assets":{}}"""))
        assertNull(Unified.parse("not json"))
        assertNull(Unified.parse(null))
    }
}
