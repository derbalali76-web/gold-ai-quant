package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TradeOppTest {
    private val pending = """{"engine":"te-live-h1-0.1","updated_at":"2026-11-18T17:05:00Z","price":64200.5,
      "active":[{"seq":3,"t":"2026-11-18T16:00:00Z","limit":63980.0,"stop":62030.0,"target":66905.0,
        "entry_until":"2026-11-19T04:00:00Z","hold_bars":30,"status":"PENDING","recorded_at":"2026-11-18T16:20:00Z"}],
      "last_closed":{"seq":1,"status":"STOP","limit":70000.0,"entry":70000.0,"exit":67900.0,"net":-0.0321,"exit_time":"2026-11-10T08:15:00Z"},
      "record":{"orders":2,"not_filled":0,"closed":1,"wins":0,"losses":1,"mean_net_pct":-3.21}}"""

    @Test fun parsesActiveOrderAndRecord() {
        val s = TradeOpp.parse(pending)!!
        assertTrue(s.hasTrade)
        assertEquals(63980.0, s.active!!.limit, 0.0)
        assertEquals("PENDING", s.active!!.status)
        assertEquals("STOP", s.lastClosed!!.status)
        assertEquals(1, s.record.losses)
        assertEquals(-3.21, s.record.meanNetPct!!, 1e-9)
        assertEquals(4.57, TradeOpp.pctFrom(63980.0, 66905.0), 0.01)
        assertEquals(-3.05, TradeOpp.pctFrom(63980.0, 62030.0), 0.01)
    }

    @Test fun emptyStateAndBadInputs() {
        val s = TradeOpp.parse("""{"engine":"te-live-h1-0.1","updated_at":"x","active":[],"record":{"orders":0}}""")!!
        assertTrue(!s.hasTrade)
        assertNull(s.record.meanNetPct)
        assertNull(TradeOpp.parse("""{"engine":"other"}"""))
        assertNull(TradeOpp.parse("not json"))
        // levels in the wrong order are never shown
        val bad = TradeOpp.parse("""{"engine":"te-live-h1-0.1","active":[{"limit":1,"stop":2,"target":3}]}""")!!
        assertNull(bad.active)
    }
}
