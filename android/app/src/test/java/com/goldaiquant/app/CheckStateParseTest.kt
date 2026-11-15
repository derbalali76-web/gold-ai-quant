package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class CheckStateParseTest {
    private fun fixture(name: String) = javaClass.classLoader!!.getResource("fixtures/$name")!!.readText()

    @Test fun newsCheckCarriesState() {
        val body = fixture("wait_demo.json")
        val d = DecisionParser.parse(body)
        val news = d.outlooks.flatMap { it.checklist }.firstOrNull { it.code == "news" }
        assertNotNull(news)
        // demo has no calendar: unknown must stay unknown (never "no news")
        assertNull(news!!.ok)
        assertEquals("NOT_CONFIGURED", news.state)
    }
}
