package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class JournalTest {
    private val c = Journal.Costs(0.15, 2.0)

    @Test fun cryptoSaleNetsTheOwnersCost() {
        // 1 000 $ of SOL at 70, sold at 70.455 (+0.65 %): gain 6.50 $, cost 1.50 $ -> 5.00 $
        val t = Journal.Trade(1, "SOL", 1000.0, 70.0, 0L, 70.455, 1L)
        assertEquals(5.0, Journal.net(t, t.sellPrice!!, c), 1e-9)
        assertEquals(70.455, Journal.target(t), 1e-9)
    }

    @Test fun goldUsesTheFixedCost() {
        val t = Journal.Trade(2, "XAU", 3600.0, 3600.0, 0L)   // 1 ounce
        assertEquals(13.0, Journal.net(t, 3615.0, c), 1e-9)
        assertEquals(3615.0, Journal.target(t), 1e-9)
    }

    @Test fun summaryCountsOpenStuckAndUnknownPrices() {
        val day = 86_400_000L
        val now = 100 * day
        val ts = listOf(
            Journal.Trade(1, "SOL", 1000.0, 70.0, now - 2 * day, 70.455, now - day),
            Journal.Trade(2, "BTC", 500.0, 100.0, now - 40 * day),
            Journal.Trade(3, "SOL", 200.0, 80.0, now - day))
        val s = Journal.summary(ts, c, { a -> if (a == "SOL") 70.0 else 90.0 }, now)
        assertEquals(1, s.closed); assertEquals(1, s.wins); assertEquals(5.0, s.realizedUsd, 1e-9)
        assertEquals(2, s.open); assertEquals(700.0, s.lockedUsd, 1e-9); assertEquals(1, s.stuck)
        // BTC: 5 coins × −10 − 0.75 = −50.75 ; SOL: 2.5 × −10 − 0.30 = −25.30
        assertEquals(-76.05, s.unrealizedUsd!!, 1e-9)
        assertNull(Journal.summary(ts, c, { null }, now).unrealizedUsd)
    }
}
