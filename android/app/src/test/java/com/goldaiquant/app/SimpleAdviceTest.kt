package com.goldaiquant.app

import com.goldaiquant.app.SimpleAdvice.Kind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class SimpleAdviceTest {
    private val sup = listOf(100.0, 95.0)
    private val res = listOf(120.0, 130.0)

    @Test fun cashRisingNotHighBuysNowTargetResistance() {
        val i = SimpleAdvice.decide("UP", 105.0, sup, res, hold = false)
        assertEquals(Kind.BUY_NOW, i.kind); assertEquals(120.0, i.sellAt!!, 1e-9); assertEquals(95.0, i.invalid!!, 1e-9)
    }

    @Test fun cashRisingHighWaitsForDipAtSupport() {
        val i = SimpleAdvice.decide("UP", 118.0, sup, res, hold = false)
        assertEquals(Kind.WAIT_DIP, i.kind); assertEquals(100.0, i.buyAt!!, 1e-9)
    }

    @Test fun cashFallingWaits() = assertEquals(Kind.WAIT, SimpleAdvice.decide("DOWN", 110.0, sup, res, false).kind)

    @Test fun holderRisingKeepsAndSellsAbove() {
        val i = SimpleAdvice.decide("UP", 105.0, sup, res, hold = true)
        assertEquals(Kind.HOLD_SELL_ABOVE, i.kind); assertEquals(120.0, i.sellAt!!, 1e-9)
    }

    @Test fun holderRisingHighSellsThenRebuysAtSupport() {
        val i = SimpleAdvice.decide("UP", 118.0, sup, res, hold = true)
        assertEquals(Kind.SELL_REBUY, i.kind); assertEquals(100.0, i.buyAt!!, 1e-9)
    }

    @Test fun holderFallingSellsThenRebuys() = assertEquals(Kind.SELL_REBUY, SimpleAdvice.decide("DOWN", 116.0, sup, res, true).kind)

    // owner rule 2026-11-24: gold gap of at least 15 USD before a sell-and-rebuy is shown
    @Test fun goldGapBelowFifteenHolds() {
        val i = SimpleAdvice.decide("DOWN", 112.0, sup, res, true, "XAU")
        assertEquals(Kind.HOLD_SELL_ABOVE, i.kind); assertEquals(120.0, i.sellAt!!, 1e-9)
    }

    @Test fun goldGapOfFiveDollarsHoldsLikeTheSeenCase() =
        assertEquals(Kind.HOLD_SELL_ABOVE, SimpleAdvice.decide("DOWN", 105.0, sup, res, true, "XAU").kind)

    // digital assets: gap of at least 0.65 % of the price
    @Test fun cryptoGapBelowPointSixFivePercentHolds() {
        val sup2 = listOf(60000.0); val res2 = listOf(61000.0)
        assertEquals(Kind.HOLD_SELL_ABOVE, SimpleAdvice.decide("DOWN", 60300.0, sup2, res2, true, "BTC").kind)   // gap 0.50 %, pos 0.30
    }

    @Test fun cryptoGapAtLeastPointSixFivePercentSellsThenRebuys() {
        val sup2 = listOf(60000.0); val res2 = listOf(61000.0)
        assertEquals(Kind.SELL_REBUY, SimpleAdvice.decide("DOWN", 60500.0, sup2, res2, true, "BTC").kind)   // gap 0.83 %, pos 0.50
    }

    @Test fun holderFallingAtSupportDoesNotSellAtTheBottom() =
        assertEquals(Kind.HOLD_SELL_ABOVE, SimpleAdvice.decide("DOWN", 101.0, sup, res, true).kind)

    @Test fun cashNeverSells() {
        for (t in listOf("UP", "DOWN", "SIDEWAYS", null)) for (p in listOf(99.0, 101.0, 110.0, 119.0, 125.0)) {
            val k = SimpleAdvice.decide(t, p, sup, res, false).kind
            assertNotEquals(Kind.SELL_REBUY, k); assertNotEquals(Kind.HOLD_SELL_ABOVE, k)
        }
    }

    @Test fun missingDataGivesNone() {
        assertEquals(Kind.NONE, SimpleAdvice.decide("UP", null, sup, res, false).kind)
        assertEquals(Kind.NONE, SimpleAdvice.decide("UP", 110.0, emptyList(), res, false).kind)
    }

    // owner rule 2026-11-24: tested likely side contradicting the idea withdraws the idea
    @Test fun testedUpWithdrawsSellRebuy() {
        val i = SimpleAdvice.decide("DOWN", 116.0, sup, res, true)
        assertEquals(Kind.SELL_REBUY, i.kind)
        assertEquals(Kind.CONFLICT, SimpleAdvice.resolve(i, true).kind)
        assertEquals(Kind.SELL_REBUY, SimpleAdvice.resolve(i, false).kind)
        assertEquals(Kind.SELL_REBUY, SimpleAdvice.resolve(i, null).kind)
    }

    @Test fun testedDownWithdrawsBuyNow() {
        val i = SimpleAdvice.decide("UP", 105.0, sup, res, false)
        assertEquals(Kind.BUY_NOW, i.kind)
        assertEquals(Kind.CONFLICT, SimpleAdvice.resolve(i, false).kind)
        assertEquals(Kind.BUY_NOW, SimpleAdvice.resolve(i, true).kind)
    }
}
