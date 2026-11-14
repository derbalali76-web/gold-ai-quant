package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class DataHealthParseTest {
    private fun fixture(name: String) = javaClass.classLoader!!.getResource("fixtures/$name")!!.readText()

    @Test fun fixtureHasHealth() {
        val d = DecisionParser.parse(fixture("wait_demo.json"))
        val h = d.dataHealth!!
        assert(h.status in setOf("OK", "WARN"))
        assert(h.checks.any { it.code == "flat" })
    }

    @Test fun missingHealthIsNull() {
        val body = fixture("wait_demo.json").replace("\"data_health\"", "\"data_health_x\"")
        assertNull(DecisionParser.parse(body).dataHealth)
    }
}
