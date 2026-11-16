package com.goldaiquant.app

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SourcesParseTest {
    private fun fixture(name: String) = javaClass.classLoader!!.getResource("fixtures/$name")!!.readText()

    private fun withSources(vararg s: Pair<String, String>): Decision {
        val o = JSONObject(fixture("wait_demo.json"))
        val a = JSONArray()
        s.forEach { (src, st) ->
            a.put(JSONObject().put("source", src).put("state", st).put("last_update_utc", "2026-11-16T07:00:00Z"))
        }
        a.put(JSONObject().put("source", "CALENDAR").put("state", "OK").put("last_update_utc", JSONObject.NULL))
        o.put("sources", a)
        return DecisionParser.parse(o.toString())
    }

    @Test fun olderFilesHaveNoSources() {
        val d = DecisionParser.parse(fixture("wait_demo.json"))
        assertTrue(d.sources.isEmpty())
        assertFalse(d.hasStaleSource)
    }

    @Test fun parsesStatesAndFlagsOldInputs() {
        val ok = withSources("PRICE" to "OK", "H4" to "OK")
        assertEquals(3, ok.sources.size)
        assertEquals("H4", ok.sources[1].source)
        assertEquals(java.time.Instant.parse("2026-11-16T07:00:00Z"), ok.sources[0].lastUpdate)
        assertNull(ok.sources[2].lastUpdate)
        assertFalse(ok.hasStaleSource)
        assertTrue(withSources("PRICE" to "OK", "H4" to "STALE").hasStaleSource)
        assertTrue(withSources("D1" to "DOWN").hasStaleSource)
        assertFalse(withSources("H1" to "CLOSED").hasStaleSource)
    }
}
