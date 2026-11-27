package com.goldaiquant.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.goldaiquant.app.Journal
import com.goldaiquant.app.R
import com.goldaiquant.app.UiState
import java.util.Locale

private fun usd(v: Double) = (if (v >= 0) "+" else "−") + String.format(Locale.US, "%,.2f $", kotlin.math.abs(v))
private fun num(s: String) = s.replace(',', '.').trim().toDoubleOrNull()?.takeIf { it > 0 }

/** «دفتر صفقاتي»: the owner's real spot trades and their true result (owner 2026-11-27). */
@Composable
internal fun JournalDialog(s: UiState, onClose: () -> Unit) {
    val prefs = LocalContext.current.getSharedPreferences("gold_ai_quant", android.content.Context.MODE_PRIVATE)
    var trades by remember { mutableStateOf(Journal.load(prefs)) }
    var costs by remember { mutableStateOf(Journal.costs(prefs)) }
    var adding by remember { mutableStateOf(false) }
    var selling by remember { mutableStateOf<Journal.Trade?>(null) }
    var editCosts by remember { mutableStateOf(false) }
    fun price(a: String): Double? = s.live[a]?.price ?: (if (a == s.asset) s.decision?.quote else null)
        ?: com.goldaiquant.app.Widgets.decision(prefs, a)?.quote
    fun put(ts: List<Journal.Trade>) { trades = ts; Journal.save(prefs, ts) }

    DialogFrame(stringResource(R.string.j_title), onClose) {
        val sm = Journal.summary(trades, costs, ::price)
        Column(Modifier.fillMaxWidth().background(Color(0xFF161618), RoundedCornerShape(14.dp))
            .border(1.dp, Color(0xFF3A3018), RoundedCornerShape(14.dp)).padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Line(stringResource(R.string.j_realized, sm.closed, sm.wins), ltr(usd(sm.realizedUsd)),
                if (sm.realizedUsd >= 0) BuyGreen else SellRed)
            Line(stringResource(R.string.j_open, sm.open), ltr(String.format(Locale.US, "%,.2f $", sm.lockedUsd)), TextMain)
            Line(stringResource(R.string.j_unrealized), sm.unrealizedUsd?.let { ltr(usd(it)) } ?: "—",
                if ((sm.unrealizedUsd ?: 0.0) >= 0) BuyGreen else SellRed)
            if (sm.stuck > 0) Text("⚠ " + stringResource(R.string.j_stuck, sm.stuck, Journal.STUCK_DAYS), color = WaitGold, fontSize = 13.sp)
            Text(stringResource(R.string.j_costs, ltr(String.format(Locale.US, "%.2f%%", costs.cryptoRoundTripPct)),
                ltr(String.format(Locale.US, "%.2f $", costs.goldPerTradeUsd))), color = TextDim, fontSize = 11.sp,
                modifier = Modifier.clickable { editCosts = true })
        }
        Text(stringResource(if (Journal.autoOn(prefs)) R.string.j_auto_note else R.string.j_auto_off_note,
            ltr(String.format(Locale.US, "%,.0f $", Journal.autoAmount(prefs)))), color = TextDim, fontSize = 12.sp,
            modifier = Modifier.clickable { editCosts = true })
        TextButton(onClick = { adding = true }) { Text("＋ " + stringResource(R.string.j_add), color = Gold, fontWeight = FontWeight.Bold) }

        val open = trades.filter { it.open }.sortedByDescending { it.buyAt }
        if (open.isNotEmpty()) Text(stringResource(R.string.j_open_list), color = Gold, fontWeight = FontWeight.Bold, fontSize = 14.sp)
        open.forEach { t ->
            val px = price(t.asset)
            val days = ((System.currentTimeMillis() - t.buyAt) / 86_400_000L).toInt()
            Column(Modifier.fillMaxWidth().background(Color(0xFF121214), RoundedCornerShape(12.dp)).padding(10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text((if (t.auto) "🤖 " else "") + t.asset + " · " + ltr(String.format(Locale.US, "%,.0f $", t.amountUsd)) + " @ " + ltr(t.buyPrice.p2()),
                        color = TextMain, fontWeight = FontWeight.Bold, fontSize = 14.sp, modifier = Modifier.weight(1f))
                    Text(stringResource(R.string.j_sell), color = Color.Black, fontWeight = FontWeight.Bold, fontSize = 13.sp,
                        modifier = Modifier.background(Gold, RoundedCornerShape(10.dp)).clickable(role = Role.Button) { selling = t }
                            .padding(horizontal = 12.dp, vertical = 4.dp))
                }
                Text(stringResource(R.string.j_target, ltr(Journal.target(t).p2()), days) +
                    (px?.let { "  ·  " + stringResource(R.string.j_now, ltr(usd(Journal.net(t, it, costs)))) } ?: ""),
                    color = TextDim, fontSize = 12.sp)
            }
        }
        val closed = trades.filter { !it.open }.sortedByDescending { it.sellAt }.take(30)
        if (closed.isNotEmpty()) Text(stringResource(R.string.j_closed_list), color = Gold, fontWeight = FontWeight.Bold, fontSize = 14.sp)
        closed.forEach { t ->
            val n = Journal.net(t, t.sellPrice!!, costs)
            Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                Text((if (t.auto) "🤖 " else "") + t.asset + "  " + ltr(t.buyPrice.p2()) + " → " + ltr(t.sellPrice.p2()), color = TextMain, fontSize = 13.sp,
                    modifier = Modifier.weight(1f))
                Text(ltr(usd(n)), color = if (n >= 0) BuyGreen else SellRed, fontSize = 13.sp, fontWeight = FontWeight.Bold)
            }
        }
        if (trades.isEmpty()) Text(stringResource(R.string.j_empty), color = TextDim, fontSize = 13.sp)
        Text(stringResource(R.string.j_private), color = TextDim, fontSize = 11.sp)
    }

    if (adding) {
        var asset by remember { mutableStateOf(s.asset) }
        var amount by remember { mutableStateOf("") }
        var buy by remember { mutableStateOf(price(s.asset)?.let { String.format(Locale.US, "%.2f", it) } ?: "") }
        DialogFrame(stringResource(R.string.j_add), { adding = false }) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("XAU", "BTC", "ETH", "SOL").forEach { a ->
                    Text(a, color = if (a == asset) Color.Black else TextMain, fontWeight = FontWeight.Bold,
                        modifier = Modifier.background(if (a == asset) Gold else Color(0xFF26262A), RoundedCornerShape(10.dp))
                            .clickable { asset = a; price(a)?.let { buy = String.format(Locale.US, "%.2f", it) } }
                            .padding(horizontal = 10.dp, vertical = 6.dp))
                }
            }
            OutlinedTextField(amount, { amount = it.take(12) }, singleLine = true, label = { Text(stringResource(R.string.j_amount)) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(buy, { buy = it.take(14) }, singleLine = true, label = { Text(stringResource(R.string.j_buy_price)) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth())
            val ok = num(amount) != null && num(buy) != null
            TextButton(enabled = ok, onClick = {
                put(trades + Journal.Trade(System.currentTimeMillis(), asset, num(amount)!!, num(buy)!!, System.currentTimeMillis()))
                adding = false
            }) { Text(stringResource(R.string.j_save), color = if (ok) Gold else TextDim, fontWeight = FontWeight.Bold) }
        }
    }

    selling?.let { t ->
        var sell by remember(t.id) { mutableStateOf(price(t.asset)?.let { String.format(Locale.US, "%.2f", it) } ?: "") }
        DialogFrame(stringResource(R.string.j_sell) + " · " + t.asset, { selling = null }) {
            OutlinedTextField(sell, { sell = it.take(14) }, singleLine = true, label = { Text(stringResource(R.string.j_sell_price)) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth())
            num(sell)?.let { Text(stringResource(R.string.j_result, ltr(usd(Journal.net(t, it, costs)))), color = TextMain, fontSize = 14.sp) }
            Row {
                TextButton(enabled = num(sell) != null, onClick = {
                    put(trades.map { x -> if (x.id == t.id) x.copy(sellPrice = num(sell), sellAt = System.currentTimeMillis()) else x })
                    selling = null
                }) { Text(stringResource(R.string.j_save), color = Gold, fontWeight = FontWeight.Bold) }
                TextButton(onClick = { put(trades.filter { it.id != t.id }); selling = null }) {
                    Text(stringResource(R.string.j_delete), color = SellRed)
                }
            }
        }
    }

    if (editCosts) {
        var cp by remember { mutableStateOf(costs.cryptoRoundTripPct.toString()) }
        var gd by remember { mutableStateOf(costs.goldPerTradeUsd.toString()) }
        var auto by remember { mutableStateOf(Journal.autoOn(prefs)) }
        var amt by remember { mutableStateOf(Journal.autoAmount(prefs).toString()) }
        DialogFrame(stringResource(R.string.j_costs_title), { editCosts = false }) {
            OutlinedTextField(cp, { cp = it.take(6) }, singleLine = true, label = { Text(stringResource(R.string.j_cost_crypto)) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(gd, { gd = it.take(6) }, singleLine = true, label = { Text(stringResource(R.string.j_cost_gold)) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth())
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.j_auto_on), color = TextMain, fontSize = 14.sp, modifier = Modifier.weight(1f))
                androidx.compose.material3.Switch(checked = auto, onCheckedChange = { auto = it })
            }
            OutlinedTextField(amt, { amt = it.take(8) }, singleLine = true, label = { Text(stringResource(R.string.j_auto_amount)) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth())
            TextButton(onClick = {
                prefs.edit().putBoolean("j_auto", auto).putFloat("j_auto_amount",
                    (amt.replace(',', '.').toDoubleOrNull()?.takeIf { it > 0 } ?: Journal.autoAmount(prefs)).toFloat()).apply()
                val c = Journal.Costs(cp.replace(',', '.').toDoubleOrNull() ?: costs.cryptoRoundTripPct,
                    gd.replace(',', '.').toDoubleOrNull() ?: costs.goldPerTradeUsd)
                costs = c; Journal.saveCosts(prefs, c); editCosts = false
            }) { Text(stringResource(R.string.j_save), color = Gold, fontWeight = FontWeight.Bold) }
        }
    }
}

@Composable
private fun Line(k: String, v: String, c: Color) = Row(Modifier.fillMaxWidth()) {
    Text(k, color = TextDim, fontSize = 13.sp, modifier = Modifier.weight(1f))
    Text(v, color = c, fontSize = 14.sp, fontWeight = FontWeight.Bold)
}
