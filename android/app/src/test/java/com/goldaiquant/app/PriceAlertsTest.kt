package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PriceAlertsTest {
    @Test fun directionFollowsCurrentPrice() {
        assertEquals("BELOW", PriceAlerts.make("SOL", 70.0, 71.3, "S1").dir)
        assertEquals("ABOVE", PriceAlerts.make("SOL", 71.36, 71.3, "R1").dir)
    }

    @Test fun roundTripAndToggle() {
        val a = PriceAlerts.make("BTC", 62405.12, 63000.0, "S1")
        val list = PriceAlerts.toggle(emptyList(), a)
        assertEquals(list, PriceAlerts.decode(PriceAlerts.encode(list)))
        assertTrue(PriceAlerts.isOn(list, "BTC", 62405.12))
        assertTrue(PriceAlerts.toggle(list, a).isEmpty())
        assertTrue(PriceAlerts.decode("garbage\nBTC|SIDEWAYS|1|x").isEmpty())
    }

    @Test fun reachedOnlyThroughTheLevel() {
        val below = PriceAlert("SOL", 70.0, "BELOW", "S1")
        assertFalse(PriceAlerts.reached(below, 70.5))
        assertTrue(PriceAlerts.reached(below, 69.9))
        val above = PriceAlert("SOL", 71.36, "ABOVE", "R1")
        assertFalse(PriceAlerts.reached(above, 71.0))
        assertTrue(PriceAlerts.reached(above, 71.4))
    }
}
