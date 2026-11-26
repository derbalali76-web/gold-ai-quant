package com.goldaiquant.app.ui

import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.goldaiquant.app.Candles
import com.goldaiquant.app.Decision
import com.goldaiquant.app.HorizonCard
import com.goldaiquant.app.HorizonScenarios
import com.goldaiquant.app.Level
import com.goldaiquant.app.LiveLevels
import com.goldaiquant.app.PriceAlert
import com.goldaiquant.app.PriceAlerts
import com.goldaiquant.app.R
import com.goldaiquant.app.SimpleAdvice
import com.goldaiquant.app.UiState
import java.util.Locale

/**
 * Home screen v2 (owner design, 2026-11-26): black, glowing gold cards, one screen without scrolling.
 * Same data and rules as before: the green bar says «الأرجح» only for tested evidence; otherwise it is the trend.
 */

val Cairo = FontFamily(
    Font(R.font.cairo_regular, FontWeight.Normal),
    Font(R.font.cairo_semibold, FontWeight.SemiBold),
    Font(R.font.cairo_bold, FontWeight.Bold),
    Font(R.font.cairo_extrabold, FontWeight.ExtraBold),
    Font(R.font.cairo_black, FontWeight.Black),
)

internal val H2Gold = Color(0xFFF5C542)
internal val H2GoldDeep = Color(0xFFC9982B)
internal val H2Green = Color(0xFF2BD46A)
internal val H2Red = Color(0xFFFF3B3B)
private val PillBrush = Brush.verticalGradient(listOf(Color(0xFFFFE58A), Color(0xFFF2C03C), Color(0xFFD99A1E)))
private val ButtonBrush = Brush.verticalGradient(listOf(Color(0xFFFFF0A8), Color(0xFFF7CD4A), Color(0xFFE3A825), Color(0xFFF2C548)))
private val EdgeBrush = Brush.verticalGradient(listOf(Color(0xFFFFD966), Color(0xFFB8862B)))

/** Black card with a gold edge and a soft gold glow. */
@Composable
internal fun GlowCard(modifier: Modifier = Modifier, shape: Shape = RoundedCornerShape(18.dp), glow: Color = H2Gold,
                      edge: Brush = EdgeBrush, bg: Brush = Brush.verticalGradient(listOf(Color(0xFF0B0B0C), Color(0xFF050505))),
                      onClick: (() -> Unit)? = null, content: @Composable () -> Unit) {
    val base = modifier.shadow(10.dp, shape, ambientColor = glow, spotColor = glow).background(bg, shape).border(1.5.dp, edge, shape)
    val m = if (onClick != null) base.clip(shape).clickable(role = Role.Button, onClick = onClick) else base
    Box(m) { content() }
}

@Composable
private fun Circle(onClick: () -> Unit, cd: String, dot: Boolean = false, content: @Composable () -> Unit) {
    Box(Modifier.size(40.dp).shadow(6.dp, CircleShape, ambientColor = H2Gold, spotColor = H2Gold)
        .background(Color(0xFF0A0A0A), CircleShape).border(2.dp, EdgeBrush, CircleShape).clip(CircleShape)
        .clickable(role = Role.Button, onClick = onClick).semantics { contentDescription = cd },
        contentAlignment = Alignment.Center) {
        content()
        if (dot) Box(Modifier.align(Alignment.TopEnd).padding(5.dp).size(9.dp).background(Color(0xFFFF3030), CircleShape))
    }
}

@Composable
private fun Bars(modifier: Modifier) = Canvas(modifier) {
    val w = size.width / 3.6f
    listOf(0.45f, 0.72f, 1f).forEachIndexed { i, h ->
        drawRoundRect(H2Gold, Offset(i * w * 1.3f, size.height * (1 - h)), Size(w, size.height * h), CornerRadius(2f))
    }
}

@Composable
internal fun H2Header(s: UiState, onSettings: () -> Unit, onCalendar: () -> Unit) {
    val soon = s.calendar?.events?.any { it.importance >= 3 && it.time.isAfter(java.time.Instant.now()) &&
        it.time.isBefore(java.time.Instant.now().plusSeconds(24 * 3600)) } == true
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        // RTL: the first child sits on the right (bell), the last on the left (settings), as in the design
        Circle(onCalendar, stringResource(R.string.cal_title), dot = soon) {
            Text("🔔", fontSize = 20.sp)
        }
        Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Bars(Modifier.size(width = 24.dp, height = 22.dp))
                Spacer(Modifier.width(6.dp))
                Text(stringResource(R.string.app_name), color = H2Gold, fontFamily = Cairo, fontWeight = FontWeight.Black,
                    fontSize = 24.sp, maxLines = 1, style = androidx.compose.ui.text.TextStyle(
                        shadow = androidx.compose.ui.graphics.Shadow(H2Gold.copy(alpha = 0.6f), blurRadius = 18f)))
            }
        }
        Circle(onSettings, stringResource(R.string.cd_settings)) { Text("⚙", color = H2Gold, fontSize = 22.sp) }
    }
}

internal fun coinRes(a: String): Int = when (a) {
    "BTC" -> R.drawable.coin_btc; "ETH" -> R.drawable.coin_eth; "SOL" -> R.drawable.coin_sol; else -> R.drawable.coin_xau
}

@Composable
internal fun H2PositionAndAsset(s: UiState, onPosition: (String) -> Unit, onAsset: () -> Unit) {
    val hold = s.position == "HOLD"
    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically) {
        GlowCard(Modifier.weight(1f), RoundedCornerShape(26.dp)) {
            Row(Modifier.padding(4.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                listOf(false to R.string.sa_cash, true to R.string.sa_hold).forEach { (h, label) ->
                    val on = h == hold
                    Row(Modifier.weight(1f).clip(RoundedCornerShape(22.dp))
                        .background(if (on) PillBrush else Brush.linearGradient(listOf(Color.Transparent, Color.Transparent)))
                        .clickable(role = Role.Button) { onPosition(if (h) "HOLD" else "CASH") }.padding(vertical = 7.dp),
                        horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                        Text(stringResource(label), color = if (on) Color(0xFF1A1203) else Color.White, fontFamily = Cairo,
                            fontWeight = if (on) FontWeight.ExtraBold else FontWeight.Bold, fontSize = 13.sp, maxLines = 1,
                            lineHeight = 15.sp)
                        if (h) {
                            Spacer(Modifier.width(4.dp))
                            Image(painterResource(R.drawable.hi_levels), null, Modifier.size(17.dp))
                        }
                    }
                }
            }
        }
        val cd = stringResource(R.string.cd_asset)
        GlowCard(Modifier.widthIn(min = 128.dp).fillMaxHeight(), RoundedCornerShape(26.dp), onClick = onAsset) {
            Row(Modifier.fillMaxHeight().padding(horizontal = 8.dp).semantics { contentDescription = cd },
                verticalAlignment = Alignment.CenterVertically) {
                Text("⌄", color = H2Gold, fontSize = 16.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.width(6.dp))
                Text(ltr(assetPair(s.asset).replace("/", " / ")), color = Color.White, fontFamily = Cairo,
                    fontWeight = FontWeight.Bold, fontSize = 14.sp, maxLines = 1)
                Spacer(Modifier.width(6.dp))
                Image(painterResource(coinRes(s.asset)), null, Modifier.size(28.dp))
            }
        }
    }
}

@Composable
private fun CandleChart(c: Candles?, modifier: Modifier) {
    if (c == null || c.size < 3) { Box(modifier); return }
    val n = minOf(32, c.size)
    val o = c.o.takeLast(n); val h = c.h.takeLast(n); val l = c.l.takeLast(n); val cl = c.c.takeLast(n)
    Canvas(modifier) {
        val lo = l.min(); val hi = h.max(); val span = (hi - lo).takeIf { it > 0 } ?: 1.0
        fun y(v: Double) = (size.height * (1 - (v - lo) / span)).toFloat()
        val step = size.width / n
        for (i in 0 until n) {
            val up = cl[i] >= o[i]
            val col = if (up) H2Green else H2Red
            val x = step * i + step / 2
            drawLine(col, Offset(x, y(h[i])), Offset(x, y(l[i])), strokeWidth = 1.2f)
            val top = y(maxOf(o[i], cl[i])); val bot = y(minOf(o[i], cl[i]))
            drawRect(col, Offset(x - step * 0.32f, top), Size(step * 0.64f, maxOf(2f, bot - top)))
        }
    }
}

@Composable
internal fun H2PriceCard(d: Decision?, s: UiState, modifier: Modifier, onChart: () -> Unit) {
    val tick = s.live[s.asset]?.takeIf { System.currentTimeMillis() - it.at < 15_000 && d?.marketClosed != true }
    val price = tick?.price ?: d?.quote
    GlowCard(modifier, onClick = onChart) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            // the chart on the right in RTL (first child), the price on the left
            CandleChart(s.candles["${s.asset}/H1"], Modifier.weight(1f).height(56.dp))
            Spacer(Modifier.width(10.dp))
            Column(horizontalAlignment = Alignment.Start) {
                Text(ltr(price?.p2() ?: "—"), color = Color.White, fontFamily = Cairo, fontWeight = FontWeight.Black,
                    fontSize = 34.sp, lineHeight = 36.sp, maxLines = 1)
                val cc = s.candles["${s.asset}/H1"]
                val ref = d?.quoteChange?.let { null } ?: cc?.takeIf { it.size >= 25 }?.c?.let { it[it.size - 25] }
                val ch = d?.quoteChange ?: if (ref != null && price != null) price - ref else null
                val pctV = d?.quoteChangePct ?: if (ref != null && ch != null && ref > 0) 100 * ch / ref else null
                if (ch != null) {
                    val up = ch >= 0
                    val pct = pctV?.let { " (${if (up) "+" else ""}${String.format(Locale.US, "%.2f", it)}%)" } ?: ""
                    Text(ltr("${if (up) "+" else ""}${ch.p2()}$pct ${if (up) "▲" else "▼"}"), color = if (up) H2Green else H2Red,
                        fontFamily = Cairo, fontWeight = FontWeight.ExtraBold, fontSize = 15.sp, lineHeight = 17.sp, maxLines = 1)
                }
                if (tick != null) Text(stringResource(R.string.live_badge), color = H2Green, fontFamily = Cairo, fontSize = 10.sp,
                    lineHeight = 12.sp)
                else (d?.quoteTime ?: s.receivedAt)?.let { t ->
                    Text(stringResource(if (d?.marketClosed == true) R.string.closed_price_at else R.string.updated_at,
                        ltr(java.time.format.DateTimeFormatter.ofPattern("HH:mm").format(t.atZone(java.time.ZoneId.systemDefault())))),
                        color = if (d?.marketClosed == true) WaitGold else Color(0xFFA3A3A8), fontFamily = Cairo, fontSize = 10.sp,
                        lineHeight = 12.sp, maxLines = 1)
                }
            }
        }
    }
}

@Composable
internal fun H2Tabs(current: String, onSelect: (String) -> Unit) {
    GlowCard(Modifier.fillMaxWidth(), RoundedCornerShape(26.dp)) {
        Row(Modifier.padding(4.dp), verticalAlignment = Alignment.CenterVertically) {
            com.goldaiquant.app.HorizonModel.ORDER.forEachIndexed { i, h ->
                val on = h == current
                if (i > 0) Box(Modifier.width(1.dp).height(22.dp).background(Color(0xFF5A4A20)))
                Text(horizonName(h), color = if (on) Color(0xFF1A1203) else Color.White, fontFamily = Cairo,
                    fontWeight = if (on) FontWeight.ExtraBold else FontWeight.SemiBold, fontSize = 17.sp, lineHeight = 20.sp,
                    textAlign = TextAlign.Center, maxLines = 1,
                    modifier = Modifier.weight(1f).clip(RoundedCornerShape(22.dp))
                        .background(if (on) PillBrush else Brush.linearGradient(listOf(Color.Transparent, Color.Transparent)))
                        .clickable(role = Role.Tab) { onSelect(h) }.padding(vertical = 5.dp))
            }
        }
    }
}

@Composable
internal fun H2AskButton(onClick: () -> Unit) {
    val label = stringResource(R.string.h2_ask)
    val shape = RoundedCornerShape(40.dp)
    Row(Modifier.fillMaxWidth().shadow(18.dp, shape, ambientColor = Color(0xFFFAC83C), spotColor = Color(0xFFFAC83C))
        .background(ButtonBrush, shape).border(2.dp, Color(0xFFFFE58A), shape).clip(shape)
        .clickable(role = Role.Button, onClick = onClick).semantics { contentDescription = label }
        .padding(horizontal = 16.dp, vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(ltr("»"), color = Color(0xFF140E00), fontSize = 28.sp, fontWeight = FontWeight.Black)
        Text(label, color = Color(0xFF140E00), fontFamily = Cairo, fontWeight = FontWeight.Black, fontSize = 25.sp,
            lineHeight = 30.sp, textAlign = TextAlign.Center, maxLines = 1, modifier = Modifier.weight(1f))
        Box(Modifier.width(1.dp).height(38.dp).background(Color(0x40000000)))
        Spacer(Modifier.width(10.dp))
        Image(painterResource(R.drawable.hi_target), null, Modifier.size(48.dp))
    }
}

@Composable
private fun Arrow(up: Boolean, color: Color, modifier: Modifier) = Canvas(modifier) {
    val w = size.width; val h = size.height
    val pts = if (up) listOf(0f to .9f, .3f to .5f, .45f to .68f, .8f to .18f) else listOf(0f to .1f, .3f to .5f, .45f to .32f, .8f to .82f)
    val p = Path().apply { pts.forEachIndexed { i, (x, y) -> if (i == 0) moveTo(x * w, y * h) else lineTo(x * w, y * h) } }
    drawPath(p, color.copy(alpha = 0.35f), style = Stroke(10f, cap = StrokeCap.Round, join = StrokeJoin.Round))
    drawPath(p, color, style = Stroke(5f, cap = StrokeCap.Round, join = StrokeJoin.Round))
    val head = Path().apply {
        if (up) { moveTo(w * .62f, h * .1f); lineTo(w, 0f); lineTo(w * .95f, h * .42f) }
        else { moveTo(w * .62f, h * .9f); lineTo(w, h); lineTo(w * .95f, h * .58f) }
        close()
    }
    drawPath(head, color)
}

/** The live levels and the likely side of the selected card (same rules as the scenario card). */
internal data class H2View(val c: HorizonCard, val v: HorizonScenarios.View, val tested: Boolean)

internal fun h2View(c0: HorizonCard, s: UiState, d: Decision): H2View {
    val px = s.live[s.asset]?.price ?: d.quote
    val c = c0.copy(levels = LiveLevels.reanchor(c0.levels, px))
    val ev = HorizonScenarios.of(c, d.brief.takeIf { LiveLevels.briefConsistent(it, px) }, d.isDemo)
    val v = looseLikely(ev, c.trend?.direction)
    return H2View(c, v, ev.likely != HorizonScenarios.Likely.NONE)
}

@Composable
internal fun H2TrendBar(x: H2View, onClick: () -> Unit) {
    val (word, color, up) = when (x.v.likely) {
        HorizonScenarios.Likely.UP -> Triple(R.string.h2_up, H2Green, true)
        HorizonScenarios.Likely.DOWN -> Triple(R.string.h2_down, H2Red, false)
        HorizonScenarios.Likely.BETWEEN -> Triple(R.string.h2_between, H2Gold, null)
        HorizonScenarios.Likely.NONE -> Triple(R.string.h2_side, H2Gold, null)
    }
    val target = when (x.v.likely) {
        HorizonScenarios.Likely.UP -> x.v.up?.trigger; HorizonScenarios.Likely.DOWN -> x.v.down?.trigger; else -> null
    }
    val bg = Brush.verticalGradient(listOf(color.copy(alpha = 0.10f), Color(0xFF030805)))
    GlowCard(Modifier.fillMaxWidth(), RoundedCornerShape(18.dp), glow = color,
        edge = Brush.verticalGradient(listOf(color, color.copy(alpha = 0.6f))), bg = bg, onClick = onClick) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
            Column {
                Text(stringResource(if (x.tested) R.string.h2_likely else R.string.h2_trend), color = Color.White,
                    fontFamily = Cairo, fontWeight = FontWeight.Bold, fontSize = 13.sp, lineHeight = 15.sp, maxLines = 1)
                Text("(" + scHorizon(x.c.horizon) + ")" + if (!x.tested) " · " + stringResource(R.string.h2_untested) else "",
                    color = Color(0xFFBDBDBD), fontFamily = Cairo, fontSize = 10.sp, lineHeight = 12.sp, maxLines = 1)
            }
            Spacer(Modifier.width(8.dp))
            Text((if (up == true) "⬆ " else if (up == false) "⬇ " else "") + stringResource(word), color = Color.White,
                fontFamily = Cairo, fontWeight = FontWeight.ExtraBold, fontSize = 14.sp, lineHeight = 17.sp, maxLines = 1,
                modifier = Modifier.background(color.copy(alpha = if (up == null) 0.35f else 0.85f), RoundedCornerShape(16.dp))
                    .padding(horizontal = 10.dp, vertical = 1.dp))
            Spacer(Modifier.width(8.dp))
            Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                if (target != null) {
                    Text(stringResource(R.string.h2_toward), color = Color.White, fontFamily = Cairo, fontSize = 12.sp, lineHeight = 14.sp)
                    Spacer(Modifier.width(4.dp))
                    Text(ltr(target.p2()), color = Color.White, fontFamily = Cairo, fontWeight = FontWeight.Black, fontSize = 21.sp,
                        lineHeight = 24.sp, maxLines = 1)
                }
            }
            if (up != null) Arrow(up, color, Modifier.size(width = 44.dp, height = 26.dp))
        }
    }
}

@Composable
internal fun H2ScenarioPair(x: H2View, modifier: Modifier = Modifier, onClick: () -> Unit = {}) {
    val lk = if (x.tested) x.v.likely else HorizonScenarios.Likely.NONE
    val badge = stringResource(if (x.tested) R.string.h2_badge_likely else R.string.h2_badge_trend)
    Row(modifier.fillMaxWidth().height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        H2Scenario(true, x.v.up, faint = lk == HorizonScenarios.Likely.DOWN,
            badge.takeIf { x.v.likely == HorizonScenarios.Likely.UP }, Modifier.weight(1f).fillMaxHeight(), onClick)
        H2Scenario(false, x.v.down, faint = lk == HorizonScenarios.Likely.UP,
            badge.takeIf { x.v.likely == HorizonScenarios.Likely.DOWN }, Modifier.weight(1f).fillMaxHeight(), onClick)
    }
}

@Composable
private fun H2Scenario(up: Boolean, side: HorizonScenarios.Side?, faint: Boolean, badge: String?, modifier: Modifier,
                       onClick: () -> Unit) {
    val color = if (up) H2Green else H2Red
    val bg = Brush.linearGradient(listOf(if (up) Color(0xFF06311A) else Color(0xFF3A0709), Color(0xFF050505)))
    GlowCard(modifier.alpha(if (faint) 0.5f else 1f), RoundedCornerShape(16.dp), glow = color,
        edge = Brush.verticalGradient(listOf(color, color.copy(alpha = 0.6f))), bg = bg, onClick = onClick) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(if (up) R.string.h2_sc_up else R.string.h2_sc_down), color = color, fontFamily = Cairo,
                    fontWeight = FontWeight.ExtraBold, fontSize = 13.sp, lineHeight = 15.sp, maxLines = 1, modifier = Modifier.weight(1f))
                if (badge != null) Text(badge, color = Color.White, fontFamily = Cairo, fontWeight = FontWeight.Bold, fontSize = 10.sp,
                    lineHeight = 12.sp, maxLines = 1, modifier = Modifier.background(color.copy(alpha = 0.75f), RoundedCornerShape(10.dp))
                        .padding(horizontal = 6.dp, vertical = 1.dp))
            }
            if (side != null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(ltr((side.target ?: side.trigger).p2()), color = Color.White, fontFamily = Cairo,
                        fontWeight = FontWeight.Black, fontSize = 24.sp, lineHeight = 27.sp, maxLines = 1, modifier = Modifier.weight(1f))
                    Arrow(up, color, Modifier.size(width = 34.dp, height = 22.dp))
                }
                Text(stringResource(if (up) R.string.h2_if_up else R.string.h2_if_down, ltr(side.trigger.p2())),
                    color = Color(0xFFDADADA), fontFamily = Cairo, fontSize = 11.sp, lineHeight = 13.sp, maxLines = 1)
            } else Text("—", color = Color.White, fontSize = 22.sp)
        }
    }
}

private fun strong(l: Level) = (l.strength ?: 0) >= 70 || l.tests >= 5

@Composable
private fun AreaChart(c: Candles?, modifier: Modifier) {
    if (c == null || c.size < 3) { Box(modifier); return }
    val xs = c.c.takeLast(48)
    Canvas(modifier) {
        val lo = xs.min(); val span = (xs.max() - lo).takeIf { it > 0 } ?: 1.0
        val line = Path(); val fill = Path()
        xs.forEachIndexed { i, v ->
            val x = size.width * i / (xs.size - 1)
            val y = (size.height * 0.08f + size.height * 0.88f * (1 - (v - lo) / span)).toFloat()
            if (i == 0) { line.moveTo(x, y); fill.moveTo(x, size.height); fill.lineTo(x, y) } else { line.lineTo(x, y); fill.lineTo(x, y) }
        }
        fill.lineTo(size.width, size.height); fill.close()
        drawPath(fill, Brush.verticalGradient(listOf(H2Gold.copy(alpha = 0.75f), H2Gold.copy(alpha = 0f))))
        drawPath(line, H2Gold.copy(alpha = 0.35f), style = Stroke(8f, join = StrokeJoin.Round))
        drawPath(line, Color(0xFFFFE07A), style = Stroke(3.5f, join = StrokeJoin.Round))
    }
}

@Composable
private fun LevelChip(l: Level, support: Boolean) {
    val (fg, bg) = when {
        support -> Color(0xFF3CE07A) to Color(0xFF0B3A1C)
        strong(l) -> Color(0xFFFF6B70) to Color(0xFF4A0C10)
        else -> Color(0xFFE5E5E5) to Color(0xFF2A2A2A)
    }
    val label = stringResource(when {
        support && strong(l) -> R.string.h2_sup_strong; support -> R.string.h2_sup
        strong(l) -> R.string.h2_res_strong; else -> R.string.h2_res
    })
    Text(label, color = fg, fontFamily = Cairo, fontWeight = FontWeight.ExtraBold, fontSize = 12.sp, lineHeight = 15.sp,
        textAlign = TextAlign.Center, maxLines = 1,
        modifier = Modifier.width(84.dp).background(bg, RoundedCornerShape(20.dp)).padding(vertical = 2.dp))
}

@Composable
internal fun H2LevelsCard(x: H2View, s: UiState, modifier: Modifier, onOpen: () -> Unit) {
    val lv = x.c.levels
    val rows = buildList {
        lv?.resistances?.getOrNull(0)?.let { add(it to false) }
        lv?.supports?.getOrNull(0)?.let { add(it to true) }
    }
    GlowCard(modifier, onClick = onOpen) {
        Row(Modifier.fillMaxSize().padding(horizontal = 12.dp, vertical = 8.dp)) {
            Column(Modifier.weight(1f).fillMaxHeight()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Image(painterResource(R.drawable.hi_levels), null, Modifier.size(28.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.h2_levels), color = Color.White, fontFamily = Cairo, fontWeight = FontWeight.ExtraBold,
                        fontSize = 16.sp, lineHeight = 19.sp, maxLines = 1)
                }
                AreaChart(s.candles["${s.asset}/H1"], Modifier.fillMaxWidth().weight(1f).padding(top = 4.dp))
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f).fillMaxHeight(), verticalArrangement = Arrangement.SpaceEvenly) {
                rows.forEach { (l, sup) ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(ltr(l.price.p2()), color = Color.White, fontFamily = Cairo, fontWeight = FontWeight.ExtraBold,
                            fontSize = 18.sp, lineHeight = 21.sp, maxLines = 1, modifier = Modifier.weight(1f))
                        LevelChip(l, sup)
                    }
                    Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0xFF2A2410)))
                }
                if (rows.isEmpty()) Text("—", color = TextDim)
            }
        }
    }
}

@Composable
internal fun H2Bottom(s: UiState, radarText: String, onRadar: () -> Unit, onRecord: () -> Unit) {
    GlowCard(Modifier.fillMaxWidth()) {
        Row(Modifier.height(IntrinsicSize.Min).padding(horizontal = 10.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Row(Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).clickable(role = Role.Button, onClick = onRadar),
                verticalAlignment = Alignment.CenterVertically) {
                Image(painterResource(R.drawable.hi_target), null, Modifier.size(34.dp))
                Spacer(Modifier.width(8.dp))
                Column {
                    Text(stringResource(R.string.rd_tile), color = Color.White, fontFamily = Cairo, fontWeight = FontWeight.ExtraBold,
                        fontSize = 15.sp, lineHeight = 18.sp, maxLines = 1)
                    Text(radarText, color = Color.White, fontFamily = Cairo, fontSize = 11.sp, lineHeight = 13.sp, maxLines = 1,
                        overflow = TextOverflow.Ellipsis)
                }
            }
            Box(Modifier.width(1.dp).fillMaxHeight().padding(vertical = 4.dp).background(Color(0xFF5A4A20)))
            Spacer(Modifier.width(8.dp))
            Row(Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).clickable(role = Role.Button, onClick = onRecord),
                verticalAlignment = Alignment.CenterVertically) {
                Image(painterResource(R.drawable.hi_record), null, Modifier.size(32.dp))
                Spacer(Modifier.width(8.dp))
                Column {
                    Text(stringResource(R.string.rec_title), color = Color.White, fontFamily = Cairo, fontWeight = FontWeight.ExtraBold,
                        fontSize = 16.sp, lineHeight = 19.sp, maxLines = 1)
                    Text(recordTile(s.briefs), color = H2Gold, fontFamily = Cairo, fontWeight = FontWeight.ExtraBold, fontSize = 13.sp,
                        lineHeight = 15.sp, maxLines = 1)
                }
            }
        }
    }
}

/** All supports and resistances of the selected horizon around the price, with distance, strength and an alert. */
@Composable
internal fun LevelsSheet(x: H2View, s: UiState, price: Double?, onBell: (PriceAlert) -> Unit, onLevel: (Level, Boolean) -> Unit,
                         onClose: () -> Unit) {
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false,
        securePolicy = SecureDialog.securePolicy)) {
        Box(Modifier.fillMaxSize().background(Color(0xA6000000)).clickable(onClick = onClose), contentAlignment = Alignment.BottomCenter) {
            val shape = RoundedCornerShape(topStart = 22.dp, topEnd = 22.dp)
            Column(Modifier.fillMaxWidth().shadow(16.dp, shape, ambientColor = H2Gold, spotColor = H2Gold)
                .background(Color(0xFF0A0A0A), shape).border(1.5.dp, EdgeBrush, shape).clickable(enabled = false) {}
                .verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 12.dp)) {
                Box(Modifier.align(Alignment.CenterHorizontally).size(width = 44.dp, height = 4.dp).background(Color(0xFF555555), RoundedCornerShape(4.dp)))
                Spacer(Modifier.height(10.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Image(painterResource(R.drawable.hi_levels), null, Modifier.size(28.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.h2_levels_title, horizonName(x.c.horizon)), color = H2Gold, fontFamily = Cairo,
                        fontWeight = FontWeight.ExtraBold, fontSize = 18.sp, modifier = Modifier.weight(1f))
                    Text("✕", color = TextDim, fontSize = 20.sp, modifier = Modifier.clickable(role = Role.Button, onClick = onClose).padding(6.dp))
                }
                Text(stringResource(R.string.h2_levels_hint), color = Color(0xFF9A9A9A), fontFamily = Cairo, fontSize = 12.sp)
                val res = x.c.levels?.resistances.orEmpty().sortedByDescending { it.price }
                val sup = x.c.levels?.supports.orEmpty().sortedByDescending { it.price }
                Text(stringResource(R.string.lv_resistances), color = Color(0xFFFF6B70), fontFamily = Cairo, fontWeight = FontWeight.ExtraBold,
                    fontSize = 14.sp, modifier = Modifier.padding(top = 8.dp))
                res.forEach { LevelRow(it, false, s, price, onBell, onLevel) }
                Text(stringResource(R.string.h2_now, ltr(price?.p2() ?: "—")), color = H2Gold, fontFamily = Cairo, fontSize = 13.sp,
                    fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp))
                Text(stringResource(R.string.lv_supports), color = Color(0xFF3CE07A), fontFamily = Cairo, fontWeight = FontWeight.ExtraBold,
                    fontSize = 14.sp)
                sup.forEach { LevelRow(it, true, s, price, onBell, onLevel) }
                Text(stringResource(R.string.h2_levels_foot), color = TextDim, fontFamily = Cairo, fontSize = 10.sp,
                    modifier = Modifier.padding(top = 8.dp))
            }
        }
    }
}

@Composable
private fun LevelRow(l: Level, support: Boolean, s: UiState, price: Double?, onBell: (PriceAlert) -> Unit,
                     onLevel: (Level, Boolean) -> Unit) {
    val col = if (support) Color(0xFF3CE07A) else Color(0xFFFF6B70)
    val on = PriceAlerts.isOn(s.priceAlerts, s.asset, l.price)
    val name = stringResource(if (support) R.string.lv_support else R.string.lv_resistance)
    Row(Modifier.fillMaxWidth().clickable { onLevel(l, support) }.padding(vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(stringResource(when {
                support && strong(l) -> R.string.h2_sup_strong; support -> R.string.h2_sup
                strong(l) -> R.string.h2_res_strong; else -> R.string.h2_res
            }), color = col, fontFamily = Cairo, fontWeight = FontWeight.Bold, fontSize = 13.sp, lineHeight = 15.sp)
            val n = ((l.strength?.div(20)) ?: minOf(5, l.tests)).coerceIn(0, 5)
            Row(horizontalArrangement = Arrangement.spacedBy(2.dp), modifier = Modifier.padding(top = 2.dp)) {
                repeat(5) { i -> Box(Modifier.size(7.dp).background(if (i < n) col else Color(0xFF333333), RoundedCornerShape(2.dp))) }
            }
        }
        Column(horizontalAlignment = Alignment.End) {
            Text(ltr(l.price.p2()), color = Color.White, fontFamily = Cairo, fontWeight = FontWeight.ExtraBold, fontSize = 17.sp, lineHeight = 19.sp)
            if (price != null && price > 0) {
                val d = (l.price - price) / price * 100
                Text(ltr((if (d >= 0) "+" else "−") + String.format(Locale.US, "%.1f%%", kotlin.math.abs(d))), color = Color(0xFF9A9A9A),
                    fontFamily = Cairo, fontSize = 11.sp, lineHeight = 13.sp)
            }
        }
        Spacer(Modifier.width(10.dp))
        Text("🔔 " + stringResource(if (on) R.string.h2_alert_on else R.string.h2_alert), color = if (on) Color.Black else H2Gold,
            fontFamily = Cairo, fontSize = 11.sp, fontWeight = FontWeight.Bold,
            modifier = Modifier.clip(RoundedCornerShape(16.dp)).background(if (on) H2Gold else Color.Transparent)
                .border(1.dp, Color(0xFF8A6A22), RoundedCornerShape(16.dp))
                .clickable(role = Role.Button) { onBell(PriceAlerts.make(s.asset, l.price, price, name + " " + l.price.p2())) }
                .padding(horizontal = 8.dp, vertical = 3.dp))
    }
}

/** One-line notice when hours and week lean opposite ways; tap for the full sentence. */
@Composable
internal fun H2Divergence(text: String?, onClick: () -> Unit) {
    if (text == null) return
    Text("⚠  " + stringResource(R.string.h2_frames_differ), color = Color(0xFFF0B45A), fontFamily = Cairo, fontSize = 12.sp,
        lineHeight = 14.sp, fontWeight = FontWeight.Bold, maxLines = 1, textAlign = TextAlign.Center,
        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Color(0xFF1D1708))
            .border(1.dp, Color(0xFF6B5A22), RoundedCornerShape(12.dp)).clickable(role = Role.Button, onClick = onClick)
            .padding(vertical = 4.dp))
}
