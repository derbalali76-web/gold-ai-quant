package com.goldaiquant.app

/**
 * «وضعي» calculator: pure arithmetic, independent of every prediction engine and of the public ledger.
 *
 * Conventions (one place, used everywhere):
 *  - fee and slippage are percents (0.1 = 0.1%), each in [0, 5];
 *  - a buy pays the fee on top of the cash spent: coins = cash / (price × (1 + fee));
 *  - a sell receives the price minus the fee: cash = coins × price × (1 − fee);
 *  - slippage worsens MARKET orders only (buy at now × (1 + slip), sell at now × (1 − slip));
 *    a LIMIT order fills exactly at its price;
 *  - a limit on the wrong side of the current price (buy limit ≥ now, sell limit ≤ now) fills at once,
 *    so it is computed as a market order and flagged;
 *  - options are compared at ONE end price chosen by the user, marked to market (coins × end price + cash,
 *    no exit cost), against a baseline (hold for a holder, wait for cash);
 *  - a limit order depends on the path, not on the end price, so its result is always given twice:
 *    filled and not filled. No probability is attached to either (none is validated yet).
 */
object PositionCalc {

    enum class Err { BUY_PRICE, QTY, CASH, NOW, END, FEE, SLIP, SELL_QTY, SELL_LEVEL, REBUY_LEVEL, BUY_LEVEL, FIRST_PART }

    data class Costs(val feePct: Double, val slipPct: Double) {
        val fee get() = feePct / 100.0
        val slip get() = slipPct / 100.0
    }

    /** Coins received for [cash] at [price]; [market] adds slippage. */
    fun buyCoins(cash: Double, price: Double, c: Costs, market: Boolean): Double {
        val exec = if (market) price * (1 + c.slip) else price
        return cash / (exec * (1 + c.fee))
    }

    /** Cash received for [coins] at [price]; [market] adds slippage. */
    fun sellCash(coins: Double, price: Double, c: Costs, market: Boolean): Double {
        val exec = if (market) price * (1 - c.slip) else price
        return coins * exec * (1 - c.fee)
    }

    /** Price at which selling [coins] (market) gives back [money] after costs. */
    fun breakeven(money: Double, coins: Double, c: Costs): Double = money / (coins * (1 - c.slip) * (1 - c.fee))

    /** Breakeven of [money] when [cash] is already in hand next to [coins]. */
    private fun recover(money: Double, cash: Double, coins: Double, c: Costs): Double? =
        if (coins <= 1e-12) null else maxOf(0.0, breakeven(money - cash, coins, c))

    /** One outcome of an option: what you hold at the end, its value, and how it compares with the baseline. */
    data class Outcome(
        val coins: Double,
        val cash: Double,
        val value: Double,          // cash + coins × end price
        val vsBase: Double,         // value − baseline value
        val realized: Double?,      // realized profit/loss from any sale (null when nothing was sold)
        val avgCost: Double?,       // average cost of the coins held after the option (null when no coins)
        val breakeven: Double?,     // market sell price at which the coins plus the cash give back the ORIGINAL money
                                    // (holder: cost basis; cash: the amount). 0 = already covered; null = no coins
    )

    /** An option: [filled] is the result when its order executes; [notFilled] only for limit orders. */
    data class Option(val code: String, val filled: Outcome, val notFilled: Outcome? = null, val asMarket: Boolean = false)

    data class HoldIn(
        val buyPrice: Double, val qty: Double, val now: Double, val end: Double, val costs: Costs,
        val sellQty: Double, val sellLevel: Double, val rebuyLevel: Double,
    )

    data class HoldOut(
        val costBasis: Double, val marketValue: Double, val unrealized: Double, val unrealizedPct: Double,
        val breakeven: Double, val options: List<Option>,
    )

    data class CashIn(
        val cash: Double, val now: Double, val end: Double, val costs: Costs, val buyLevel: Double, val firstPart: Double,
    )

    data class CashOut(val options: List<Option>)

    private fun ok(x: Double) = x.isFinite() && x > 0

    fun validate(i: HoldIn): List<Err> = buildList {
        if (!ok(i.buyPrice)) add(Err.BUY_PRICE)
        if (!ok(i.qty)) add(Err.QTY)
        if (!ok(i.now)) add(Err.NOW)
        if (!ok(i.end)) add(Err.END)
        addAll(costErrors(i.costs))
        if (!ok(i.sellQty)) add(Err.SELL_QTY) else if (ok(i.qty) && i.sellQty > i.qty * (1 + 1e-12)) add(Err.SELL_QTY)
        if (!ok(i.sellLevel)) add(Err.SELL_LEVEL)
        if (!ok(i.rebuyLevel)) add(Err.REBUY_LEVEL)
    }

    fun validate(i: CashIn): List<Err> = buildList {
        if (!ok(i.cash)) add(Err.CASH)
        if (!ok(i.now)) add(Err.NOW)
        if (!ok(i.end)) add(Err.END)
        addAll(costErrors(i.costs))
        if (!ok(i.buyLevel)) add(Err.BUY_LEVEL)
        if (!ok(i.firstPart) || (ok(i.cash) && i.firstPart > i.cash * (1 + 1e-12))) add(Err.FIRST_PART)
    }

    private fun costErrors(c: Costs) = buildList {
        if (!c.feePct.isFinite() || c.feePct < 0 || c.feePct > 5) add(Err.FEE)
        if (!c.slipPct.isFinite() || c.slipPct < 0 || c.slipPct > 5) add(Err.SLIP)
    }

    /** Holder: hold / sell now / sell at a level / sell now and buy back lower. Null when the input is invalid. */
    fun hold(i: HoldIn): HoldOut? {
        if (validate(i).isNotEmpty()) return null
        val c = i.costs
        val cost = i.buyPrice * i.qty * (1 + c.fee)
        val unitCost = cost / i.qty
        val mv = i.qty * i.now
        val baseValue = i.qty * i.end
        val keep = i.qty - i.sellQty
        val keptCost = keep * unitCost

        fun out(coins: Double, cash: Double, realized: Double?, committed: Double): Outcome {
            val v = cash + coins * i.end
            return Outcome(coins, cash, v, v - baseValue, realized,
                if (coins > 1e-12) committed / coins else null, recover(cost, cash, coins, c))
        }

        val holdOpt = Option("HOLD", out(i.qty, 0.0, null, cost))

        val nowCash = sellCash(i.sellQty, i.now, c, market = true)
        val nowRealized = nowCash - i.sellQty * unitCost
        val sellNow = Option("SELL_NOW", out(keep, nowCash, nowRealized, keptCost))

        val limitMarket = i.sellLevel <= i.now
        val limCash = if (limitMarket) nowCash else sellCash(i.sellQty, i.sellLevel, c, market = false)
        val sellLimit = Option("SELL_LIMIT",
            filled = out(keep, limCash, limCash - i.sellQty * unitCost, keptCost),
            notFilled = if (limitMarket) null else holdOpt.filled,
            asMarket = limitMarket)

        val rebuyMarket = i.rebuyLevel >= i.now
        val back = buyCoins(nowCash, if (rebuyMarket) i.now else i.rebuyLevel, c, market = rebuyMarket)
        // the coins bought back cost the cash spent; the realized loss of the sale stays realized
        val rebuy = Option("SELL_REBUY",
            filled = out(keep + back, 0.0, nowRealized, keptCost + nowCash),
            notFilled = if (rebuyMarket) null else sellNow.filled,
            asMarket = rebuyMarket)

        return HoldOut(cost, mv, mv - cost, (mv - cost) / cost, breakeven(cost, i.qty, c),
            listOf(holdOpt, sellNow, sellLimit, rebuy))
    }

    /** Cash: wait / buy now / buy at a level / split in two payments. Null when the input is invalid. */
    fun cash(i: CashIn): CashOut? {
        if (validate(i).isNotEmpty()) return null
        val c = i.costs
        fun out(coins: Double, cash: Double, committed: Double): Outcome {
            val v = cash + coins * i.end
            return Outcome(coins, cash, v, v - i.cash, null,
                if (coins > 1e-12) committed / coins else null, recover(i.cash, cash, coins, c))
        }
        val wait = Option("WAIT", out(0.0, i.cash, 0.0))
        val nowCoins = buyCoins(i.cash, i.now, c, market = true)
        val buyNow = Option("BUY_NOW", out(nowCoins, 0.0, i.cash))

        val limMarket = i.buyLevel >= i.now
        val limCoins = if (limMarket) nowCoins else buyCoins(i.cash, i.buyLevel, c, market = false)
        val buyLimit = Option("BUY_LIMIT", out(limCoins, 0.0, i.cash),
            notFilled = if (limMarket) null else wait.filled, asMarket = limMarket)

        val first = buyCoins(i.firstPart, i.now, c, market = true)
        val rest = i.cash - i.firstPart
        val second = if (limMarket) buyCoins(rest, i.now, c, market = true) else buyCoins(rest, i.buyLevel, c, market = false)
        val split = Option("SPLIT", out(first + second, 0.0, i.cash),
            notFilled = if (limMarket) null else out(first, rest, i.firstPart), asMarket = limMarket)

        return CashOut(listOf(wait, buyNow, buyLimit, split))
    }

    /** Lenient number parsing for the input fields: Arabic-Indic digits and a comma decimal are accepted. */
    fun parse(s: String): Double? {
        val t = s.trim().map { ch ->
            when (ch) {
                in '٠'..'٩' -> '0' + (ch - '٠')
                in '۰'..'۹' -> '0' + (ch - '۰')
                ',', '٫' -> '.'
                else -> ch
            }
        }.joinToString("").replace("%", "").replace("$", "").trim()
        if (t.isEmpty() || t.count { it == '.' } > 1) return null
        return t.toDoubleOrNull()?.takeIf { it.isFinite() }
    }

    /** End-price choices around the current price (−10 %, −5 %, now, +5 %, +10 %). */
    fun endChoices(now: Double): List<Double> = listOf(0.90, 0.95, 1.0, 1.05, 1.10).map { now * it }
}
