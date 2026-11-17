package com.goldaiquant.app.ui

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.goldaiquant.app.PositionCalc
import com.goldaiquant.app.PositionCalc.Err
import com.goldaiquant.app.R
import java.util.Locale

// ---------------------------------------------------------------- «وضعي» calculator (arithmetic only, never a recommendation)

private fun f2(x: Double) = String.format(Locale.US, "%.2f", x)
private fun price(x: Double) = ltr(if (x < 1) String.format(Locale.US, "%.4f", x) else f2(x))
private fun money(x: Double) = ltr(f2(x) + "$")
private fun signed(x: Double) = ltr((if (x > 0.005) "+" else if (x < -0.005) "−" else "") + f2(kotlin.math.abs(x)) + "$")
private fun coins(x: Double): String =
    ltr(String.format(Locale.US, "%.4f", x).trimEnd('0').trimEnd('.').ifEmpty { "0" })
/** A number shown in an input field (plain, no isolation marks so it stays editable). */
private fun input(x: Double): String = String.format(Locale.US, if (x < 1) "%.4f" else "%.2f", x).removeSuffix(".00")

@Composable
private fun rememberField(ctx: Context, key: String, def: String): MutableState<String> {
    val prefs = remember { ctx.getSharedPreferences("position_calc", Context.MODE_PRIVATE) }
    return remember(key) { mutableStateOf(prefs.getString(key, null) ?: def) }
}

private fun save(ctx: Context, key: String, v: String) =
    ctx.getSharedPreferences("position_calc", Context.MODE_PRIVATE).edit().putString(key, v).apply()

@Composable
private fun NumField(label: String, state: MutableState<String>, bad: Boolean, modifier: Modifier,
                     hint: String = "", onEdit: (String) -> Unit = {}) {
    Column(modifier.background(Color(0xFF17151B), RoundedCornerShape(9.dp))
        .border(1.dp, if (bad) SellRed else CardEdge, RoundedCornerShape(9.dp)).padding(horizontal = 7.dp, vertical = 5.dp)) {
        Text(label, color = TextDim, fontSize = 10.sp, maxLines = 1)
        Box {
            if (state.value.isEmpty() && hint.isNotEmpty()) Text(hint, color = Grey, fontSize = 15.sp)
            BasicTextField(value = state.value, onValueChange = { v ->
                val t = v.filter { it.isDigit() || it in ".,\u066B" }.take(14); state.value = t; onEdit(t)
            }, singleLine = true, cursorBrush = SolidColor(Gold),
                textStyle = TextStyle(color = if (bad) SellRed else TextMain, fontSize = 15.sp, fontWeight = FontWeight.Bold,
                    textAlign = TextAlign.Start),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun Seg(text: String, on: Boolean, modifier: Modifier, onClick: () -> Unit) = Text(text,
    color = if (on) Color.Black else TextDim, fontSize = 13.sp, fontWeight = if (on) FontWeight.Bold else FontWeight.Normal,
    textAlign = TextAlign.Center, maxLines = 1,
    modifier = modifier.background(if (on) Gold else Color.Transparent, RoundedCornerShape(9.dp))
        .clickable(role = Role.Tab, onClick = onClick).padding(vertical = 7.dp))

@Composable
private fun KvLine(k: String, v: String, color: Color = TextMain) = Row(Modifier.fillMaxWidth()) {
    Text(k, color = TextDim, fontSize = 12.sp, modifier = Modifier.weight(1f)); Text(v, color = color, fontSize = 12.sp)
}

private fun moneyColor(x: Double) = when { x > 0.005 -> BuyGreen; x < -0.005 -> SellRed; else -> TextDim }

/**
 * The calculator sheet. [live] is the current price if known; [support]/[resistance] only pre-fill the order
 * fields (the user edits them). Nothing here is sent anywhere: inputs are kept in this phone's preferences.
 */
@Composable
internal fun PositionDialog(asset: String, assetName: String, live: Double?, support: Double?, resistance: Double?,
                            startHold: Boolean, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val k = { name: String -> "$asset.$name" }
    var hold by remember {
        mutableStateOf(ctx.getSharedPreferences("position_calc", Context.MODE_PRIVATE).getString(k("mode"), null)
            ?.let { it == "HOLD" } ?: startHold)
    }
    val nowState = remember { mutableStateOf(live?.let(::input) ?: "") }
    var manual by remember { mutableStateOf(live == null) }
    LaunchedEffect(live) { if (!manual && live != null) nowState.value = input(live) }
    val now = PositionCalc.parse(nowState.value) ?: 0.0
    val ref = live ?: now
    val sup = support?.takeIf { ref > 0 && it < ref } ?: ref * 0.96
    val res = resistance?.takeIf { ref > 0 && it > ref } ?: ref * 1.04

    val buy = rememberField(ctx, k("buy"), if (ref > 0) input(ref) else "")
    val qty = rememberField(ctx, k("qty"), "1")
    val fee = rememberField(ctx, k("fee"), "0.1")
    val slip = rememberField(ctx, k("slip"), "0.05")
    val sellQty = rememberField(ctx, k("sellQty"), "")
    val sellLv = rememberField(ctx, k("sellLv"), if (ref > 0) input(res) else "")
    val rebuyLv = rememberField(ctx, k("rebuyLv"), if (ref > 0) input(sup) else "")
    val cashAmt = rememberField(ctx, k("cash"), "1000")
    val buyLv = rememberField(ctx, k("buyLv"), if (ref > 0) input(sup) else "")
    val first = rememberField(ctx, k("first"), "")
    val end = remember { mutableStateOf(if (ref > 0) input(ref) else "") }
    val keep = { key: String -> { v: String -> save(ctx, k(key), v) } }

    val n = { st: MutableState<String> -> PositionCalc.parse(st.value) ?: Double.NaN }
    val costs = PositionCalc.Costs(n(fee), n(slip))
    val qtyV = n(qty); val cashV = n(cashAmt)
    val hIn = PositionCalc.HoldIn(n(buy), qtyV, now.takeIf { it > 0 } ?: Double.NaN, n(end), costs,
        sellQty.value.takeIf { it.isNotBlank() }?.let { n(sellQty) } ?: qtyV, n(sellLv), n(rebuyLv))
    val cIn = PositionCalc.CashIn(cashV, now.takeIf { it > 0 } ?: Double.NaN, n(end), costs, n(buyLv),
        first.value.takeIf { it.isNotBlank() }?.let { n(first) } ?: (cashV / 2))
    val errs = if (hold) PositionCalc.validate(hIn) else PositionCalc.validate(cIn)

    DialogFrame(stringResource(R.string.pc_title, assetName), onClose) {
        Text(stringResource(R.string.pc_sub), color = TextDim, fontSize = 12.sp)
        Row(Modifier.fillMaxWidth().border(1.dp, CardEdge, RoundedCornerShape(10.dp)).padding(2.dp)) {
            Seg(stringResource(R.string.pos_hold), hold, Modifier.weight(1f)) { hold = true; save(ctx, k("mode"), "HOLD") }
            Seg(stringResource(R.string.pos_cash), !hold, Modifier.weight(1f)) { hold = false; save(ctx, k("mode"), "CASH") }
        }
        if (live == null) Text(stringResource(R.string.pc_no_live), color = WaitGold, fontSize = 11.sp)
        else if (manual) Row(verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.pc_manual), color = WaitGold, fontSize = 11.sp, modifier = Modifier.weight(1f))
            Text(stringResource(R.string.pc_use_live), color = Gold, fontSize = 11.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.clickable(role = Role.Button) { manual = false; nowState.value = input(live) }.padding(4.dp))
        }
        val gap = Arrangement.spacedBy(6.dp)
        val lNow = stringResource(R.string.pc_now)
        if (hold) {
            Row(horizontalArrangement = gap) {
                NumField(stringResource(R.string.pc_buy_price), buy, Err.BUY_PRICE in errs, Modifier.weight(1f), onEdit = keep("buy"))
                NumField(stringResource(R.string.pc_qty), qty, Err.QTY in errs, Modifier.weight(1f), onEdit = keep("qty"))
                NumField(lNow, nowState, Err.NOW in errs, Modifier.weight(1f)) { manual = true }
            }
            Row(horizontalArrangement = gap) {
                NumField(stringResource(R.string.pc_sell_qty), sellQty, Err.SELL_QTY in errs, Modifier.weight(1f),
                    hint = qty.value, onEdit = keep("sellQty"))
                NumField(stringResource(R.string.pc_sell_level), sellLv, Err.SELL_LEVEL in errs, Modifier.weight(1f), onEdit = keep("sellLv"))
                NumField(stringResource(R.string.pc_rebuy_level), rebuyLv, Err.REBUY_LEVEL in errs, Modifier.weight(1f), onEdit = keep("rebuyLv"))
            }
        } else {
            Row(horizontalArrangement = gap) {
                NumField(stringResource(R.string.pc_cash_amt), cashAmt, Err.CASH in errs, Modifier.weight(1f), onEdit = keep("cash"))
                NumField(lNow, nowState, Err.NOW in errs, Modifier.weight(1f)) { manual = true }
                NumField(stringResource(R.string.pc_buy_level), buyLv, Err.BUY_LEVEL in errs, Modifier.weight(1f), onEdit = keep("buyLv"))
            }
            Row(horizontalArrangement = gap) {
                NumField(stringResource(R.string.pc_first), first, Err.FIRST_PART in errs, Modifier.weight(1f),
                    hint = if (cashV.isFinite()) input(cashV / 2) else "", onEdit = keep("first"))
                Box(Modifier.weight(2f))
            }
        }
        Row(horizontalArrangement = gap) {
            NumField(stringResource(R.string.pc_fee), fee, Err.FEE in errs, Modifier.weight(1f), onEdit = keep("fee"))
            NumField(stringResource(R.string.pc_slip), slip, Err.SLIP in errs, Modifier.weight(1f), onEdit = keep("slip"))
            NumField(stringResource(R.string.pc_end), end, Err.END in errs, Modifier.weight(1f))
        }
        errs.forEach { e -> ErrBanner(errText(e, hIn, cIn, hold)) }

        if (errs.isEmpty()) {
            if (hold) PositionCalc.hold(hIn)?.let { o ->
                Column(Modifier.fillMaxWidth().background(Color(0xFF17151B), RoundedCornerShape(10.dp)).padding(8.dp)) {
                    KvLine(stringResource(R.string.pc_cost), money(o.costBasis))
                    KvLine(stringResource(R.string.pc_value_now), money(o.marketValue))
                    KvLine(stringResource(R.string.pc_unreal),
                        signed(o.unrealized) + " " + ltr("(" + (if (o.unrealizedPct >= 0) "+" else "−") +
                            f2(kotlin.math.abs(o.unrealizedPct * 100)) + "%)"), moneyColor(o.unrealized))
                    KvLine(stringResource(R.string.pc_be), price(o.breakeven))
                }
            }
            Section(stringResource(R.string.pc_compare))
            EndChips(now, end)
            val opts = if (hold) PositionCalc.hold(hIn)?.options else PositionCalc.cash(cIn)?.options
            opts?.forEach { OptionCard(it, hIn, cIn) }
            Text(stringResource(R.string.pc_note), color = TextDim, fontSize = 10.sp, lineHeight = 13.sp)
        }
    }
}

@Composable
private fun Section(t: String) = Text(t, color = Gold, fontSize = 13.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 4.dp))

@Composable
private fun ErrBanner(t: String) = Text(t, color = TextMain, fontSize = 12.sp, modifier = Modifier.fillMaxWidth()
    .background(Color(0xFF3D1D20), RoundedCornerShape(9.dp)).border(1.dp, SellRed, RoundedCornerShape(9.dp))
    .padding(horizontal = 9.dp, vertical = 6.dp))

@Composable
private fun errText(e: Err, h: PositionCalc.HoldIn, c: PositionCalc.CashIn, hold: Boolean): String {
    @Composable fun pos(id: Int) = stringResource(R.string.pc_e_pos, stringResource(id))
    @Composable fun pct(id: Int) = stringResource(R.string.pc_e_pct, stringResource(id).removeSuffix(" %").removeSuffix("%").trim(),
        ltr("0%"), ltr("5%"))
    return when (e) {
        Err.BUY_PRICE -> pos(R.string.pc_buy_price)
        Err.QTY -> pos(R.string.pc_qty)
        Err.CASH -> pos(R.string.pc_cash_amt)
        Err.NOW -> pos(R.string.pc_now)
        Err.END -> pos(R.string.pc_end)
        Err.FEE -> pct(R.string.pc_fee)
        Err.SLIP -> pct(R.string.pc_slip)
        Err.SELL_QTY -> if (h.sellQty.isFinite() && h.sellQty > 0 && h.qty.isFinite())
            stringResource(R.string.pc_e_sell_qty, coins(h.qty)) else pos(R.string.pc_sell_qty)
        Err.SELL_LEVEL -> pos(R.string.pc_sell_level)
        Err.REBUY_LEVEL -> pos(R.string.pc_rebuy_level)
        Err.BUY_LEVEL -> pos(R.string.pc_buy_level)
        Err.FIRST_PART -> if (c.firstPart.isFinite() && c.firstPart > 0 && c.cash.isFinite())
            stringResource(R.string.pc_e_first, money(c.cash)) else pos(R.string.pc_first)
    }
}

@Composable
private fun EndChips(now: Double, end: MutableState<String>) {
    if (now <= 0) return
    val sel = PositionCalc.parse(end.value)
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
        PositionCalc.endChoices(now).forEach { p ->
            val on = sel != null && kotlin.math.abs(sel - p) < 1e-6 * p + 0.005
            Text(price(p), color = if (on) WaitGold else TextDim, fontSize = 12.sp, textAlign = TextAlign.Center, maxLines = 1,
                fontWeight = if (on) FontWeight.Bold else FontWeight.Normal,
                modifier = Modifier.weight(1f).border(1.dp, if (on) WaitGold else CardEdge, RoundedCornerShape(8.dp))
                    .clickable(role = Role.Button) { end.value = input(p) }.padding(vertical = 5.dp))
        }
    }
}

@Composable
private fun OptionCard(o: PositionCalc.Option, h: PositionCalc.HoldIn, c: PositionCalc.CashIn) {
    val base = o.code == "HOLD" || o.code == "WAIT"
    val title = when (o.code) {
        "HOLD" -> stringResource(R.string.pc_o_hold) + " (" + stringResource(R.string.pc_base) + ")"
        "SELL_NOW" -> stringResource(R.string.pc_o_sell_now, coins(h.sellQty))
        "SELL_LIMIT" -> stringResource(R.string.pc_o_sell_limit, coins(h.sellQty), price(h.sellLevel))
        "SELL_REBUY" -> stringResource(R.string.pc_o_rebuy, coins(h.sellQty), price(h.rebuyLevel))
        "WAIT" -> stringResource(R.string.pc_o_wait) + " (" + stringResource(R.string.pc_base) + ")"
        "BUY_NOW" -> stringResource(R.string.pc_o_buy_now)
        "BUY_LIMIT" -> stringResource(R.string.pc_o_buy_limit, price(c.buyLevel))
        else -> stringResource(R.string.pc_o_split, money(c.firstPart), price(c.buyLevel))
    }
    val risk = when (o.code) {
        "HOLD" -> R.string.pc_r_hold; "SELL_NOW" -> R.string.pc_r_sell_now; "SELL_LIMIT" -> R.string.pc_r_sell_limit
        "SELL_REBUY" -> R.string.pc_r_rebuy; "WAIT" -> R.string.pc_r_wait; "BUY_NOW" -> R.string.pc_r_buy_now
        "BUY_LIMIT" -> R.string.pc_r_buy_limit; else -> R.string.pc_r_split
    }
    Column(Modifier.fillMaxWidth().background(Color(0xFF15131A), RoundedCornerShape(12.dp))
        .border(1.dp, if (base) Grey else CardEdge, RoundedCornerShape(12.dp)).padding(9.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(title, color = TextMain, fontSize = 14.sp, fontWeight = FontWeight.Bold)
        if (o.notFilled == null) OutcomeLines(o.filled, base, o.code)
        else {
            Text(stringResource(if (o.code == "SPLIT") R.string.pc_both else R.string.pc_filled), color = Gold, fontSize = 12.sp)
            OutcomeLines(o.filled, false, o.code)
            Text(stringResource(if (o.code == "SPLIT") R.string.pc_only_first else R.string.pc_not_filled), color = Gold, fontSize = 12.sp)
            OutcomeLines(o.notFilled, false, o.code)
        }
        if (o.asMarket) Text(stringResource(R.string.pc_as_market), color = TextDim, fontSize = 11.sp)
        if (o.code == "SELL_REBUY") Text(stringResource(R.string.pc_more_coins), color = TextDim, fontSize = 11.sp)
        if (o.code == "BUY_LIMIT") Text(stringResource(R.string.pc_cheaper), color = TextDim, fontSize = 11.sp)
        Text("⚠ " + stringResource(risk), color = WaitGold, fontSize = 11.sp, lineHeight = 15.sp)
        if (o.notFilled != null) Text(stringResource(R.string.pc_lock), color = TextDim, fontSize = 10.sp,
            modifier = Modifier.fillMaxWidth().background(Color(0xFF0E0D11), RoundedCornerShape(6.dp)).padding(4.dp))
    }
}

@Composable
private fun OutcomeLines(x: PositionCalc.Outcome, base: Boolean, code: String) {
    val held = when {
        x.coins > 1e-12 && x.cash > 0.005 -> stringResource(R.string.pc_and_cash, coins(x.coins), money(x.cash))
        x.coins > 1e-12 -> stringResource(R.string.pc_holding, coins(x.coins))
        else -> stringResource(R.string.pc_cash_only, money(x.cash))
    }
    Text("$held · " + stringResource(R.string.pc_worth, money(x.value)), color = TextMain, fontSize = 12.sp)
    if (!base) Text(stringResource(R.string.pc_vs, signed(x.vsBase)), color = moneyColor(x.vsBase), fontSize = 12.sp,
        fontWeight = FontWeight.Bold)
    x.realized?.let { Text(stringResource(R.string.pc_realized, signed(it)), color = moneyColor(it), fontSize = 11.sp) }
    if (!base) x.avgCost?.let { Text(stringResource(R.string.pc_avg, price(it)), color = TextDim, fontSize = 11.sp) }
    x.breakeven?.let {
        Text(if (it <= 0.0) stringResource(R.string.pc_recovered) else stringResource(R.string.pc_recover, price(it)),
            color = TextDim, fontSize = 11.sp)
    }
}
