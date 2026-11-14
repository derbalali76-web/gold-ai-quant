package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class TrustParseTest {
    @Test fun parsesLedgerStats() {
        val body = """{"schema":1,"chain_head":"abcdef0123456789ff","lines":5,"tracking_since":"2026-11-14T11:17:00Z",
          "days_tracked":3,"recommendations":{"completed":2,"wins":1,"win_rate":0.5,"avg_r":0.25,"baseline_avg_r":-0.1,
          "published":3,"open":1},"by_model":{"m1":{"completed":2,"wins":1,"avg_r":0.25}},
          "analysis":{"days":3,"scored":2,"correct":1,"accuracy":0.5,"baseline_accuracy":null},
          "recent":[{"recorded_at":"2026-11-15T10:17:00Z","horizon":"HOURS","side":"BUY","outcome":"TARGET","r":1.5},
                    {"recorded_at":"2026-11-14T10:17:00Z","horizon":"WEEK","side":"SELL","outcome":"NOT_FILLED","r":null}]}"""
        val t = TrustParser.parse(body)
        assertNotNull(t)
        t!!
        assertEquals(2, t.all.completed)
        assertEquals(0.25, t.all.avgR!!, 1e-9)
        assertEquals(-0.1, t.all.baselineAvgR!!, 1e-9)
        assertEquals(1, t.open)
        assertNull(t.baselineAccuracy)
        assertEquals(2, t.recent.size)
        assertNull(t.recent[1].r)
        assertEquals("2026-11-15", t.recent[0].date)
        assertEquals(1, t.byModel["m1"]!!.wins)
    }

    @Test fun emptyLedgerIsHonestZero() {
        val t = TrustParser.parse("""{"chain_head":"0000","recommendations":{"completed":0,"win_rate":null,"avg_r":null},"analysis":{}}""")!!
        assertEquals(0, t.all.completed)
        assertNull(t.all.winRate)
    }

    @Test fun perAssetRecords() {
        val body = """{"chain_head":"abc","recommendations":{"completed":1},"analysis":{},
          "assets":{"XAU":{"recommendations":{"completed":1},"analysis":{}},
                    "BTC":{"recommendations":{"completed":0},"analysis":{"scored":3,"accuracy":0.67}}}}"""
        val all = TrustParser.parseAll(body)
        assertEquals(setOf("XAU", "BTC"), all.keys)
        assertEquals(3, all["BTC"]!!.analysisScored)
        assertEquals("abc", all["BTC"]!!.head)
    }

    @Test fun scenarioBlocks() {
        val body = """{"chain_head":"abc","recommendations":{"completed":0},"analysis":{},
          "scenarios":{"experimental":true,"assets":{"XAU":{"HOLD_SELL_REBUY":{"all":{"scenarios":5,"triggered":2,
          "not_triggered":3,"wins":1,"losses":1,"avg_return_pct":0.01,"max_drawdown_pct":0.3,"beat_reference_share":0.2}}}}}}"""
        val t = TrustParser.parse(body)!!
        assertEquals(3, t.scenarios["HOLD_SELL_REBUY"]!!.notTriggered)
    }

    @Test fun garbageIsNull() {
        assertNull(TrustParser.parse("<html>rate limited</html>"))
        assertNull(TrustParser.parse(null))
        assertNull(TrustParser.parse("""{"a":1}"""))
    }
}
