package com.goldaiquant.app

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ScalpActivityParseTest {
    @Test fun parsesActivity() {
        val a = DecisionParser.parseActivity(JSONObject(
            """{"probability":0.82,"usual":0.49,"level":"HIGH","target_pct":0.65,"hours":4.0,"skill":0.25,"holdout_skill":0.15}"""))!!
        assertEquals(0.82, a.probability, 1e-9)
        assertEquals("HIGH", a.level)
        assertEquals(0.15, a.holdoutSkill!!, 1e-9)
    }

    @Test fun rejectsBrokenProbability() {
        assertNull(DecisionParser.parseActivity(JSONObject("""{"probability":1.7,"usual":0.5}""")))
        assertNull(DecisionParser.parseActivity(JSONObject("""{"usual":0.5}""")))
    }

    @Test fun fixtureWithoutActivityIsNull() {
        val body = javaClass.classLoader!!.getResource("fixtures/wait_demo.json")!!.readText()
        assertNull(DecisionParser.parse(body).scalpActivity)
    }
}
