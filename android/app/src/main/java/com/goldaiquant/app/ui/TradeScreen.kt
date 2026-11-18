package com.goldaiquant.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.goldaiquant.app.LocalWatermark
import com.goldaiquant.app.R
import com.goldaiquant.app.TeClosed
import com.goldaiquant.app.TeOrder
import com.goldaiquant.app.TeState
import com.goldaiquant.app.TradeOpp
import com.goldaiquant.app.watermark
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

private val Btc = Color(0xFFF7931A)
private val GreenBg = Color(0xFF0F3A22)
private val RedBg = Color(0xFF3A1416)
private val Box2 = Color(0xFF16161B)

private fun p0(v: Double) = String.format(Locale.US, "%,.0f", v)
private fun pct(v: Double) = (if (v >= 0) "+" else "−") + String.format(Locale.US, "%.1f%%", kotlin.math.abs(v))
private fun hhmm(iso: String?): String? = try {
    DateTimeFormatter.ofPattern("HH:mm").withZone(ZoneId.systemDefault()).format(Instant.parse(iso))
} catch (e: Exception) { null }

/** Small tile on the main screen, in place of «probabilities». */
@Composable
internal fun TradeTile(te: TeState?, modifier: Modifier, onClick: () -> Unit) {
    Column(modifier.background(Color(0xFF0F0E0B), RoundedCornerShape(16.dp)).border(1.dp, Color(0xFF6B5A22), RoundedCornerShape(16.dp))
        .clickable(role = Role.Button, onClick = onClick).padding(vertical = 8.dp, horizontal = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Text(stringResource(R.string.te_tile), color = TextMain, fontSize = 12.sp, fontWeight = FontWeight.Bold, maxLines = 1)
        val (t, c) = when {
            te?.active?.status == "OPEN" -> stringResource(R.string.te_tile_open) to BuyGreen
            te?.active != null -> stringResource(R.string.te_tile_new) to WaitGold
            else -> stringResource(R.string.te_tile_none) to TextDim
        }
        Text(t, color = c, fontSize = 11.sp, fontWeight = FontWeight.Bold, maxLines = 1, textAlign = TextAlign.Center)
    }
}

@Composable
internal fun TradeSheet(te: TeState?, notify: Boolean, onNotify: (Boolean) -> Unit, onCalc: (Double) -> Unit, onClose: () -> Unit) {
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false,
        securePolicy = SecureDialog.securePolicy)) {
        Column(Modifier.fillMaxSize().background(Bg).watermark(LocalWatermark.current).verticalScroll(rememberScrollState())
            .padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.fillMaxWidth().background(Color(0xFF0C0B08), RoundedCornerShape(24.dp))
                .border(1.5.dp, Gold, RoundedCornerShape(24.dp)).padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Header(onClose)
                val o = te?.active
                if (o != null) OrderBody(o, onCalc) else NoTrade(notify, onNotify)
                te?.lastClosed?.let { LastClosed(it) }
                RecordBox(te)
                Text(stringResource(R.string.te_foot), color = TextDim, fontSize = 11.sp, lineHeight = 16.sp)
            }
        }
    }
}

@Composable
private fun Header(onClose: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Box(Modifier.size(42.dp).border(2.dp, Btc, RoundedCornerShape(21.dp)), contentAlignment = Alignment.Center) {
            Text("₿", color = Btc, fontSize = 22.sp, fontWeight = FontWeight.Black)
        }
        Text(stringResource(R.string.te_title), color = TextMain, fontSize = 18.sp, fontWeight = FontWeight.Black, modifier = Modifier.weight(1f))
        Row(Modifier.border(1.dp, Color(0xFF8A6D1E), RoundedCornerShape(16.dp)).padding(horizontal = 10.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("⏳", fontSize = 12.sp)
            Text(stringResource(R.string.te_badge), color = WaitGold, fontSize = 12.sp, fontWeight = FontWeight.Bold)
        }
        Text("✕", color = TextDim, fontSize = 18.sp, modifier = Modifier.clickable(role = Role.Button, onClick = onClose).padding(4.dp))
    }
    Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0xFF3A3218)))
}

@Composable
private fun OrderBody(o: TeOrder, onCalc: (Double) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(stringResource(R.string.te_buy_title), color = TextMain, fontSize = 22.sp, fontWeight = FontWeight.Black, modifier = Modifier.weight(1f))
        Text("↗", color = BuyGreen, fontSize = 26.sp, fontWeight = FontWeight.Bold)
    }
    Text(stringResource(R.string.te_reason), color = TextMain, fontSize = 14.sp, lineHeight = 20.sp)
    Text("ⓘ " + stringResource(R.string.te_not_proven), color = TextDim, fontSize = 12.sp)
    Row(Modifier.fillMaxWidth().background(Box2, RoundedCornerShape(16.dp)).padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(stringResource(R.string.te_entry), color = TextMain, fontSize = 14.sp, modifier = Modifier.weight(1f))
        Text(ltr(p0(o.limit)), color = TextMain, fontSize = 26.sp, fontWeight = FontWeight.Black)
    }
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Level(stringResource(R.string.te_stop), o.stop, TradeOpp.pctFrom(o.limit, o.stop), RedBg, Color(0xFFB3363B), Color(0xFFFF7B80), "⛉", Modifier.weight(1f))
        Level(stringResource(R.string.te_target), o.target, TradeOpp.pctFrom(o.limit, o.target), GreenBg, Color(0xFF1F8F4E), Color(0xFF3FE08A), "◎", Modifier.weight(1f))
    }
    Text(stringResource(R.string.te_before_costs), color = TextDim, fontSize = 11.sp)
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Small("⧗", stringResource(R.string.te_valid), hhmm(o.entryUntil)?.let { stringResource(R.string.te_until, ltr(it)) } ?: "—", Modifier.weight(1f))
        Small("◷", stringResource(R.string.te_duration), stringResource(R.string.te_days, o.holdBars / 6), Modifier.weight(1f))
    }
    val status = if (o.status == "OPEN") stringResource(R.string.te_st_open, ltr(p0(o.entry ?: o.limit)))
                 else stringResource(R.string.te_st_pending)
    Text(status, color = if (o.status == "OPEN") BuyGreen else TextMain, fontSize = 14.sp, textAlign = TextAlign.Center,
        modifier = Modifier.fillMaxWidth().background(Track, RoundedCornerShape(12.dp)).padding(8.dp))
    Text("▦  " + stringResource(R.string.te_calc), color = Color(0xFF111111), fontSize = 17.sp, fontWeight = FontWeight.Black,
        textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().background(Gold, RoundedCornerShape(28.dp))
            .clickable(role = Role.Button) { onCalc(o.limit) }.padding(vertical = 13.dp))
}

@Composable
private fun Level(label: String, v: Double, p: Double, bg: Color, edge: Color, fg: Color, icon: String, modifier: Modifier) {
    Column(modifier.background(bg, RoundedCornerShape(16.dp)).border(1.dp, edge, RoundedCornerShape(16.dp)).padding(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, color = TextMain, fontSize = 13.sp, modifier = Modifier.weight(1f))
            Text(icon, color = fg, fontSize = 18.sp)
        }
        Text(ltr(p0(v)), color = TextMain, fontSize = 21.sp, fontWeight = FontWeight.Black)
        Text(ltr(pct(p)), color = fg, fontSize = 14.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun Small(icon: String, label: String, value: String, modifier: Modifier) {
    Row(modifier.background(Box2, RoundedCornerShape(14.dp)).border(1.dp, Track, RoundedCornerShape(14.dp)).padding(10.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(label, color = TextDim, fontSize = 11.sp)
            Text(value, color = TextMain, fontSize = 14.sp, fontWeight = FontWeight.Bold)
        }
        Text(icon, color = WaitGold, fontSize = 20.sp)
    }
}

@Composable
private fun NoTrade(notify: Boolean, onNotify: (Boolean) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Candles(Modifier.size(width = 90.dp, height = 70.dp))
        Text(stringResource(R.string.te_none_title), color = TextMain, fontSize = 22.sp, fontWeight = FontWeight.Black)
        Text(stringResource(R.string.te_none_text), color = TextDim, fontSize = 14.sp, textAlign = TextAlign.Center, lineHeight = 21.sp)
        Text("🔔  " + stringResource(if (notify) R.string.te_bell_on else R.string.te_bell), color = WaitGold, fontSize = 16.sp,
            fontWeight = FontWeight.Bold, textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth().border(1.5.dp, Gold, RoundedCornerShape(28.dp))
                .background(if (notify) Color(0xFF2A2210) else Color.Transparent, RoundedCornerShape(28.dp))
                .clickable(role = Role.Switch) { onNotify(!notify) }.padding(vertical = 12.dp))
    }
}

@Composable
private fun Candles(modifier: Modifier) {
    Canvas(modifier) {
        val n = 5
        val w = size.width / (n * 2f)
        for (i in 0 until n) {
            val x = w * (2 * i + 0.5f)
            val top = size.height * (0.55f - 0.1f * i)
            val bh = size.height * 0.28f
            drawLine(Grey, Offset(x + w / 2, top - 8f), Offset(x + w / 2, top + bh + 8f), 3f)
            drawRoundRect(Color(0xFF8A8A90), Offset(x, top), Size(w, bh), androidx.compose.ui.geometry.CornerRadius(3f, 3f))
        }
    }
}

@Composable
private fun LastClosed(c: TeClosed) {
    val (txt, col) = when (c.status) {
        "TARGET" -> stringResource(R.string.te_last_target, ltr(pct(100 * (c.net ?: 0.0)))) to BuyGreen
        "STOP" -> stringResource(R.string.te_last_stop, ltr(pct(100 * (c.net ?: 0.0)))) to SellRed
        "TIME" -> stringResource(R.string.te_last_time, ltr(pct(100 * (c.net ?: 0.0)))) to TextMain
        "NOT_FILLED" -> stringResource(R.string.te_last_nofill) to TextDim
        else -> stringResource(R.string.te_last_nodata) to TextDim
    }
    Text(txt, color = col, fontSize = 13.sp, modifier = Modifier.fillMaxWidth().background(Box2, RoundedCornerShape(12.dp)).padding(10.dp))
}

@Composable
private fun RecordBox(te: TeState?) {
    val r = te?.record
    Column(Modifier.fillMaxWidth().background(Color(0xFF121216), RoundedCornerShape(18.dp)).border(1.dp, Track, RoundedCornerShape(18.dp))
        .padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.te_record), color = TextMain, fontSize = 16.sp, fontWeight = FontWeight.Black, modifier = Modifier.weight(1f))
            Text("▮▮", color = WaitGold, fontSize = 14.sp)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Count(r?.wins ?: 0, stringResource(R.string.te_wins), GreenBg, Color(0xFF3FE08A), Modifier.weight(1f))
            Count(r?.losses ?: 0, stringResource(R.string.te_losses), RedBg, Color(0xFFFF7B80), Modifier.weight(1f))
            Count(r?.notFilled ?: 0, stringResource(R.string.te_nofill), Track, TextMain, Modifier.weight(1f))
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(Track))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
            Text(stringResource(R.string.te_count, ltr("${r?.closed ?: 0}")), color = TextMain, fontSize = 13.sp)
            Text("   |   ", color = TextDim, fontSize = 13.sp)
            Text(stringResource(R.string.te_mean, r?.meanNetPct?.let { ltr(pct(it)) } ?: "—"), color = TextMain, fontSize = 13.sp)
        }
    }
}

@Composable
private fun Count(n: Int, label: String, bg: Color, fg: Color, modifier: Modifier) {
    Column(modifier.background(bg, RoundedCornerShape(14.dp)).padding(vertical = 8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Text(ltr("$n"), color = fg, fontSize = 22.sp, fontWeight = FontWeight.Black)
        Text(label, color = fg, fontSize = 13.sp)
    }
}
