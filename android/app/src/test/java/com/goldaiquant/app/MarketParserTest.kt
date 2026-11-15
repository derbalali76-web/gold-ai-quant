package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class MarketParserTest {
    @Test fun candles() {
        val c = MarketParser.candles("""{"tf":"H1","t":[1,2,3],"o":[1,2,3],"h":[2,3,4],"l":[0.5,1,2],"c":[1.5,2.5,3.5]}""")!!
        assertEquals(3, c.size)
        assertNull(MarketParser.candles("""{"t":[1,2],"o":[1],"h":[2,3],"l":[0,1],"c":[1,2]}"""))  // ragged -> rejected
        assertNull(MarketParser.candles("not json"))
    }

    @Test fun calendar() {
        val k = MarketParser.calendar("""{"state":"CONNECTED","updated_at":"2026-11-15T06:15:00+00:00",
            "events":[{"time_utc":"2026-11-18T13:30:00+00:00","name":"US CPI","importance":3}]}""")!!
        assertEquals("CONNECTED", k.state)
        assertNotNull(k.updatedAt)
        assertEquals("US CPI", k.events.single().name)
    }

    @Test fun ticker() {
        assertEquals(91234.5, MarketParser.tickerPrice("""{"symbol":"BTCUSDT","price":"91234.50"}""")!!, 1e-9)
        assertNull(MarketParser.tickerPrice("""{"code":-1121}"""))
    }
}
