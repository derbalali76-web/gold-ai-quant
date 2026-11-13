package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TrackParserTest {
    @Test fun parsesResolvedSignalsNewestFirstAndSkipsBadRows() {
        val body = """{"horizons":{},"recent":[
          {"bar":"2026-10-01T00:00:00+00:00","horizon":"WEEK","tilt":1,"close":3800.5,"exit_close":3850.0,"hit":true},
          {"bar":"2026-10-20T00:00:00+00:00","horizon":"MONTH","tilt":-1,"close":3900,"exit_close":3950,"hit":false},
          {"bar":"2026-10-21T00:00:00+00:00","horizon":"WEEK","tilt":0,"close":1,"exit_close":1,"hit":true},
          {"bar":"2026-10-22T00:00:00+00:00","horizon":"WEEK","tilt":1,"close":1}
        ]}"""
        val r = TrackParser.parse(body)
        assertEquals(2, r.size)
        assertEquals("2026-10-20", r[0].bar)
        assertEquals(false, r[0].hit)
        assertEquals("WEEK", r[1].horizon)
    }

    @Test fun emptyOrInvalidGivesNothing() {
        assertTrue(TrackParser.parse("""{"status":"EMPTY"}""").isEmpty())
        assertTrue(TrackParser.parse("not json").isEmpty())
    }
}
