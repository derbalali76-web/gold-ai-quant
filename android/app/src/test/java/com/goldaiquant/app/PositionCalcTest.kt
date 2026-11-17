package com.goldaiquant.app

import com.goldaiquant.app.PositionCalc.CashIn
import com.goldaiquant.app.PositionCalc.Costs
import com.goldaiquant.app.PositionCalc.Err
import com.goldaiquant.app.PositionCalc.HoldIn
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Every expected value below is written out by hand from the conventions in Position.kt (not from the code). */
class PositionCalcTest {
    private val eps = 1e-9
    private val c = Costs(0.1, 0.05)                 // fee 0.1 %, slippage 0.05 %
    private val f = 0.001; private val s = 0.0005
    private fun hold(end: Double = 76.0, sellQty: Double = 10.0, sell: Double = 75.0, rebuy: Double = 69.0, costs: Costs = c) =
        HoldIn(buyPrice = 80.0, qty = 10.0, now = 72.0, end = end, costs = costs, sellQty = sellQty, sellLevel = sell, rebuyLevel = rebuy)
    private fun cash(end: Double = 65.0, level: Double = 69.0, first: Double = 500.0, amount: Double = 1000.0, costs: Costs = c) =
        CashIn(cash = amount, now = 72.0, end = end, costs = costs, buyLevel = level, firstPart = first)

    @Test fun holderSummary() {
        val o = PositionCalc.hold(hold())!!
        val cost = 80.0 * 10 * (1 + f)
        assertEquals(800.8, cost, eps)
        assertEquals(cost, o.costBasis, eps)
        assertEquals(720.0, o.marketValue, eps)
        assertEquals(720.0 - cost, o.unrealized, eps)
        assertEquals((720.0 - cost) / cost, o.unrealizedPct, eps)
        assertEquals(cost / (10 * (1 - s) * (1 - f)), o.breakeven, eps)
        assertEquals(80.2003, o.breakeven, 1e-4)
    }

    @Test fun sellNowRealizesTheLossAndMissesTheRise() {
        // price rises right after the sale: the seller is behind the holder by exactly the rise plus costs
        val o = PositionCalc.hold(hold(end = 80.0))!!
        val sell = o.options.first { it.code == "SELL_NOW" }.filled
        val got = 10 * 72.0 * (1 - s) * (1 - f)
        assertEquals(got, sell.cash, eps); assertEquals(0.0, sell.coins, eps)
        assertEquals(got - 800.8, sell.realized!!, eps)
        assertEquals(got - 800.0, sell.vsBase, eps)          // hold is worth 10 × 80
        assertTrue(sell.vsBase < 0)
        assertNull(sell.avgCost); assertNull(sell.breakeven)
    }

    @Test fun sellLimitFilledAndNotFilled() {
        val o = PositionCalc.hold(hold(end = 76.0))!!.options.first { it.code == "SELL_LIMIT" }
        assertFalse(o.asMarket)
        assertEquals(10 * 75.0 * (1 - f), o.filled.cash, eps)            // limit: no slippage
        assertEquals(749.25 - 760.0, o.filled.vsBase, eps)
        val nf = o.notFilled!!                                           // not filled = still holding
        assertEquals(10.0, nf.coins, eps); assertEquals(760.0, nf.value, eps); assertEquals(0.0, nf.vsBase, eps)
    }

    @Test fun sellAndBuyBackLower() {
        val o = PositionCalc.hold(hold(end = 76.0))!!.options.first { it.code == "SELL_REBUY" }
        val got = 10 * 72.0 * (1 - s) * (1 - f)
        val back = got / (69.0 * (1 + f))
        assertEquals(back, o.filled.coins, eps)
        assertEquals(0.0, o.filled.cash, eps)
        assertEquals(back * 76 - 760, o.filled.vsBase, eps)
        // more coins is not a realized profit: the realized loss of the sale is still there
        assertEquals(got - 800.8, o.filled.realized!!, eps)
        assertEquals(got / back, o.filled.avgCost!!, eps)                // = 69 × (1 + fee)
        assertEquals(69.0 * (1 + f), o.filled.avgCost!!, eps)
        assertEquals(800.8 / (back * (1 - s) * (1 - f)), o.filled.breakeven!!, eps)
        assertTrue(o.filled.breakeven!! < 80.2)                          // more coins → lower price to get the money back
        // the buy-back never happens and the price rises: out of the market, behind the holder
        val up = PositionCalc.hold(hold(end = 80.0))!!.options.first { it.code == "SELL_REBUY" }.notFilled!!
        assertEquals(0.0, up.coins, eps); assertEquals(got, up.cash, eps); assertEquals(got - 800.0, up.vsBase, eps)
    }

    @Test fun partialSale() {
        val o = PositionCalc.hold(hold(sellQty = 4.0, end = 72.0))!!
        val sell = o.options.first { it.code == "SELL_NOW" }.filled
        val got = 4 * 72.0 * (1 - s) * (1 - f)
        assertEquals(6.0, sell.coins, eps); assertEquals(got, sell.cash, eps)
        assertEquals(got - 4 * 80.08, sell.realized!!, eps)
        assertEquals(80.08, sell.avgCost!!, eps)                         // the coins kept keep their cost
        assertEquals((800.8 - got) / (6 * (1 - s) * (1 - f)), sell.breakeven!!, eps)
        val rb = o.options.first { it.code == "SELL_REBUY" }.filled
        assertEquals(6 + got / (69.0 * (1 + f)), rb.coins, eps)
        assertEquals((6 * 80.08 + got) / rb.coins, rb.avgCost!!, eps)
    }

    @Test fun limitsOnTheWrongSideAreMarketOrders() {
        val o = PositionCalc.hold(hold(sell = 70.0, rebuy = 73.0))!!
        val lim = o.options.first { it.code == "SELL_LIMIT" }
        assertTrue(lim.asMarket); assertNull(lim.notFilled)
        assertEquals(10 * 72.0 * (1 - s) * (1 - f), lim.filled.cash, eps)
        val rb = o.options.first { it.code == "SELL_REBUY" }
        assertTrue(rb.asMarket); assertNull(rb.notFilled)
        assertEquals(10 * 72.0 * (1 - s) * (1 - f) / (72.0 * (1 + s) * (1 + f)), rb.filled.coins, eps)
        assertTrue(rb.filled.coins < 10)                                 // a round trip only costs
        val cb = PositionCalc.cash(cash(level = 75.0))!!.options.first { it.code == "BUY_LIMIT" }
        assertTrue(cb.asMarket); assertNull(cb.notFilled)
    }

    @Test fun cashOptions() {
        val o = PositionCalc.cash(cash(end = 65.0))!!
        val wait = o.options.first { it.code == "WAIT" }.filled
        assertEquals(1000.0, wait.value, eps); assertEquals(0.0, wait.vsBase, eps); assertNull(wait.avgCost)
        val now = o.options.first { it.code == "BUY_NOW" }.filled
        val q = 1000 / (72.0 * (1 + s) * (1 + f))
        assertEquals(q, now.coins, eps); assertEquals(q * 65 - 1000, now.vsBase, eps)
        assertTrue(now.vsBase < 0)                                       // price fell after the buy
        assertEquals(1000 / (q * (1 - s) * (1 - f)), now.breakeven!!, eps)
        val lim = o.options.first { it.code == "BUY_LIMIT" }
        val ql = 1000 / (69.0 * (1 + f))
        assertEquals(ql, lim.filled.coins, eps)
        assertEquals(69.0 * (1 + f), lim.filled.avgCost!!, eps)
        assertTrue(lim.filled.vsBase < 0)                                // a cheaper buy can still lose
        assertEquals(1000.0, lim.notFilled!!.cash, eps); assertEquals(0.0, lim.notFilled!!.vsBase, eps)
    }

    @Test fun splitInTwoPayments() {
        val o = PositionCalc.cash(cash(end = 76.0))!!.options.first { it.code == "SPLIT" }
        val q1 = 500 / (72.0 * (1 + s) * (1 + f)); val q2 = 500 / (69.0 * (1 + f))
        assertEquals(q1 + q2, o.filled.coins, eps)
        assertEquals(1000 / (q1 + q2), o.filled.avgCost!!, eps)
        assertEquals((q1 + q2) * 76 - 1000, o.filled.vsBase, eps)
        val nf = o.notFilled!!                                           // only the first payment executed
        assertEquals(q1, nf.coins, eps); assertEquals(500.0, nf.cash, eps)
        assertEquals(q1 * 76 + 500 - 1000, nf.vsBase, eps)
        assertEquals(500 / (q1 * (1 - s) * (1 - f)), nf.breakeven!!, eps)
        // everything in the first payment = buy now; nothing left for the order
        val all = PositionCalc.cash(cash(first = 1000.0))!!
        assertEquals(all.options.first { it.code == "BUY_NOW" }.filled.coins, all.options.first { it.code == "SPLIT" }.filled.coins, eps)
    }

    @Test fun noOrderExecutedLeavesEverythingAsBefore() {
        val h = PositionCalc.hold(hold(end = 72.0))!!
        h.options.mapNotNull { it.notFilled }.forEach { assertTrue(it.vsBase <= 1e-9) }
        assertEquals(720.0, h.options.first { it.code == "SELL_LIMIT" }.notFilled!!.value, eps)
        val k = PositionCalc.cash(cash(end = 72.0))!!
        assertEquals(1000.0, k.options.first { it.code == "BUY_LIMIT" }.notFilled!!.value, eps)
    }

    @Test fun feesChangeEveryResult() {
        val free = PositionCalc.hold(hold(costs = Costs(0.0, 0.0), end = 72.0))!!
        assertEquals(800.0, free.costBasis, eps); assertEquals(80.0, free.breakeven, eps)
        assertEquals(720.0, free.options.first { it.code == "SELL_NOW" }.filled.cash, eps)
        assertEquals(0.0, free.options.first { it.code == "SELL_NOW" }.filled.vsBase, eps)
        val dear = PositionCalc.hold(hold(costs = Costs(1.0, 0.5), end = 72.0))!!
        assertEquals(808.0, dear.costBasis, eps)
        assertEquals(720.0 * 0.995 * 0.99, dear.options.first { it.code == "SELL_NOW" }.filled.cash, eps)
        assertTrue(dear.breakeven > free.breakeven)
        val k = PositionCalc.cash(cash(costs = Costs(0.0, 0.0)))!!
        assertEquals(1000 / 72.0, k.options.first { it.code == "BUY_NOW" }.filled.coins, eps)
    }

    @Test fun invalidInputsGiveErrorsNotNumbers() {
        assertEquals(listOf(Err.BUY_PRICE), PositionCalc.validate(hold().copy(buyPrice = 0.0)))
        assertTrue(Err.QTY in PositionCalc.validate(hold().copy(qty = -1.0)))
        assertTrue(Err.NOW in PositionCalc.validate(hold().copy(now = Double.NaN)))
        assertTrue(Err.FEE in PositionCalc.validate(hold(costs = Costs(-1.0, 0.0))))
        assertTrue(Err.SLIP in PositionCalc.validate(hold(costs = Costs(0.1, 6.0))))
        assertEquals(listOf(Err.SELL_QTY), PositionCalc.validate(hold(sellQty = 12.0)))   // more than held
        assertTrue(Err.SELL_QTY in PositionCalc.validate(hold(sellQty = 0.0)))
        assertNull(PositionCalc.hold(hold(sellQty = 12.0)))
        assertEquals(listOf(Err.FIRST_PART), PositionCalc.validate(cash(first = 1200.0)))   // not enough cash
        assertTrue(Err.CASH in PositionCalc.validate(cash(amount = 0.0)))
        assertTrue(Err.END in PositionCalc.validate(cash().copy(end = 0.0)))
        assertNull(PositionCalc.cash(cash(first = 1200.0)))
        assertTrue(PositionCalc.validate(hold()).isEmpty()); assertTrue(PositionCalc.validate(cash()).isEmpty())
    }

    @Test fun parsingAcceptsArabicDigitsAndCommas() {
        assertEquals(72.5, PositionCalc.parse("٧٢٫٥")!!, eps)
        assertEquals(72.5, PositionCalc.parse("72,5")!!, eps)
        assertEquals(0.1, PositionCalc.parse("0.1%")!!, eps)
        assertEquals(1000.0, PositionCalc.parse(" 1000$ ")!!, eps)
        assertNull(PositionCalc.parse("")); assertNull(PositionCalc.parse("1.2.3")); assertNull(PositionCalc.parse("abc"))
    }

    @Test fun endChoicesAreAroundNow() {
        assertEquals(listOf(64.8, 68.4, 72.0, 75.6, 79.2), PositionCalc.endChoices(72.0).map { Math.round(it * 10) / 10.0 })
    }
}
