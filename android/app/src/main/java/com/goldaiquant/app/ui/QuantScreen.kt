package com.goldaiquant.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.goldaiquant.app.AssetState
import com.goldaiquant.app.LocalWatermark
import com.goldaiquant.app.ModeView
import com.goldaiquant.app.R
import com.goldaiquant.app.RadarItem
import com.goldaiquant.app.RadarState
import com.goldaiquant.app.Verdict
import com.goldaiquant.app.watermark
import java.util.Locale

/** AI QUANT 2.0 phase 4 (design approved 2026-11-22). Renders the ledger's decision state; decides nothing itself. */

private val QualFill = Color(0xFF1B170A)
private val QualEdge = Color(0xFFA88B2C)
private val WaitFill = Color(0xFF141311)
private val WaitEdge = Color(0xFF3A3730)
private val Amber = Color(0xFFF0B45A)
private val Blue = Color(0xFF8FC1EA)
private val Orange = Color(0xFFF0A46A)

internal fun px(v: Double?): String = v?.let { ltr(String.format(Locale.US, if (it >= 1000) "%,.0f" else "%.2f", it)) } ?: "—"

@Composable
internal fun whyText(code: String): String = stringResource(when {
    code == "not_yet_qualified" -> R.string.why_not_yet_qualified
    code == "record_failed" -> R.string.why_record_failed
    code == "no_edge" -> R.string.why_no_edge
    code == "no_signal" -> R.string.why_no_signal
    code == "price_only_asset" -> R.string.why_price_only
    code == "state_inconsistent" -> R.string.why_inconsistent
    code == "state_unavailable" -> R.string.why_unavailable
    code == "hold_is_the_plan" -> R.string.why_hold_plan
    code.contains("stale_or_missing_price") -> R.string.why_blocked_price
    code.contains("stale_advice") -> R.string.why_blocked_advice
    code.contains("conflicting_sides") -> R.string.why_conflict
    code.startsWith("blocked") -> R.string.why_blocked
    else -> R.string.why_unavailable
})

@Composable
private fun Badge(text: String, fg: Color, bg: Color = Color.Transparent, edge: Color = fg) {
    Text(text, color = fg, fontSize = 12.sp, fontWeight = FontWeight.Bold, maxLines = 1,
        modifier = Modifier.background(bg, RoundedCornerShape(50)).border(1.dp, edge, RoundedCornerShape(50))
            .padding(horizontal = 10.dp, vertical = 2.dp))
}

/** «أملك الأصل / لدي سيولة» — stored per asset on the phone (CASH | HOLD). */
@Composable
internal fun ModeToggle(hold: Boolean, assetName: String, onPosition: (String) -> Unit) {
    Row(Modifier.fillMaxWidth().background(Color(0xFF161618), RoundedCornerShape(14.dp))
        .border(1.dp, Color(0xFF2A2A2D), RoundedCornerShape(14.dp)).padding(3.dp)) {
        listOf(true to stringResource(R.string.wd_hold, assetName), false to stringResource(R.string.pos_cash)).forEach { (h, t) ->
            val on = h == hold
            Text(t, color = if (on) Color.Black else TextDim, fontSize = 14.sp, textAlign = TextAlign.Center, maxLines = 1,
                fontWeight = if (on) FontWeight.Bold else FontWeight.Normal,
                modifier = Modifier.weight(1f).background(if (on) Gold else Color.Transparent, RoundedCornerShape(11.dp))
                    .clickable(role = Role.Tab) { if (!on) onPosition(if (h) "HOLD" else "CASH") }.heightIn(min = 40.dp)
                    .padding(vertical = 9.dp))
        }
    }
}

/** The «ماذا أفعل؟» decision: an executive plan only when the ledger marks it QUALIFIED, otherwise «انتظر» + why. */
@Composable
internal fun DecisionBlock(st: AssetState?, hold: Boolean) {
    val m: ModeView = st?.mode(hold) ?: ModeView(Verdict.WAIT, null, null, listOf("state_unavailable"))
    val q = m.verdict != Verdict.WAIT
    val priceOnly = m.why.firstOrNull() == "price_only_asset"
    val shape = RoundedCornerShape(18.dp)
    Column(Modifier.fillMaxWidth().background(if (q) QualFill else WaitFill, shape).border(1.dp, if (q) QualEdge else WaitEdge, shape)
        .padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.ask), color = Color(0xFFD9C78F), fontSize = 13.sp, modifier = Modifier.weight(1f))
            when {
                q -> Badge(stringResource(R.string.q_badge_qualified), Color.Black, Gold, Gold)
                priceOnly -> Badge(stringResource(R.string.q_badge_price_only), TextDim)
                m.why.firstOrNull() == "not_yet_qualified" -> Badge(stringResource(R.string.q_badge_forming), Amber)
                else -> Badge(stringResource(R.string.q_badge_forecast), Color(0xFFC9C6BC))
            }
        }
        val p = m.plan
        val title = when (m.verdict) {
            Verdict.SELL_THEN_REBUY -> stringResource(R.string.q_sell_rebuy)
            Verdict.BUY -> stringResource(R.string.q_buy_now)
            Verdict.BUY_LIMIT -> stringResource(R.string.q_buy_limit, px(p?.entry))
            Verdict.WAIT -> stringResource(R.string.wd_wait)
        }
        Text(title, color = Gold, fontSize = 26.sp, fontWeight = FontWeight.Black)
        Text(stringResource(when (m.verdict) {
            Verdict.SELL_THEN_REBUY -> R.string.q_sell_rebuy_sub
            Verdict.BUY, Verdict.BUY_LIMIT -> R.string.q_buy_sub
            Verdict.WAIT -> if (hold) R.string.q_wait_hold_sub else R.string.q_wait_cash_sub
        }), color = TextMain, fontSize = 13.sp, lineHeight = 19.sp)
        if (q && p != null) {
            val dur = p.durationH?.let { stringResource(R.string.p_dur_val, it) } ?: stringResource(R.string.p_dur_open)
            val cells = if (m.verdict == Verdict.SELL_THEN_REBUY) listOf(
                Triple(R.string.p_sell, px(p.sell), TextMain), Triple(R.string.p_rebuy, px(p.rebuyAt), Blue),
                Triple(R.string.p_inval_above, px(p.invalidateAbove), Orange), Triple(R.string.p_duration, dur, TextMain))
            else listOf(Triple(R.string.p_entry, px(p.entry), TextMain), Triple(R.string.p_target, px(p.target), Blue),
                Triple(R.string.p_inval_below, px(p.invalidateBelow), Orange), Triple(R.string.p_duration, dur, TextMain))
            cells.chunked(2).forEach { row ->
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    row.forEach { (k, v, c) ->
                        Column(Modifier.weight(1f).background(Color(0xFF0F0D07), RoundedCornerShape(10.dp)).padding(8.dp)) {
                            Text(stringResource(k), color = Color(0xFFB5A877), fontSize = 11.sp, maxLines = 1)
                            Text(v, color = c, fontSize = 15.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                        }
                    }
                }
            }
            Text(stringResource(R.string.q_foot_q, m.signalId ?: "—"), color = Color(0xFFB5A877), fontSize = 11.sp)
        } else {
            Column(Modifier.fillMaxWidth().background(Color(0xFF0F0F10), RoundedCornerShape(10.dp)).padding(10.dp),
                verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(stringResource(R.string.q_why_title), color = Color(0xFFD8D5CC), fontSize = 12.sp, fontWeight = FontWeight.Bold)
                m.why.distinct().forEach { Text("• " + whyText(it), color = Color(0xFFC9C6BC), fontSize = 12.sp, lineHeight = 18.sp) }
            }
            Text(stringResource(R.string.q_foot_wait), color = Color(0xFFB5A877), fontSize = 11.sp)
        }
    }
}

/** Bottom tile: same counts as the radar sheet (never «no opportunity» beside a qualified one). */
@Composable
internal fun RadarTile(st: AssetState?, modifier: Modifier, onClick: () -> Unit) {
    Column(modifier.background(Color(0xFF0F0E0B), RoundedCornerShape(16.dp)).border(1.dp, Color(0xFF6B5A22), RoundedCornerShape(16.dp))
        .clickable(role = Role.Button, onClick = onClick).padding(vertical = 8.dp, horizontal = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Text(stringResource(R.string.rd_tile), color = TextMain, fontSize = 12.sp, fontWeight = FontWeight.Bold, maxLines = 1)
        val q = st?.qualified?.size ?: 0
        val f = st?.forming?.size ?: 0
        val (t, c) = when {
            q > 0 -> stringResource(R.string.rd_tile_q, q) to Gold
            f > 0 -> stringResource(R.string.rd_tile_f, f) to Amber
            else -> stringResource(R.string.rd_tile_none) to TextDim
        }
        Text(t, color = c, fontSize = 11.sp, fontWeight = FontWeight.Bold, maxLines = 1, textAlign = TextAlign.Center)
    }
}

@Composable
private fun stateLabel(s: RadarState): Pair<String, Color> = when (s) {
    RadarState.FORMING -> stringResource(R.string.st_forming) to Amber
    RadarState.READY_FOR_VALIDATION -> stringResource(R.string.st_ready) to Blue
    RadarState.QUALIFIED -> stringResource(R.string.st_qualified) to Gold
    RadarState.REJECTED -> stringResource(R.string.st_rejected) to TextDim
    RadarState.EXPIRED -> stringResource(R.string.st_expired) to TextDim
}

@Composable
private fun RadarRow(it: RadarItem, st: AssetState, onPaper: () -> Unit) {
    val q = it.state == RadarState.QUALIFIED
    val shape = RoundedCornerShape(16.dp)
    Column(Modifier.fillMaxWidth().background(if (q) QualFill else Color(0xFF161618), shape)
        .border(1.dp, if (q) QualEdge else Color(0xFF2A2A2D), shape)
        .let { m -> if (it.paper) m.clickable(role = Role.Button, onClick = onPaper) else m }.padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(st.asset + " · " + stringResource(if (it.paper) R.string.rd_paper else R.string.rd_advice), color = TextMain,
                fontSize = 14.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f), maxLines = 1)
            val (l, c) = stateLabel(it.state)
            if (q) Badge(l, Color.Black, Gold, Gold) else Badge(l, c)
        }
        val lv = it.entry ?: it.level
        if (lv != null) Text(stringResource(R.string.rd_level, px(lv)) +
            (it.target?.let { t -> " · " + stringResource(R.string.p_target) + " " + px(t) } ?: "") +
            (it.invalidateBelow?.let { s -> " · " + stringResource(R.string.p_inval_below) + " " + px(s) } ?: ""),
            color = Color(0xFFC9C6BC), fontSize = 12.sp)
        Text(it.id, color = Color(0xFF8E8C86), fontSize = 11.sp)
    }
}

/** Radar sheet: qualified / forming / expired-or-rejected, all from the same decision state. */
@Composable
internal fun RadarSheet(st: AssetState?, onPaper: () -> Unit, onClose: () -> Unit) {
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false,
        securePolicy = SecureDialog.securePolicy)) {
        Column(Modifier.fillMaxSize().background(Bg).watermark(LocalWatermark.current).verticalScroll(rememberScrollState())
            .padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(stringResource(R.string.rd_tile), color = Gold, fontSize = 22.sp, fontWeight = FontWeight.Black)
                    Text(stringResource(R.string.rd_sub), color = TextDim, fontSize = 12.sp)
                }
                Text("✕", color = TextDim, fontSize = 20.sp, modifier = Modifier.clickable(role = Role.Button, onClick = onClose).padding(8.dp))
            }
            Text(stringResource(R.string.rd_q) + " (" + (st?.qualified?.size ?: 0) + ")", color = Gold, fontSize = 13.sp, fontWeight = FontWeight.Bold)
            if (st == null || st.qualified.isEmpty())
                Text(stringResource(R.string.rd_q_none), color = Color(0xFFC9C6BC), fontSize = 13.sp, lineHeight = 19.sp,
                    modifier = Modifier.fillMaxWidth().border(1.dp, WaitEdge, RoundedCornerShape(14.dp)).padding(12.dp))
            else st.qualified.forEach { RadarRow(it, st, onPaper) }
            Text(stringResource(R.string.rd_f) + " (" + (st?.forming?.size ?: 0) + ")", color = Color(0xFFD8D5CC), fontSize = 13.sp,
                fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 6.dp))
            if (st == null || st.forming.isEmpty()) Text(stringResource(R.string.rd_f_none), color = TextDim, fontSize = 12.sp)
            else st.forming.forEach { RadarRow(it, st, onPaper) }
            if (st != null && st.closed.isNotEmpty()) {
                Text(stringResource(R.string.rd_closed), color = TextDim, fontSize = 13.sp, fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(top = 6.dp))
                st.closed.forEach { RadarRow(it, st, onPaper) }
            }
            Text(stringResource(R.string.rd_open_paper) + " ←", color = Gold, fontSize = 13.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.fillMaxWidth().border(1.dp, Color(0xFF6B5A22), RoundedCornerShape(14.dp))
                    .clickable(role = Role.Button, onClick = onPaper).padding(12.dp))
        }
    }
}
