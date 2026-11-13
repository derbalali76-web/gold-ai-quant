package com.goldaiquant.app.ui

import androidx.compose.animation.Crossfade
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.goldaiquant.app.Action
import com.goldaiquant.app.ApiException
import com.goldaiquant.app.Decision
import com.goldaiquant.app.ErrorKind
import com.goldaiquant.app.HorizonCard
import com.goldaiquant.app.HorizonModel
import com.goldaiquant.app.Lang
import com.goldaiquant.app.Level
import com.goldaiquant.app.LevelRelation
import com.goldaiquant.app.MainViewModel
import com.goldaiquant.app.ProbState
import com.goldaiquant.app.R
import com.goldaiquant.app.Reason
import com.goldaiquant.app.ReasonStrings
import com.goldaiquant.app.ReasonText
import com.goldaiquant.app.Trend
import com.goldaiquant.app.UiState
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale

// ---------------------------------------------------------------- palette (black + restrained gold)
val Bg = Color(0xFF07070A)
val Card = Color(0xFF111014)
val CardEdge = Color(0xFF3A3018)
val Gold = Color(0xFFD4AF37)
val GoldLight = Color(0xFFF3D46B)
val TextMain = Color(0xFFF4F4F4)
val TextDim = Color(0xFFA3A3A8)
val BuyGreen = Color(0xFF2ECC71)
val SellRed = Color(0xFFE5484D)
val WaitGold = Color(0xFFE8B931)
val Grey = Color(0xFF6B6B70)
val Track = Color(0xFF2A2A30)

@Composable
fun GoldTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = darkColorScheme(primary = Gold, background = Bg, surface = Card,
        onPrimary = Color.Black, onBackground = TextMain, onSurface = TextMain), content = content)
}

private val clock = DateTimeFormatter.ofPattern("HH:mm:ss", Locale.US)
private fun Instant.hms(): String = clock.format(atZone(ZoneId.systemDefault()))
private fun Double.p2(): String = String.format(Locale.US, "%.2f", this)

/** Keeps numbers, signs and ranges in reading order inside any layout direction. */
fun ltr(s: String): String = "⁦$s⁩"

// ---------------------------------------------------------------- localized helpers (no visible text lives in code)
/** Resolves reason codes against this app's string resources; unknown codes fall back to the server's Arabic text. */
@Composable
private fun reasonStrings(): ReasonStrings {
    val ctx = LocalContext.current
    return remember(ctx.resources.configuration) {
        ReasonStrings { code ->
            val id = ctx.resources.getIdentifier(ReasonText.resourceName(code), "string", ctx.packageName)
            if (id == 0) null else ctx.getString(id)
        }
    }
}

@Composable
private fun rt(r: Reason?): String = if (r == null) "" else ReasonText.render(r, reasonStrings())

@Composable
private fun horizonName(h: String): String = stringResource(when (h) {
    "WEEK" -> R.string.h_week; "MONTH" -> R.string.h_month; else -> R.string.h_hours
})

@Composable
private fun actionTitle(a: Action): String = stringResource(when (a) {
    Action.BUY -> R.string.a_buy; Action.SELL -> R.string.a_sell
    Action.WAIT -> R.string.a_wait; Action.UNAVAILABLE -> R.string.a_unavailable
})

@Composable
private fun errorText(e: ApiException): String {
    val main = stringResource(when (e.kind) {
        ErrorKind.INVALID_URL -> R.string.err_invalid_url
        ErrorKind.HTTP_NOT_LOCAL -> R.string.err_http_not_local
        ErrorKind.BAD_SCHEME -> R.string.err_bad_scheme
        ErrorKind.TIMEOUT_WAKING -> R.string.err_timeout_waking
        ErrorKind.NO_CONNECTION -> R.string.err_no_connection
        ErrorKind.BAD_TOKEN -> R.string.err_bad_token
        ErrorKind.SERVER_STARTING -> R.string.err_server_starting
        ErrorKind.SERVER_ERROR -> R.string.err_server_error
        ErrorKind.TOO_LARGE -> R.string.err_too_large
        ErrorKind.INVALID_RESPONSE -> R.string.err_invalid_response
        ErrorKind.UNEXPECTED -> R.string.err_unexpected
    })
    return if (e.detail.isNullOrBlank()) main else main + "\n" + stringResource(R.string.err_detail, ltr(e.detail!!))
}

private enum class Health(val label: Int, val color: Color) {
    LIVE(R.string.health_live, BuyGreen), STALE(R.string.health_stale, WaitGold), DEMO(R.string.health_demo, WaitGold),
    NONE(R.string.health_none, SellRed), SAVED(R.string.health_saved, Grey)
}

private fun health(s: UiState): Health {
    val d = s.decision
    return when {
        s.error != null && d == null -> Health.NONE
        d == null -> Health.NONE
        s.decisionFromCache -> Health.SAVED
        d.isDemo -> Health.DEMO
        d.action == Action.UNAVAILABLE && d.quote == null -> Health.NONE
        !d.isFresh -> Health.STALE
        else -> Health.LIVE
    }
}

private fun actionColor(a: Action, tilt: Int): Color = when (a) {
    Action.BUY -> BuyGreen; Action.SELL -> SellRed; Action.UNAVAILABLE -> Grey
    Action.WAIT -> if (tilt != 0) WaitGold.copy(alpha = 0.85f) else WaitGold
}

// ---------------------------------------------------------------- screen
@Composable
fun GoldScreen(vm: MainViewModel, lang: Lang, onLanguage: (Lang) -> Unit) {
    val s by vm.state.collectAsStateWithLifecycle()
    GoldContent(s, lang, onAsk = vm::ask, onNextDemo = vm::nextDemoMoment,
        onSave = { u, t -> vm.setServerUrl(u); vm.setToken(t) }, onLive = vm::setLiveMode,
        onHorizon = vm::selectHorizon, onLanguage = onLanguage, onNotify = vm::setNotify)
}

private sealed interface Sheet {
    data class LevelSheet(val level: Level, val isSupport: Boolean) : Sheet
    data object Probabilities : Sheet
    data object TrendSheet : Sheet
    data object Details : Sheet
    data object Settings : Sheet
}

/** Stateless screen (also used by the UI tests on several screen sizes). */
@Composable
fun GoldContent(s: UiState, lang: Lang, onAsk: () -> Unit, onNextDemo: () -> Unit, onSave: (String, String) -> Unit,
                onLive: (Boolean) -> Unit, onHorizon: (String) -> Unit, onLanguage: (Lang) -> Unit,
                onNotify: (Boolean) -> Unit = {}) {
    var sheet by remember { mutableStateOf<Sheet?>(null) }
    val d = s.decision
    val selected = HorizonModel.resolve(s.selectedHorizon, d)
    BoxWithConstraints(Modifier.fillMaxSize().background(Bg).safeDrawingPadding()) {
        // Compact layout on short screens: secondary details are dropped instead of shrinking the text.
        val compact = maxHeight < 700.dp
        val gap = if (compact) 6.dp else 8.dp
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(gap),
        ) {
            TopBar(s, compact) { sheet = Sheet.Settings }
            val card = d?.let { HorizonModel.card(it, selected) }
            Row(horizontalArrangement = Arrangement.spacedBy(gap)) {
                PriceCard(d, s, Modifier.weight(1.1f))
                Crossfade(targetState = card?.trend, animationSpec = tween(220), modifier = Modifier.weight(1f),
                    label = "trend") { t -> TrendCard(t) { sheet = Sheet.TrendSheet } }
            }
            if (d?.isDemo == true) Text(stringResource(R.string.demo_banner),
                color = Color.Black, fontSize = 12.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().background(WaitGold, RoundedCornerShape(8.dp)).padding(vertical = 4.dp))
            AskButton(s.loading, compact, onAsk)
            s.error?.let { ErrorStrip(it, onAsk) }
            if (d != null && card != null) {
                HorizonsRow(d, selected, s.loading, gap, onHorizon)
                Crossfade(targetState = card, animationSpec = tween(240), label = "horizon") { c ->
                    Column(verticalArrangement = Arrangement.spacedBy(gap)) {
                        Row(horizontalArrangement = Arrangement.spacedBy(gap)) {
                            DecisionCard(c, s, d, compact, Modifier.weight(1.45f))
                            ProbabilityCard(c, d, Modifier.weight(1f)) { sheet = Sheet.Probabilities }
                        }
                        val lv = c.levels
                        Row(horizontalArrangement = Arrangement.spacedBy(gap)) {
                            LevelsCard(stringResource(R.string.lv_supports), BuyGreen, lv?.supports.orEmpty(),
                                lv?.validated == true, if (compact) 2 else 3, Modifier.weight(1f)) { sheet = Sheet.LevelSheet(it, true) }
                            LevelsCard(stringResource(R.string.lv_resistances), SellRed, lv?.resistances.orEmpty(),
                                lv?.validated == true, if (compact) 2 else 3, Modifier.weight(1f)) { sheet = Sheet.LevelSheet(it, false) }
                        }
                        ReasonCard(c) { sheet = Sheet.Details }
                    }
                }
            } else if (s.error == null) {
                Text(stringResource(R.string.prompt_ask), color = TextDim, fontSize = 14.sp,
                    textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(16.dp))
            }
            Text(stringResource(R.string.footer_disclaimer), color = TextDim, fontSize = 10.sp,
                textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        }
    }
    val card = d?.let { HorizonModel.card(it, selected) }
    when (val sh = sheet) {
        is Sheet.LevelSheet -> if (card != null) LevelDialog(sh.level, sh.isSupport, card) { sheet = null }
        Sheet.Probabilities -> if (card != null && d != null) ProbabilityDialog(card, d) { sheet = null }
        Sheet.TrendSheet -> if (card != null) TrendDialog(card) { sheet = null }
        Sheet.Details -> if (card != null && d != null) DetailsDialog(card, d) { sheet = null }
        Sheet.Settings -> SettingsDialog(s, lang, onNextDemo, onSave, onLive, onLanguage, onNotify) { sheet = null }
        null -> Unit
    }
}

// ---------------------------------------------------------------- building blocks
@Composable
private fun Panel(modifier: Modifier = Modifier, edge: Color = CardEdge, onClick: (() -> Unit)? = null,
                  content: @Composable () -> Unit) {
    val shape = RoundedCornerShape(14.dp)
    val base = modifier.background(Card, shape).border(1.dp, edge, shape)
    val m = if (onClick != null) base.clickable(role = Role.Button, onClick = onClick) else base
    Box(m.padding(horizontal = 10.dp, vertical = 8.dp)) { content() }
}

@Composable
private fun Bar(fraction: Float, color: Color, modifier: Modifier = Modifier, height: Dp = 6.dp) {
    val f by animateFloatAsState(fraction.coerceIn(0f, 1f), tween(450), label = "bar")
    Box(modifier.height(height).background(Track, RoundedCornerShape(50))) {
        Box(Modifier.fillMaxHeight().fillMaxWidth(f).background(color, RoundedCornerShape(50)))
    }
}

@Composable
private fun TopBar(s: UiState, compact: Boolean, onSettings: () -> Unit) {
    val h = health(s)
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Row(Modifier.border(1.dp, h.color, RoundedCornerShape(50)).padding(horizontal = 8.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).background(h.color, CircleShape))
            Spacer(Modifier.width(5.dp))
            Text(stringResource(h.label), color = TextMain, fontSize = 11.sp, maxLines = 1)
        }
        Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
            Text("GOLD AI QUANT", color = Gold, fontWeight = FontWeight.ExtraBold, fontSize = 18.sp, maxLines = 1)
            if (!compact) Text(stringResource(R.string.tagline), color = TextDim, fontSize = 10.sp)
        }
        val cd = stringResource(R.string.cd_settings)
        Box(Modifier.size(40.dp).border(1.dp, Gold, CircleShape)
            .clickable(role = Role.Button, onClick = onSettings).semantics { contentDescription = cd },
            contentAlignment = Alignment.Center) { Text("⚙", color = Gold, fontSize = 18.sp) }
    }
}

@Composable
private fun PriceCard(d: Decision?, s: UiState, modifier: Modifier) {
    Panel(modifier) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
            Text("XAU/USD", color = TextDim, fontSize = 12.sp)
            Text(d?.quote?.p2() ?: "—", color = TextMain, fontSize = 28.sp, fontWeight = FontWeight.Bold, maxLines = 1)
            val ch = d?.quoteChange
            if (ch != null) {
                val up = ch >= 0
                val pct = d?.quoteChangePct?.let { " (${if (up) "+" else ""}${String.format(Locale.US, "%.2f", it)}%)" } ?: ""
                Text(ltr("${if (up) "+" else ""}${ch.p2()}$pct ${if (up) "▲" else "▼"}"),
                    color = if (up) BuyGreen else SellRed, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            }
            val t = d?.quoteTime ?: s.receivedAt
            Text(stringResource(R.string.updated_at, ltr(t?.hms() ?: "—")), color = TextDim, fontSize = 10.sp, maxLines = 1)
        }
    }
}

@Composable
private fun trendLabel(dir: String?): String = stringResource(when (dir) {
    "UP" -> R.string.tr_up; "DOWN" -> R.string.tr_down; "SIDEWAYS" -> R.string.tr_sideways; else -> R.string.tr_unknown
})

private fun trendColor(dir: String?): Color = when (dir) {
    "UP" -> BuyGreen; "DOWN" -> SellRed; "SIDEWAYS" -> WaitGold; else -> Grey
}

@Composable
private fun TrendCard(t: Trend?, onClick: () -> Unit) {
    val color = trendColor(t?.direction)
    Panel(Modifier.fillMaxWidth(), onClick = onClick) {
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(stringResource(R.string.tr_title), color = TextMain, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            Text(if (t == null) "—" else trendLabel(t.direction), color = color, fontSize = 22.sp,
                fontWeight = FontWeight.ExtraBold, maxLines = 1)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.tr_strength), color = TextDim, fontSize = 11.sp, modifier = Modifier.weight(1f))
                Text(t?.strength?.let { ltr("$it/100") } ?: "—", color = TextMain, fontSize = 12.sp, fontWeight = FontWeight.Bold)
            }
            Bar((t?.strength ?: 0) / 100f, color, Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun AskButton(loading: Boolean, compact: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(40.dp)
    val cd = stringResource(R.string.ask)
    Box(Modifier.fillMaxWidth().height(if (compact) 60.dp else 70.dp)
        .background(Brush.verticalGradient(listOf(GoldLight, Gold, Color(0xFFB8901F))), shape)
        .border(1.dp, GoldLight, shape).clickable(enabled = !loading, role = Role.Button, onClick = onClick)
        .semantics { contentDescription = cd }, contentAlignment = Alignment.Center) {
        if (loading) Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(color = Color.Black, strokeWidth = 3.dp, modifier = Modifier.size(24.dp))
            Spacer(Modifier.width(10.dp))
            Text(stringResource(R.string.asking), color = Color.Black, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        } else Row(verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.ask), color = Color.Black, fontSize = if (compact) 25.sp else 28.sp,
                fontWeight = FontWeight.ExtraBold, maxLines = 1)
            Spacer(Modifier.width(12.dp))
            Canvas(Modifier.size(30.dp)) { // crosshair icon
                val c = Offset(size.width / 2, size.height / 2)
                drawCircle(Color.Black, radius = size.minDimension * 0.36f, center = c, style = Stroke(3.dp.toPx()))
                drawCircle(Color.Black, radius = size.minDimension * 0.10f, center = c)
                val r = size.minDimension / 2
                drawLine(Color.Black, Offset(c.x, 0f), Offset(c.x, c.y - r * 0.5f), 3.dp.toPx())
                drawLine(Color.Black, Offset(c.x, size.height), Offset(c.x, c.y + r * 0.5f), 3.dp.toPx())
                drawLine(Color.Black, Offset(0f, c.y), Offset(c.x - r * 0.5f, c.y), 3.dp.toPx())
                drawLine(Color.Black, Offset(size.width, c.y), Offset(c.x + r * 0.5f, c.y), 3.dp.toPx())
            }
        }
    }
}

@Composable
private fun ErrorStrip(e: ApiException, onRetry: () -> Unit) {
    Row(Modifier.fillMaxWidth().background(SellRed.copy(alpha = 0.22f), RoundedCornerShape(10.dp)).padding(8.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(errorText(e), color = TextMain, fontSize = 13.sp, modifier = Modifier.weight(1f))
        TextButton(onClick = onRetry) { Text(stringResource(R.string.err_retry), color = Gold) }
    }
}

@Composable
private fun KV(k: String, v: String, size: TextUnit = 13.sp) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(k, color = TextDim, fontSize = 12.sp, modifier = Modifier.weight(1f), maxLines = 2)
        Spacer(Modifier.width(6.dp))
        Text(v, color = TextMain, fontSize = size, fontWeight = FontWeight.SemiBold, maxLines = 1)
    }
}

// ---------------------------------------------------------------- horizons (tap = the whole screen switches)
@Composable
private fun HorizonsRow(d: Decision, current: String, loading: Boolean, gap: Dp, onSelect: (String) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(gap)) {
        HorizonModel.ORDER.forEach { h ->
            val o = d.outlooks.firstOrNull { it.horizon == h }
            val action = o?.action ?: Action.UNAVAILABLE
            val isSel = h == current
            val c = actionColor(action, o?.tilt ?: 0)
            val edge by animateColorAsState(if (isSel) Gold else c.copy(alpha = 0.45f), tween(220), label = "edge")
            val glow by animateDpAsState(if (isSel) 10.dp else 0.dp, tween(220), label = "glow")
            val shape = RoundedCornerShape(14.dp)
            val name = horizonName(h)
            val cd = if (isSel) stringResource(R.string.cd_horizon_selected, name) else stringResource(R.string.cd_horizon, name)
            Box(Modifier.weight(1f).heightIn(min = 64.dp)
                .shadow(glow, shape, ambientColor = Gold, spotColor = Gold)
                .background(Card, shape).border(if (isSel) 2.dp else 1.dp, edge, shape)
                .clickable(role = Role.Tab) { onSelect(h) }
                .semantics { contentDescription = cd; selected = isSel }
                .padding(horizontal = 6.dp, vertical = 6.dp), contentAlignment = Alignment.Center) {
                Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(name, color = if (isSel) Gold else TextDim, fontSize = 11.sp,
                        fontWeight = if (isSel) FontWeight.Bold else FontWeight.Normal)
                    Text(if (o == null) stringResource(R.string.a_unavailable) else actionTitle(action), color = c, fontSize = 15.sp,
                        fontWeight = FontWeight.ExtraBold, maxLines = 1, textAlign = TextAlign.Center)
                    val hr = o?.hitRate
                    val status = when {
                        loading -> stringResource(R.string.hz_updating)
                        o != null && hr != null -> ltr("${Math.round(hr * 100)}% / ${o.samples}")
                        o?.validated == true -> stringResource(R.string.hz_validated)
                        o == null || action == Action.UNAVAILABLE -> stringResource(R.string.hz_no_data)
                        else -> stringResource(R.string.hz_not_validated)
                    }
                    Text(status, color = if (o?.validated == true && !loading) BuyGreen else TextDim, fontSize = 10.sp, maxLines = 1)
                }
            }
        }
    }
}

// ---------------------------------------------------------------- main card (per selected horizon)
@Composable
private fun durationText(c: HorizonCard): String {
    val m = c.durationMinutes
    val days = c.durationDays
    return when {
        m != null && m % 60 == 0 -> stringResource(R.string.dur_hours, m / 60)
        m != null -> stringResource(R.string.dur_minutes, m)
        days != null -> stringResource(R.string.dur_days, days)
        else -> "—"
    }
}

@Composable
private fun DecisionCard(c: HorizonCard, s: UiState, d: Decision, compact: Boolean, modifier: Modifier) {
    val expired = d.isExpired(Instant.now())
    val color = actionColor(c.action, c.tilt)
    val sub = when (c.action) {
        Action.BUY, Action.SELL -> stringResource(if (c.horizon == "HOURS") R.string.sub_court else R.string.sub_validated_rule)
        Action.WAIT -> if (c.stance != null && c.tilt != 0) rt(c.stance) else stringResource(R.string.sub_wait)
        Action.UNAVAILABLE -> stringResource(R.string.sub_unavailable)
    }
    Panel(modifier, edge = color) {
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(actionTitle(c.action), color = color, fontSize = if (c.action == Action.UNAVAILABLE) 22.sp else 30.sp,
                    fontWeight = FontWeight.Black, maxLines = 1)
                Spacer(Modifier.width(8.dp))
                Text(sub, color = TextDim, fontSize = 11.sp, maxLines = 2)
            }
            Text(horizonName(c.horizon), color = Gold, fontSize = 11.sp)
            if (s.decisionFromCache || expired) Text(stringResource(R.string.saved_decision), color = WaitGold, fontSize = 11.sp)
            when (c.action) {
                Action.BUY, Action.SELL -> {
                    val approx = if (c.horizon == "HOURS") "" else " ${stringResource(R.string.approx)}"
                    if (c.horizon == "HOURS") KV(stringResource(R.string.l_entry), ltr("${c.entryLow!!.p2()} – ${c.entryHigh!!.p2()}"))
                    else KV(stringResource(R.string.l_ref_price), c.entryLow!!.p2())
                    KV(stringResource(R.string.l_stop) + approx, c.stop!!.p2())
                    KV(stringResource(R.string.l_target) + approx, c.target!!.p2())
                    KV(stringResource(R.string.l_duration), durationText(c))
                }
                Action.WAIT -> {
                    c.waitForPrice?.let { KV(stringResource(R.string.l_reeval), it.p2()) }
                    if (c.horizon == "HOURS") d.reevaluateRefs.take(if (compact) 1 else 2).forEach {
                        Text("• ${rt(it)}", color = TextMain, fontSize = 11.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                }
                Action.UNAVAILABLE -> Text(rt(c.warnings.firstOrNull() ?: c.reason), color = TextMain, fontSize = 12.sp, maxLines = 3)
            }
        }
    }
}

// ---------------------------------------------------------------- probabilities (tap = explanation)
@Composable
private fun probNote(c: HorizonCard): String = stringResource(when (c.probState) {
    ProbState.DEMO -> R.string.prob_demo
    ProbState.NOT_CALIBRATED -> R.string.prob_not_cal
    ProbState.HORIZON_UNSUPPORTED -> R.string.prob_horizon
    else -> R.string.prob_not_cal
})

@Composable
private fun ProbabilityCard(c: HorizonCard, d: Decision, modifier: Modifier, onClick: () -> Unit) {
    Panel(modifier, onClick = onClick) {
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.prob_title), color = TextMain, fontSize = 13.sp, fontWeight = FontWeight.Bold)
            val o = c.outcomes
            if (c.probState != ProbState.AVAILABLE || o == null) {
                Text(stringResource(R.string.prob_na), color = WaitGold, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                Text(probNote(c), color = TextDim, fontSize = 11.sp)
            } else {
                ProbRow(stringResource(R.string.prob_target), o.target, BuyGreen)
                ProbRow(stringResource(R.string.prob_stop), o.stop, SellRed)
                ProbRow(stringResource(R.string.prob_neither), o.neither, Color(0xFFB8BCC4))
                Text(stringResource(R.string.prob_samples, o.samples), color = TextDim, fontSize = 9.sp)
            }
            Text(liveLine(c), color = TextDim, fontSize = 10.sp)
        }
    }
}

@Composable
private fun liveLine(c: HorizonCard): String =
    if (c.liveResolved > 0) stringResource(R.string.live_record, c.liveHits, c.liveResolved)
    else stringResource(R.string.live_none)

@Composable
private fun ProbRow(label: String, p: Double, color: Color) {
    Column {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, color = TextDim, fontSize = 11.sp, modifier = Modifier.weight(1f))
            Text("${Math.round(p * 100)}%", color = color, fontSize = 15.sp, fontWeight = FontWeight.Bold)
        }
        Bar(p.toFloat(), color, Modifier.fillMaxWidth(), 5.dp)
    }
}

// ---------------------------------------------------------------- levels (tap a level = detail dialog)
private fun labelFill(l: Level): Float = l.strength?.let { it / 100f } ?: when {
    l.tests >= 5 -> 0.85f; l.tests >= 3 -> 0.55f; l.tests >= 1 -> 0.25f; else -> 0f
}

@Composable
private fun LevelsCard(title: String, color: Color, items: List<Level>, validated: Boolean, rows: Int, modifier: Modifier,
                       onOpen: (Level) -> Unit) {
    Panel(modifier, edge = color.copy(alpha = 0.6f)) {
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(title, color = color, fontSize = 15.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                if (!validated) Text(stringResource(R.string.lv_estimated), color = TextDim, fontSize = 9.sp)
            }
            if (items.isEmpty()) Text(stringResource(R.string.lv_none), color = TextDim, fontSize = 11.sp)
            items.take(rows).forEach { l ->
                Row(Modifier.fillMaxWidth().heightIn(min = 40.dp).clickable(role = Role.Button) { onOpen(l) },
                    verticalAlignment = Alignment.CenterVertically) {
                    Text(l.name, color = color, fontSize = 12.sp, fontWeight = FontWeight.Bold, modifier = Modifier.width(26.dp))
                    Text(l.price.p2(), color = TextMain, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.weight(1f))
                    Column(horizontalAlignment = Alignment.End, modifier = Modifier.width(54.dp)) {
                        Text(l.strength?.let { "$it" } ?: stringResource(strengthWord(l)), color = TextDim, fontSize = 10.sp, maxLines = 1)
                        Segments(labelFill(l), color)
                    }
                }
            }
        }
    }
}

private fun strengthWord(l: Level): Int = when {
    l.tests >= 5 -> R.string.lv_word_strong; l.tests >= 3 -> R.string.lv_word_medium; else -> R.string.lv_word_weak
}

@Composable
private fun Segments(fill: Float, color: Color) {
    val n = (fill * 6 + 0.5f).toInt().coerceIn(0, 6)
    Row(horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        repeat(6) { i -> Box(Modifier.size(width = 6.dp, height = 7.dp)
            .background(if (i < n) color else Track, RoundedCornerShape(2.dp))) }
    }
}

// ---------------------------------------------------------------- reason card
@Composable
private fun ReasonCard(c: HorizonCard, onDetails: () -> Unit) {
    Panel(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(stringResource(R.string.reason_title), color = Gold, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                Text(rt(c.reason ?: c.warnings.firstOrNull()), color = TextMain, fontSize = 13.sp, lineHeight = 18.sp,
                    maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
            Spacer(Modifier.width(8.dp))
            Box(Modifier.heightIn(min = 44.dp).border(1.dp, Gold, RoundedCornerShape(20.dp))
                .clickable(role = Role.Button, onClick = onDetails).padding(horizontal = 12.dp, vertical = 8.dp),
                contentAlignment = Alignment.Center) {
                Text(stringResource(R.string.details) + " ⌄", color = TextMain, fontSize = 13.sp)
            }
        }
    }
}

// ---------------------------------------------------------------- dialogs (in-screen, no extra pages)
@Composable
private fun DialogFrame(title: String, onClose: () -> Unit, content: @Composable () -> Unit) {
    Dialog(onDismissRequest = onClose) {
        Column(Modifier.fillMaxWidth().heightIn(max = 620.dp).background(Card, RoundedCornerShape(16.dp))
            .border(1.dp, Gold, RoundedCornerShape(16.dp)).verticalScroll(rememberScrollState()).padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Text(title, color = Gold, fontSize = 17.sp, fontWeight = FontWeight.Bold)
            content()
            TextButton(onClick = onClose, modifier = Modifier.align(Alignment.End)) {
                Text(stringResource(R.string.close), color = Gold)
            }
        }
    }
}

@Composable
private fun Section(t: String) = Text(t, color = Gold, fontSize = 13.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 4.dp))

@Composable
private fun Body(t: String, color: Color = TextMain, size: TextUnit = 12.sp) = Text(t, color = color, fontSize = size)

@Composable
private fun LevelDialog(l: Level, isSupport: Boolean, c: HorizonCard, onClose: () -> Unit) {
    val color = if (isSupport) BuyGreen else SellRed
    val locale = LocalConfiguration.current.locales[0]
    val fmt = remember(locale) { DateTimeFormatter.ofLocalizedDateTime(FormatStyle.MEDIUM).withLocale(locale) }
    DialogFrame("${l.name} · ${stringResource(if (isSupport) R.string.lv_support else R.string.lv_resistance)}", onClose) {
        Text(l.price.p2(), color = color, fontSize = 26.sp, fontWeight = FontWeight.Black)
        KV(stringResource(R.string.lv_zone), ltr("${l.zoneLow.p2()} – ${l.zoneHigh.p2()}"))
        // strength only when the engine validated it; otherwise it is explicitly "not validated"
        KV(stringResource(R.string.lv_strength), l.strength?.let { stringResource(R.string.lv_strength_val, it) }
            ?: stringResource(R.string.lv_not_validated))
        KV(stringResource(R.string.lv_tests), "${l.tests}")
        KV(stringResource(R.string.lv_last_test), l.lastTest?.let { ltr(fmt.format(it.atZone(ZoneId.systemDefault()))) } ?: "—")
        KV(stringResource(R.string.lv_timeframes), ltr(l.timeframes.joinToString(" / ").ifEmpty { "—" }))
        Section(stringResource(R.string.lv_why))
        Body(stringResource(R.string.lv_why_tests, l.tests))
        if (l.roleFlip) Body(stringResource(R.string.lv_why_flip))
        if (l.brokenRecently) Body(stringResource(R.string.lv_why_broken), WaitGold)
        if (l.timeframes == listOf("D1")) Body(stringResource(R.string.lv_why_daily))
        Section(stringResource(R.string.rel_title))
        val rel = com.goldaiquant.app.HorizonModel.relation(l, isSupport, c)
        Body(stringResource(when (rel) {
            LevelRelation.OBSTACLE_BEFORE_TARGET -> R.string.rel_obstacle
            LevelRelation.PROTECTS_STOP -> R.string.rel_protects
            LevelRelation.STOP_INSIDE_ZONE -> R.string.rel_stop_inside
            LevelRelation.NOT_IN_PATH -> R.string.rel_not_in_path
            LevelRelation.NO_TRADE_CONTEXT -> R.string.rel_no_trade
        }), if (rel == LevelRelation.OBSTACLE_BEFORE_TARGET || rel == LevelRelation.STOP_INSIDE_ZONE) WaitGold else TextMain)
        Body(stringResource(R.string.lv_method), TextDim, 11.sp)
    }
}

@Composable
private fun ProbabilityDialog(c: HorizonCard, d: Decision, onClose: () -> Unit) {
    DialogFrame(stringResource(R.string.prob_dialog_title) + " · " + horizonName(c.horizon), onClose) {
        Body(stringResource(R.string.prob_expl_what))
        Body(stringResource(R.string.prob_expl_horizon))
        Body(stringResource(R.string.prob_expl_cal), TextDim, 11.sp)
        val o = c.outcomes
        if (c.probState == ProbState.AVAILABLE && o != null) {
            Section(stringResource(R.string.prob_title))
            ProbRow(stringResource(R.string.prob_target), o.target, BuyGreen)
            ProbRow(stringResource(R.string.prob_stop), o.stop, SellRed)
            ProbRow(stringResource(R.string.prob_neither), o.neither, Color(0xFFB8BCC4))
            Body(stringResource(R.string.prob_samples, o.samples), TextDim, 11.sp)
            d.horizonProbs.forEach {
                Body(stringResource(R.string.prob_by_horizon, it.minutes, (it.pTarget * 100).toInt(), (it.pStop * 100).toInt(),
                    (it.pNeither * 100).toInt()), TextMain, 11.sp)
            }
        } else {
            Section(stringResource(R.string.prob_na))
            Body(stringResource(R.string.prob_expl_why_na, probNote(c)), WaitGold)
            if (c.hitRate != null && c.baseRate != null) {
                Section(stringResource(R.string.sec_validation))
                Body(stringResource(R.string.prob_hist, Math.round(c.hitRate * 100), c.samples, Math.round(c.baseRate * 100)))
            }
        }
        Section(stringResource(R.string.live_title))
        Body(liveLine(c))
        if (c.liveResolved < 30) Body(stringResource(R.string.live_few), WaitGold, 11.sp)
        Body(stringResource(R.string.live_expl), TextDim, 11.sp)
        if (c.horizon == "HOURS") Body(stringResource(R.string.live_hours_note), TextDim, 11.sp)
    }
}

@Composable
private fun frameName(k: String): String {
    val id = when (k) {
        "M15" -> R.string.tf_m15; "M30" -> R.string.tf_m30; "H1" -> R.string.tf_h1; "H4" -> R.string.tf_h4; "D1" -> R.string.tf_d1
        "SMA20" -> R.string.tf_sma20; "SMA50" -> R.string.tf_sma50; "SMA200" -> R.string.tf_sma200
        "MOM3M" -> R.string.tf_mom3; "MOM6M" -> R.string.tf_mom6; "MOM12M" -> R.string.tf_mom12
        else -> 0
    }
    return if (id == 0) k else stringResource(id)
}

@Composable
private fun TrendDialog(c: HorizonCard, onClose: () -> Unit) {
    val t = c.trend
    DialogFrame(stringResource(R.string.tr_dialog) + " · " + horizonName(c.horizon), onClose) {
        if (t == null) { Body(stringResource(R.string.tr_none)); return@DialogFrame }
        Text(trendLabel(t.direction), color = trendColor(t.direction), fontSize = 24.sp, fontWeight = FontWeight.Black)
        KV(stringResource(R.string.tr_strength), t.strength?.let { ltr("$it/100") } ?: "—")
        t.agreement?.let { KV(stringResource(R.string.tr_agreement), ltr("${Math.round(it * 100)}%")) }
        Section(stringResource(R.string.tr_frames))
        t.perTimeframe.entries.forEach { e ->
            Row(Modifier.fillMaxWidth()) {
                Text(frameName(e.key), color = TextDim, fontSize = 12.sp, modifier = Modifier.weight(1f))
                Text(trendLabel(e.value), color = trendColor(e.value), fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            }
        }
        if (c.facts.isNotEmpty()) {
            Section(stringResource(R.string.tr_factors))
            c.facts.forEach { Body("• ${rt(it)}", TextMain, 11.sp) }
        }
        Section(stringResource(R.string.tr_reason))
        Body(rt(c.reason))
        Body(stringResource(R.string.tr_score_note), TextDim, 11.sp)
    }
}

@Composable
private fun DetailsDialog(c: HorizonCard, d: Decision, onClose: () -> Unit) {
    DialogFrame(stringResource(R.string.details_dialog) + " · " + horizonName(c.horizon), onClose) {
        Section(stringResource(R.string.reason_title))
        Body(rt(c.reason))
        // trend
        c.trend?.let { t ->
            Section(stringResource(R.string.sec_trend))
            Body("${trendLabel(t.direction)} · ${t.strength?.let { "$it/100" } ?: "—"}")
            val perTf = t.perTimeframe.entries.map { frameName(it.key) + ": " + trendLabel(it.value) }
            Body(perTf.joinToString("  "), TextDim, 11.sp)
        }
        // levels
        c.levels?.let { lv ->
            Section(stringResource(R.string.sec_levels))
            (lv.supports + lv.resistances).forEach { l ->
                Body("${l.name}: ${ltr("${l.zoneLow.p2()}–${l.zoneHigh.p2()}")} · " +
                    (l.strength?.let { stringResource(R.string.lv_strength_val, it) } ?: stringResource(strengthWord(l))) +
                    " · ${stringResource(R.string.lv_tests)} ${l.tests}", TextMain, 11.sp)
            }
            Body(stringResource(R.string.lv_method), TextDim, 11.sp)
        }
        // volatility (intraday horizon only: it is an intraday measurement)
        if (c.horizon == "HOURS") d.volRegime?.let {
            Section(stringResource(R.string.sec_vol))
            Body(stringResource(when (it) {
                "STRONG_TREND" -> R.string.vol_strong_trend; "RANGE" -> R.string.vol_range
                "HIGH_VOL" -> R.string.vol_high; "EXCEPTIONAL" -> R.string.vol_exceptional; else -> R.string.vol_unknown
            }))
        }
        // risk
        if (c.horizon == "HOURS" && (d.rewardRisk != null || d.estimatedCost != null)) {
            Section(stringResource(R.string.sec_risk))
            d.rewardRisk?.let { KV(stringResource(R.string.risk_rr), it.p2()) }
            d.estimatedCost?.let { KV(stringResource(R.string.risk_cost), it.p2()) }
            d.expectedNetReturn?.let { KV(stringResource(R.string.risk_exp), it.p2()) }
            d.uncertaintyOverall?.let {
                KV(stringResource(R.string.risk_unc), stringResource(when (it) {
                    "LOW" -> R.string.unc_low; "MEDIUM" -> R.string.unc_medium; else -> R.string.unc_high
                }))
            }
        }
        if (c.horizon != "HOURS") {
            Section(stringResource(R.string.sec_validation))
            Body(rt(c.validation), if (c.validated) BuyGreen else WaitGold)
            if (c.hitRate != null && c.baseRate != null)
                Body(stringResource(R.string.prob_hist, Math.round(c.hitRate * 100), c.samples, Math.round(c.baseRate * 100)), TextMain, 11.sp)
            if (c.facts.isNotEmpty()) {
                Section(stringResource(R.string.sec_facts))
                c.facts.forEach { Body("• ${rt(it)}", TextMain, 11.sp) }
            }
        }
        // engine agreement + accept / reject reasons (intraday engines)
        if (c.horizon == "HOURS") {
            if (d.court.isNotEmpty()) {
                Section(stringResource(R.string.sec_engines))
                d.court.forEach { j ->
                    val name = stringResource(when (j.judge) {
                        "evidence" -> R.string.court_evidence; "statistics" -> R.string.court_statistics; else -> R.string.court_risk
                    })
                    Body("${if (j.passed) "✔" else "✖"} $name" + (j.reasons.firstOrNull()?.let { ": ${rt(it)}" } ?: ""),
                        if (j.passed) BuyGreen else SellRed)
                }
                Body(stringResource(R.string.eng_support, d.supporting.size, d.contrary.size), TextDim, 11.sp)
            }
            if (d.supporting.isNotEmpty()) {
                Section(stringResource(R.string.sec_accept))
                d.supporting.forEach { Body("✔ ${rt(it.reason)}", BuyGreen) }
            }
            if (d.contrary.isNotEmpty() || d.court.any { !it.passed }) {
                Section(stringResource(R.string.sec_reject))
                d.contrary.forEach { Body("✖ ${rt(it.reason)}", SellRed) }
                d.court.filter { !it.passed }.forEach { j -> j.reasons.forEach { Body("✖ ${rt(it)}", SellRed) } }
            }
            if (d.reevaluateRefs.isNotEmpty()) {
                Section(stringResource(R.string.sec_reeval))
                d.reevaluateRefs.forEach { Body("• ${rt(it)}", TextMain) }
            }
            d.alternativeEntryNote?.let { Body(rt(it), TextDim, 11.sp) }
        }
        if (c.warnings.isNotEmpty()) {
            Section(stringResource(R.string.sec_warnings))
            c.warnings.forEach { Body("• ${rt(it)}", TextMain) }
        }
        if (d.missingRefs.isNotEmpty()) {
            Section(stringResource(R.string.sec_missing))
            d.missingRefs.forEach { Body("• ${rt(it)}", TextDim, 11.sp) }
        }
        Body(ltr("${d.provider} · ${d.quoteTime?.hms() ?: "—"} · ${d.modelVersion} · ${d.decisionId}"), TextDim, 10.sp)
    }
}

@Composable
private fun SettingsDialog(s: UiState, lang: Lang, onNextDemo: () -> Unit, onSave: (String, String) -> Unit,
                           onLive: (Boolean) -> Unit, onLanguage: (Lang) -> Unit, onNotify: (Boolean) -> Unit,
                           onClose: () -> Unit) {
    val askPermission = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) { granted -> onNotify(granted) }
    Dialog(onDismissRequest = onClose) {
        Column(Modifier.fillMaxWidth().heightIn(max = 640.dp).background(Card, RoundedCornerShape(16.dp))
            .border(1.dp, Gold, RoundedCornerShape(16.dp)).verticalScroll(rememberScrollState()).padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(stringResource(R.string.set_title), color = Gold, fontSize = 17.sp, fontWeight = FontWeight.Bold)
            Text(stringResource(R.string.set_language), color = TextDim, fontSize = 12.sp)
            Lang.entries.forEach { l ->
                Row(Modifier.fillMaxWidth().heightIn(min = 44.dp).clickable(role = Role.RadioButton) {
                    if (l != lang) { onClose(); onLanguage(l) }
                }, verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = l == lang, onClick = null)
                    Spacer(Modifier.width(8.dp))
                    Text(l.nativeName, color = TextMain, fontSize = 15.sp)
                }
            }
            var url by remember(s.serverUrl) { mutableStateOf(s.serverUrl) }
            var tok by remember(s.token) { mutableStateOf(s.token) }
            OutlinedTextField(value = url, onValueChange = { url = it }, singleLine = true,
                label = { Text(stringResource(R.string.set_server)) }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(value = tok, onValueChange = { tok = it }, singleLine = true,
                label = { Text(stringResource(R.string.set_token)) }, modifier = Modifier.fillMaxWidth())
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.set_live), color = TextMain, fontSize = 14.sp, modifier = Modifier.weight(1f))
                Switch(checked = s.liveMode, onCheckedChange = onLive)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.set_notify), color = TextMain, fontSize = 14.sp, modifier = Modifier.weight(1f))
                Switch(checked = s.notify, onCheckedChange = { on ->
                    if (on && android.os.Build.VERSION.SDK_INT >= 33) askPermission.launch(android.Manifest.permission.POST_NOTIFICATIONS)
                    else onNotify(on)
                })
            }
            Text(stringResource(R.string.set_notify_note), color = TextDim, fontSize = 11.sp)
            if (!s.liveMode) TextButton(onClick = { onNextDemo(); onClose() }) {
                Text(stringResource(R.string.set_demo_next, s.demoStep + 1), color = TextDim)
            }
            Row {
                TextButton(onClick = { onSave(url, tok); onClose() }) { Text(stringResource(R.string.save), color = Gold) }
                TextButton(onClick = onClose) { Text(stringResource(R.string.cancel), color = TextDim) }
            }
        }
    }
}
