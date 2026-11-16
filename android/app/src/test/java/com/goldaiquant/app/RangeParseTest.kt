package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

class RangeParseTest {
    @Test fun parsesQualifiedHorizonsAndEvent() {
        val r = MarketParser.range("""{"asset":"SOL","available":true,"display":"4h","horizons":{
          "4h":{"low":70.1,"high":73.9,"close_at_issue":72.0,"issued_at":"2026-11-16T18:00:00+00:00",
                "event":{"name":"FOMC rate decision","time_utc":"2026-11-16T19:00:00+00:00"}}}}""")!!
        assertEquals("4h", r.display)
        assertEquals("FOMC rate decision", r.horizons["4h"]!!.eventName)
    }

    @Test fun dropsBrokenIntervalsAndUnknownDisplay() {
        val r = MarketParser.range("""{"asset":"XAU","available":true,"display":"24h","horizons":{
          "24h":{"low":3900,"high":3800,"close_at_issue":3850,"issued_at":"x","event":null}}}""")!!
        assertFalse(r.available)
        assertNull(r.display)
    }

    @Test fun rangeTracksFromLedgerStats() {
        val t = Record.rangeTracks("""{"ranges":{"BTC":{"24h":{"recorded":5,"settled":3,"inside":2,"last":null}}}}""")
        assertEquals(RangeTrack(5, 3, 2), t["BTC"]!!["24h"])
    }
}
