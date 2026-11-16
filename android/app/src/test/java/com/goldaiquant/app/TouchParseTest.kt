package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TouchParseTest {
    @Test fun parsesHorizonsAndStatuses() {
        val body = """{"asset":"XAU","available":true,"price":3862.97,"horizons":{
            "24":{"results":[{"status":"OK","price":3884.65,"side":1,"d":2.1,"probability":0.41,"usual":0.34},
                             {"status":"OUT_OF_RANGE","price":4500.0,"side":1,"d":60.0}],"weak":false},
            "4":{"results":[],"weak":true}}}"""
        val t = MarketParser.touch(body)!!
        assertTrue(t.available)
        assertEquals(3862.97, t.price!!, 1e-9)
        val h = t.horizons["24"]!!
        assertEquals(0.41, h.results[0].probability!!, 1e-9)
        assertEquals("OUT_OF_RANGE", h.results[1].status)
        assertNull(h.results[1].probability)
        assertTrue(t.horizons["4"]!!.weak)
    }

    @Test fun rejectsImpossibleProbabilitiesAndBadJson() {
        val t = MarketParser.touch("""{"asset":"BTC","available":true,"horizons":{"24":{"results":[{"status":"OK","price":1,"probability":1.7}]}}}""")!!
        assertTrue(t.horizons["24"]!!.results.isEmpty())
        assertNull(MarketParser.touch("<html>"))
        assertFalse(MarketParser.touch("""{"asset":"SOL","available":false,"horizons":{}}""")!!.available)
    }
}
