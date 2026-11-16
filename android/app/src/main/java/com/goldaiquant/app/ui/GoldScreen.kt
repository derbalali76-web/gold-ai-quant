package com.goldaiquant.app.ui

import androidx.lifecycle.repeatOnLifecycle
import com.goldaiquant.app.CalendarInfo
import com.goldaiquant.app.Candles
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import com.goldaiquant.app.PriceAlerts
import com.goldaiquant.app.PriceAlert
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.SecureFlagPolicy
import com.goldaiquant.app.InstallCode
import com.goldaiquant.app.LocalWatermark
import com.goldaiquant.app.watermark
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
import androidx.compose.foundation.layout.IntrinsicSize
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
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
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
import com.goldaiquant.app.TrackItem
import com.goldaiquant.app.Plan
import com.goldaiquant.app.Brief
import com.goldaiquant.app.SourceStatus
import com.goldaiquant.app.Scenario
import com.goldaiquant.app.Check
import com.goldaiquant.app.Perf
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
import com.goldaiquant.app.Trust
import com.goldaiquant.app.RangeTrack
import com.goldaiquant.app.RangeInfo
import com.goldaiquant.app.BriefRow
import com.goldaiquant.app.RecStatus
import com.goldaiquant.app.Record
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import com.goldaiquant.app.DataHealth
import com.goldaiquant.app.TrustLedger
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
val Teal = Color(0xFF3BA6A0)
private const val CHART_BARS = 120
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
private fun Double.p0(): String = String.format(Locale.US, "%.0f", this)

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
    NONE(R.string.health_none, SellRed), SAVED(R.string.health_saved, Grey),
    PARTIAL(R.string.health_partial, WaitGold), CLOSED(R.string.health_closed, Grey)
}

private fun health(s: UiState): Health {
    val d = s.decision
    return when {
        s.error != null && d == null -> Health.NONE
        d == null -> Health.NONE
        s.decisionFromCache -> Health.SAVED
        d.isDemo -> Health.DEMO
        d.action == Action.UNAVAILABLE && d.quote == null -> Health.NONE
        d.dataHealth?.status == "FAIL" -> Health.NONE
        d.marketClosed -> Health.CLOSED
        !d.isFresh -> Health.STALE
        d.hasStaleSource -> Health.PARTIAL  // price is live but an input of the analysis is old
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
    val ctx = LocalContext.current
    val askNotify = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) { granted -> vm.setNotify(granted) }
    val code = remember { InstallCode.get(ctx) }
    CompositionLocalProvider(LocalWatermark provides code) { GoldContent(s, lang, onAsk = vm::ask, onNextDemo = vm::nextDemoMoment,
        onSave = { u, t -> vm.setServerUrl(u); vm.setToken(t) }, onLive = vm::setLiveMode,
        onHorizon = vm::selectHorizon, onLanguage = onLanguage, onNotify = vm::setNotify, onAssetPick = vm::setAsset,
        onPosition = vm::setPosition, onAlertAsset = vm::toggleAlertAsset, onPriceAlert = vm::togglePriceAlert,
        onNeedNotify = {
            if (android.os.Build.VERSION.SDK_INT >= 33) askNotify.launch(android.Manifest.permission.POST_NOTIFICATIONS)
            else vm.setNotify(true)
        }, onBars = vm::loadBars, onCalendar = vm::loadCalendar, onOnboarded = vm::finishOnboarding,
        onPollLive = { vm.pollLive() }, onTouch = vm::loadTouch, onRange = vm::loadRange) }
}

private sealed interface Sheet {
    data class LevelSheet(val level: Level, val isSupport: Boolean) : Sheet
    data object Probabilities : Sheet
    data object TrendSheet : Sheet
    data object Details : Sheet
    data object Settings : Sheet
    data object Assets : Sheet
    data object TrustSheet : Sheet
    data object TrustDetails : Sheet
    data object HowSheet : Sheet
    data object NewsSheet : Sheet
    data object ScalpSheet : Sheet
    data object ChartSheet : Sheet
    data class TouchSheet(val focus: Double?) : Sheet
    data object CalendarSheet : Sheet
    data object RangeSheet : Sheet
}

/** Stateless screen (also used by the UI tests on several screen sizes). */
@Composable
fun GoldContent(s: UiState, lang: Lang, onAsk: () -> Unit, onNextDemo: () -> Unit, onSave: (String, String) -> Unit,
                onLive: (Boolean) -> Unit, onHorizon: (String) -> Unit, onLanguage: (Lang) -> Unit,
                onNotify: (Boolean) -> Unit = {}, onAssetPick: (String) -> Unit = {}, onPosition: (String) -> Unit = {},
                onAlertAsset: (String) -> Unit = {}, onPriceAlert: (PriceAlert) -> Unit = {},
                onNeedNotify: () -> Unit = {}, onBars: (String, String) -> Unit = { _, _ -> },
                onCalendar: () -> Unit = {}, onOnboarded: () -> Unit = {}, onPollLive: suspend () -> Unit = {},
                onTouch: (String, List<Double>) -> Unit = { _, _ -> }, onRange: (String) -> Unit = {}) {
    var sheet by remember { mutableStateOf<Sheet?>(null) }
    val onBell: (PriceAlert) -> Unit = { a ->
        val adding = !PriceAlerts.isOn(s.priceAlerts, a.asset, a.price)
        onPriceAlert(a)
        if (adding && !s.notify) onNeedNotify()  // an alert needs notifications: the activity asks for permission
    }
    val d = s.decision
    val selected = HorizonModel.resolve(s.selectedHorizon, d)
    BoxWithConstraints(Modifier.fillMaxSize().background(Bg).watermark(LocalWatermark.current).safeDrawingPadding()) {
        // Compact layout on short screens: secondary details are dropped instead of shrinking the text.
        val compact = maxHeight < 700.dp
        val gap = if (compact) 6.dp else 8.dp
        // One screen, no scrolling: everything secondary opens from the three tiles at the bottom.
        Column(
            Modifier.fillMaxSize().padding(horizontal = 12.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(gap),
        ) {
            TopBar(s, compact, onAsset = { sheet = Sheet.Assets }, onCalendar = { onCalendar(); sheet = Sheet.CalendarSheet }) { sheet = Sheet.Settings }
            val card = d?.let { HorizonModel.card(it, selected) }
            Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(gap)) {
                PriceCard(d, s, Modifier.weight(1.1f).fillMaxHeight()) { onBars(s.asset, "H1"); sheet = Sheet.ChartSheet }
                Box(Modifier.weight(1f).fillMaxHeight()) { TrendCard(card?.trend) { sheet = Sheet.TrendSheet } }
            }
            // experimental closing range (qualified horizons only), as designed by Ali: one strip under the price
            LaunchedEffect(s.asset, d?.decisionId) { if (d != null && !d.isDemo) onRange(s.asset) }
            s.range?.takeIf { it.asset == s.asset && it.available && d?.isDemo != true }?.let { r ->
                RangeStrip(r) { sheet = Sheet.RangeSheet }
            }
            if (d?.isDemo == true) Text(stringResource(R.string.demo_banner),
                color = Color.Black, fontSize = 12.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().background(WaitGold, RoundedCornerShape(8.dp)).padding(vertical = 4.dp))
            val haptic = androidx.compose.ui.platform.LocalHapticFeedback.current
            AskButton(s.loading, compact) {
                haptic.performHapticFeedback(androidx.compose.ui.hapticfeedback.HapticFeedbackType.LongPress); onAsk()
            }
            s.error?.let { ErrorStrip(it, onAsk) }
            if (d != null && card != null) {
                HorizonTabs(d, selected, s.loading, onHorizon)
                Crossfade(targetState = card, animationSpec = tween(240), label = "horizon",
                    modifier = Modifier.weight(1f).fillMaxWidth()) { c ->
                    DecisionCard(c, s, d, compact, Modifier.fillMaxSize(), onPosition, onBell) { l, sup -> sheet = Sheet.LevelSheet(l, sup) }
                }
                Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(gap)) {
                    if (d.instrument != "XAU/USD") ScalpTile(d, Modifier.weight(1f).fillMaxHeight()) { sheet = Sheet.ScalpSheet }
                    else ProbTile(card, Modifier.weight(1f).fillMaxHeight()) { sheet = Sheet.Probabilities }
                    Tile(stringResource(R.string.rec_title), recordTile(s.briefs),
                        WaitGold, Modifier.weight(1f).fillMaxHeight()) { sheet = Sheet.TrustSheet }
                    Tile(stringResource(R.string.details), stringResource(R.string.why_title), WaitGold,
                        Modifier.weight(1f).fillMaxHeight()) { sheet = Sheet.Details }
                }
            } else {
                if (s.error == null) Text(stringResource(R.string.prompt_ask), color = TextDim, fontSize = 14.sp,
                    textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(16.dp))
                Spacer(Modifier.weight(1f))
                Tile(stringResource(R.string.rec_title), recordTile(s.briefs),
                    WaitGold, Modifier.fillMaxWidth()) { sheet = Sheet.TrustSheet }
            }
            Text(stringResource(R.string.footer_disclaimer), color = TextDim, fontSize = 9.sp, lineHeight = 11.sp,
                textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        }
    }
    val card = d?.let { HorizonModel.card(it, selected) }
    when (val sh = sheet) {
        is Sheet.LevelSheet -> if (card != null) LevelDialog(sh.level, sh.isSupport, card,
            onTouch = { sheet = Sheet.TouchSheet(sh.level.price) }) { sheet = null }
        is Sheet.TouchSheet -> TouchDialog(s, card, sh.focus, onLoad = { ps -> onTouch(s.asset, ps) }) { sheet = null }
        Sheet.Probabilities -> if (card != null && d != null) ProbabilityDialog(card, d, s.track) { sheet = null }
        Sheet.TrendSheet -> if (card != null) TrendDialog(card) { sheet = null }
        Sheet.Details -> if (card != null && d != null) DetailsDialog(card, d) { sheet = null }
        Sheet.Assets -> AssetDialog(s, { a -> sheet = null; onAssetPick(a) }) { sheet = null }
        Sheet.TrustSheet -> RecordPage(s.briefs, onMore = { sheet = Sheet.TrustDetails }) { sheet = null }
        Sheet.TrustDetails -> TrustDialog(s.trust, s.position) { sheet = Sheet.TrustSheet }
        Sheet.RangeSheet -> RangeDialog(s, s.live[s.asset]?.price ?: s.decision?.quote) { sheet = null }
        Sheet.Settings -> SettingsDialog(s, lang, onNextDemo, onSave, onLive, onLanguage, onNotify, onAlertAsset,
            onHow = { sheet = Sheet.HowSheet }, onNews = { sheet = Sheet.NewsSheet }) { sheet = null }
        Sheet.HowSheet -> HowDialog { sheet = null }
        Sheet.ScalpSheet -> if (d != null) ScalpDialog(d) { sheet = null }
        Sheet.NewsSheet -> NewsDialog { sheet = null }
        Sheet.ChartSheet -> ChartDialog(s, card, d, onTf = { tf -> onBars(s.asset, tf) },
            onTouch = { sheet = Sheet.TouchSheet(null) }, onFollow = {
            val following = s.asset in s.alertAssets && s.notify
            if (!following) {
                if (s.asset !in s.alertAssets) onAlertAsset(s.asset)
                if (!s.notify) onNeedNotify()  // the activity asks for permission and turns notifications on
            } else onAlertAsset(s.asset)
        }) { sheet = null }
        Sheet.CalendarSheet -> CalendarDialog(s.calendar) { sheet = null }
        null -> Unit
    }
    if (!s.onboarded) OnboardingDialog(onDone = onOnboarded)
    // live crypto price while this screen is visible (display only; the analysis uses closed bars)
    val owner = androidx.lifecycle.compose.LocalLifecycleOwner.current
    LaunchedEffect(s.asset, owner) {
        if (s.asset == "XAU") return@LaunchedEffect
        owner.lifecycle.repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
            while (true) { onPollLive(); kotlinx.coroutines.delay(3000) }
        }
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
private fun TopBar(s: UiState, compact: Boolean, onAsset: () -> Unit, onCalendar: () -> Unit = {}, onSettings: () -> Unit) {
    val h = health(s)
    val cdA = stringResource(R.string.cd_asset) + " · " + stringResource(h.label)
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        // asset selector; the dot keeps the data-health colour that this pill used to spell out
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Row(Modifier.border(1.dp, Gold, RoundedCornerShape(50)).clickable(role = Role.Button, onClick = onAsset)
                .semantics { contentDescription = cdA }.padding(horizontal = 10.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(8.dp).background(h.color, CircleShape))
                Spacer(Modifier.width(6.dp))
                Text(ltr(assetPair(s.asset)), color = TextMain, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
                Spacer(Modifier.width(4.dp))
                Text("▾", color = Gold, fontSize = 12.sp)
            }
            // shown only when something is wrong: the analysis uses an input older than allowed
            if (h == Health.PARTIAL) Text(stringResource(R.string.health_partial_hint), color = WaitGold, fontSize = 9.sp,
                maxLines = 1, modifier = Modifier.clickable(role = Role.Button, onClick = onAsset).padding(top = 2.dp))
        }
        Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(stringResource(R.string.app_name), color = Gold, fontWeight = FontWeight.ExtraBold, fontSize = 18.sp, maxLines = 1)
            if (!compact) Text(stringResource(if (s.asset == "XAU") R.string.tagline else R.string.tagline_crypto),
                color = TextDim, fontSize = 10.sp)
        }
        val cdc = stringResource(R.string.cal_title)
        Box(Modifier.size(40.dp).border(1.dp, Gold, CircleShape)
            .clickable(role = Role.Button, onClick = onCalendar).semantics { contentDescription = cdc },
            contentAlignment = Alignment.Center) { Text("📅", fontSize = 16.sp) }
        Spacer(Modifier.width(6.dp))
        val cd = stringResource(R.string.cd_settings)
        Box(Modifier.size(40.dp).border(1.dp, Gold, CircleShape)
            .clickable(role = Role.Button, onClick = onSettings).semantics { contentDescription = cd },
            contentAlignment = Alignment.Center) { Text("⚙", color = Gold, fontSize = 18.sp) }
    }
}

fun assetPair(a: String): String = if (a == "XAU") "XAU/USD" else "$a/USD"

@Composable
private fun AssetDialog(s: UiState, onPick: (String) -> Unit, onClose: () -> Unit) {
    val h = health(s)
    DialogFrame(stringResource(R.string.asset_title), onClose) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).background(h.color, CircleShape))
            Spacer(Modifier.width(6.dp))
            Body(stringResource(R.string.asset_status, stringResource(h.label)), TextDim, 12.sp)
        }
        listOf(R.string.asset_gold to "XAU", R.string.asset_btc to "BTC", R.string.asset_eth to "ETH",
            R.string.asset_sol to "SOL").forEach { (name, code) ->
            val on = code == s.asset
            Row(Modifier.fillMaxWidth().border(1.dp, if (on) Gold else Track, RoundedCornerShape(12.dp))
                .clickable(role = Role.Button) { onPick(code) }
                .padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(stringResource(name), color = TextMain, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                    Text(ltr(assetPair(code)), color = TextDim, fontSize = 11.sp)
                }
                Text(if (on) "✓" else if (code == "XAU") "" else stringResource(R.string.asset_analysis),
                    color = if (on) Gold else TextDim, fontSize = 11.sp)
            }
        }
        s.decision?.let { if (it.sources.isNotEmpty()) SourcesSection(it.sources) }
        s.decision?.dataHealth?.let { DataHealthSection(it) }
    }
}

@Composable
private fun SourcesSection(list: List<SourceStatus>) {
    Section(stringResource(R.string.src_title))
    val zone = java.time.ZoneId.systemDefault()
    val today = java.time.LocalDate.now(zone)
    val hm = java.time.format.DateTimeFormatter.ofPattern("HH:mm")
    val dm = java.time.format.DateTimeFormatter.ofPattern("dd/MM HH:mm")
    list.forEach { x ->
        val name = stringResource(when (x.source) {
            "PRICE" -> R.string.src_price; "M15" -> R.string.src_m15; "H1" -> R.string.src_h1; "H4" -> R.string.src_h4
            "D1" -> R.string.src_d1; "CALENDAR" -> R.string.src_calendar; "ACTIVITY_MODEL" -> R.string.src_model
            else -> R.string.src_other
        })
        val (word, col) = when (x.state) {
            "OK" -> R.string.src_ok to BuyGreen; "STALE" -> R.string.src_stale to WaitGold
            "CLOSED" -> R.string.src_closed to Grey; else -> R.string.src_down to SellRed
        }
        val t = x.lastUpdate?.atZone(zone)?.let { z -> ltr((if (z.toLocalDate() == today) hm else dm).format(z)) } ?: "—"
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(name, color = TextMain, fontSize = 12.sp, modifier = Modifier.weight(1f))
            Text(t, color = TextDim, fontSize = 11.sp, modifier = Modifier.padding(horizontal = 8.dp))
            Text(stringResource(word), color = col, fontSize = 12.sp)
        }
    }
    Body(stringResource(R.string.src_note), TextDim, 10.sp)
}

@Composable
private fun PriceCard(d: Decision?, s: UiState, modifier: Modifier, onChart: () -> Unit = {}) {
    val tick = s.live[s.asset]?.takeIf { System.currentTimeMillis() - it.at < 15_000 && d?.marketClosed != true }
    val price = tick?.price ?: d?.quote
    // brief green/red flash when the price moves
    var prev by remember(s.asset) { mutableStateOf(price) }
    val flash = remember { androidx.compose.animation.Animatable(TextMain) }
    LaunchedEffect(price) {
        val p0 = prev
        if (price != null && p0 != null && price != p0) {
            flash.snapTo(if (price > p0) BuyGreen else SellRed)
            flash.animateTo(TextMain, tween(900))
        }
        prev = price
    }
    Panel(modifier, onClick = onChart) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(ltr(assetPair(s.asset)), color = TextDim, fontSize = 12.sp)
                if (tick != null) {
                    Spacer(Modifier.width(6.dp))
                    Box(Modifier.size(6.dp).background(BuyGreen, CircleShape))
                    Spacer(Modifier.width(3.dp))
                    Text(stringResource(R.string.live_badge), color = BuyGreen, fontSize = 10.sp)
                }
            }
            Text(price?.p2() ?: "—", color = flash.value, fontSize = 28.sp, fontWeight = FontWeight.Bold, maxLines = 1)
            val ch = d?.quoteChange
            if (ch != null) {
                val up = ch >= 0
                val pct = d?.quoteChangePct?.let { " (${if (up) "+" else ""}${String.format(Locale.US, "%.2f", it)}%)" } ?: ""
                Text(ltr("${if (up) "+" else ""}${ch.p2()}$pct ${if (up) "▲" else "▼"}"),
                    color = if (up) BuyGreen else SellRed, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            }
            val t = d?.quoteTime ?: s.receivedAt
            val today = t != null && t.atZone(ZoneId.systemDefault()).toLocalDate() == java.time.LocalDate.now()
            val shown = when {
                t == null -> "—"
                today -> t.hms()
                else -> t.atZone(ZoneId.systemDefault()).format(java.time.format.DateTimeFormatter.ofPattern("EEE HH:mm", Locale.getDefault()))
            }
            if (tick == null) Text(stringResource(if (d?.marketClosed == true) R.string.closed_price_at else R.string.updated_at, ltr(shown)),
                color = if (d?.marketClosed == true) WaitGold else TextDim, fontSize = 10.sp, maxLines = 1)
            Sparkline(s.candles["${s.asset}/H1"], Modifier.fillMaxWidth().height(18.dp).padding(top = 2.dp))
        }
    }
}

@Composable
private fun trendLabel(dir: String?): String = stringResource(when (trendCode(dir)) {
    "UP" -> R.string.tr_up; "DOWN" -> R.string.tr_down; "SIDEWAYS" -> R.string.tr_sideways; else -> R.string.tr_unknown
})

/** Trend codes (the server sends per-timeframe codes since schema 1.16 in "per_timeframe_code"). */
internal fun trendCode(dir: String?): String? = when (dir) {
    "UP" -> "UP"; "DOWN" -> "DOWN"; "SIDEWAYS", "NEUTRAL" -> "SIDEWAYS"; else -> null
}

private fun trendColor(dir: String?): Color = when (trendCode(dir)) {
    "UP" -> BuyGreen; "DOWN" -> SellRed; "SIDEWAYS" -> WaitGold; else -> Grey
}

@Composable
private fun TrendCard(t: Trend?, onClick: () -> Unit) {
    val color = trendColor(t?.direction)
    Panel(Modifier.fillMaxSize(), onClick = onClick) {
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
private fun HorizonTabs(d: Decision, current: String, loading: Boolean, onSelect: (String) -> Unit) {
    val outer = RoundedCornerShape(14.dp)
    Row(Modifier.fillMaxWidth().background(Card, outer).border(1.dp, CardEdge, outer).padding(3.dp),
        horizontalArrangement = Arrangement.spacedBy(3.dp)) {
        HorizonModel.ORDER.forEach { h ->
            val o = d.outlooks.firstOrNull { it.horizon == h }
            val action = o?.action ?: Action.UNAVAILABLE
            val isSel = h == current
            val c = actionColor(action, o?.tilt ?: 0)
            val bg by animateColorAsState(if (isSel) Color(0xFF1D1A12) else Color.Transparent, tween(200), label = "tab")
            val shape = RoundedCornerShape(11.dp)
            val name = horizonName(h)
            val cd = if (isSel) stringResource(R.string.cd_horizon_selected, name) else stringResource(R.string.cd_horizon, name)
            Column(Modifier.weight(1f).heightIn(min = 48.dp).background(bg, shape)
                .border(1.dp, if (isSel) Gold else Color.Transparent, shape)
                .clickable(role = Role.Tab) { onSelect(h) }
                .semantics { contentDescription = cd; selected = isSel }.padding(vertical = 4.dp),
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                Text(name, color = if (isSel) Gold else TextMain, fontSize = 13.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                Text(when {
                    loading -> stringResource(R.string.hz_updating)
                    o == null -> stringResource(R.string.a_unavailable)
                    else -> actionTitle(action)
                }, color = c, fontSize = 11.sp, maxLines = 1)
            }
        }
    }
}

@Composable
private fun Tile(title: String, value: String, valueColor: Color, modifier: Modifier, onClick: () -> Unit) {
    Panel(modifier, onClick = onClick) {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(title, color = TextMain, fontSize = 12.sp, fontWeight = FontWeight.Bold, maxLines = 1)
            Text(value, color = valueColor, fontSize = 11.sp, maxLines = 2, textAlign = TextAlign.Center, lineHeight = 14.sp)
        }
    }
}

@Composable
private fun ScalpTile(d: Decision, modifier: Modifier, onClick: () -> Unit) {
    val a = d.scalpActivity
    val color = when (a?.level) { "HIGH" -> BuyGreen; "LOW" -> TextDim; else -> WaitGold }
    Tile(stringResource(R.string.scalp_tile),
        if (a != null) stringResource(R.string.scalp_tile_act, Math.round(a.probability * 100).toInt())
        else stringResource(R.string.scalp_engine_off), if (a != null) color else WaitGold, modifier, onClick)
}

@Composable
private fun ScalpDialog(d: Decision, onClose: () -> Unit) {
    DialogFrame(stringResource(R.string.scalp_tile), onClose) {
        val a = d.scalpActivity
        if (a != null) {
            val hrs = if (a.hours % 1.0 == 0.0) a.hours.toInt().toString() else a.hours.toString()
            Text(stringResource(R.string.scalp_activity_head, hrs), color = TextMain, fontSize = 14.sp, fontWeight = FontWeight.Bold)
            Text(stringResource(when (a.level) { "HIGH" -> R.string.scalp_level_high; "LOW" -> R.string.scalp_level_low
                else -> R.string.scalp_level_normal }),
                color = when (a.level) { "HIGH" -> BuyGreen; "LOW" -> TextDim; else -> WaitGold }, fontSize = 15.sp,
                fontWeight = FontWeight.Bold)
            Body(stringResource(R.string.scalp_activity_prob, String.format(java.util.Locale.US, "%.2f", a.targetPct),
                Math.round(a.probability * 100).toInt(), Math.round(a.usual * 100).toInt()), TextMain, 13.sp)
            Body(stringResource(R.string.scalp_activity_note), TextDim, 12.sp)
            if (a.skill != null && a.holdoutSkill != null) Body(stringResource(R.string.scalp_activity_valid,
                Math.round(a.skill * 100).toInt(), Math.round(a.holdoutSkill * 100).toInt()), TextDim, 11.sp)
        } else Body(stringResource(R.string.scalp_activity_none), TextDim, 12.sp)
        Spacer(Modifier.height(4.dp))
        Body(stringResource(R.string.scalp_engine_status), WaitGold, 12.sp)
    }
}

@Composable
private fun ProbTile(c: HorizonCard, modifier: Modifier, onClick: () -> Unit) {
    val o = c.outcomes
    Panel(modifier, onClick = onClick) {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(stringResource(R.string.prob_title), color = TextMain, fontSize = 12.sp, fontWeight = FontWeight.Bold, maxLines = 1)
            if (c.probState == ProbState.AVAILABLE && o != null) {
                Text("${Math.round(o.target * 100)}%", color = BuyGreen, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            } else Text(stringResource(R.string.prob_na), color = WaitGold, fontSize = 11.sp, maxLines = 1)
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
private fun DecisionCard(c: HorizonCard, s: UiState, d: Decision, compact: Boolean, modifier: Modifier,
                         onPosition: (String) -> Unit = {}, onBell: (PriceAlert) -> Unit = {},
                         onLevel: (Level, Boolean) -> Unit) {
    val expired = d.isExpired(Instant.now())
    var showChecks by remember { mutableStateOf(false) }
    if (showChecks) ChecklistDialog(c) { showChecks = false }
    val color = actionColor(c.action, c.tilt)
    val why = when {
        d.marketClosed -> stringResource(R.string.closed_last_session)
        c.action == Action.BUY || c.action == Action.SELL ->
            stringResource(if (c.horizon == "HOURS") R.string.sub_court else R.string.sub_validated_rule)
        c.action == Action.WAIT -> if (c.stance != null && c.tilt != 0) rt(c.stance) else rt(c.reason ?: c.warnings.firstOrNull())
        else -> rt(c.warnings.firstOrNull() ?: c.reason)
    }
    Panel(modifier, edge = color.copy(alpha = 0.7f)) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            val watch = if (c.action == Action.WAIT && c.plan?.recommendation != true && !d.marketClosed) watchPrice(c, d) else null
            Row(verticalAlignment = Alignment.CenterVertically) {
                // a WAIT says what to do: watch the level that would change the picture (never a trade)
                val title = if (watch != null) stringResource(R.string.hl_wait_watch) else actionTitle(c.action)
                Text(title, color = color, fontSize = if (c.action == Action.UNAVAILABLE) 26.sp else 28.sp, lineHeight = 36.sp,
                    fontWeight = FontWeight.Black, maxLines = 2, modifier = Modifier.weight(1f))
                val known = c.checklist.filter { it.ok != null }
                if (c.plan?.recommendation != true && known.isNotEmpty()) Text(
                    stringResource(R.string.ck_chip, known.count { it.ok == true }, known.size) + " ›", color = WaitGold, fontSize = 11.sp,
                    maxLines = 1, modifier = Modifier.border(1.dp, Color(0xFF5A4A1C), RoundedCornerShape(10.dp))
                        .clickable(role = Role.Button) { showChecks = true }
                        .padding(horizontal = 8.dp, vertical = 2.dp))
            }
            if (watch != null) Text(stringResource(R.string.hl_sub2), color = TextDim, fontSize = 13.sp)
            else if (why.isNotBlank()) Text(why, color = TextMain, fontSize = 12.sp, lineHeight = 16.sp, maxLines = 2,
                overflow = TextOverflow.Ellipsis)
            if (s.decisionFromCache || expired) Text(stringResource(R.string.saved_decision), color = WaitGold, fontSize = 11.sp)
            if (c.action != Action.UNAVAILABLE) PositionChip(s.position) { onPosition(if (s.position == "HOLD") "CASH" else "HOLD") }
            Divider()
            val rec = c.plan?.recommendation == true && !d.isDemo
            if (rec) PositionLine(c, d, s.position, true)
            if (rec) {
                if (!(c.plan!!.side == "SELL")) PlanLine(c.plan, d)  // a SELL plan is phrased by the position line
                KV(stringResource(R.string.l_duration), durationText(c), 12.sp)
            } else {
                // today's scenarios are built from HOURLY levels: they belong to the hours horizon only
                if (c.horizon == "HOURS") d.brief?.let { BriefLines(it, s, d.quote, onBell) }
                if (c.action != Action.UNAVAILABLE) MineLine(c, s)
            }
            Divider()
            val lv = c.levels
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                val rows = if (compact) 2 else 3
                LevelPair(stringResource(R.string.lv_supports), stringResource(R.string.lv_sup_hint), BuyGreen,
                    lv?.supports.orEmpty(), rows, Modifier.weight(1f)) { onLevel(it, true) }
                LevelPair(stringResource(R.string.lv_resistances), stringResource(R.string.lv_res_hint), SellRed,
                    lv?.resistances.orEmpty(), rows, Modifier.weight(1f)) { onLevel(it, false) }
            }
            if (!rec) Text(stringResource(R.string.card_foot), color = TextDim, fontSize = 11.sp, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().padding(top = 4.dp))
        }
    }
}

@Composable
private fun Divider() = Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0xFF262118)))

@Composable
private fun LevelPair(title: String, hint: String, color: Color, items: List<Level>, rows: Int, modifier: Modifier,
                      onOpen: (Level) -> Unit) {
    Column(modifier) {
        Text(title, color = color, fontSize = 13.sp, fontWeight = FontWeight.Bold)
        Text(hint, color = TextDim, fontSize = 10.sp, lineHeight = 13.sp)
        if (items.isEmpty()) Text(stringResource(R.string.lv_none), color = TextDim, fontSize = 11.sp)
        items.take(rows).forEach { l ->
            // one level per row: price + strength bar (tap = details)
            Row(Modifier.fillMaxWidth().heightIn(min = 34.dp).clickable(role = Role.Button) { onOpen(l) },
                verticalAlignment = Alignment.CenterVertically) {
                Text(ltr(l.price.p2()), color = TextMain, fontSize = 14.sp, fontWeight = FontWeight.Bold, maxLines = 1,
                    modifier = Modifier.weight(1f))
                Segments(labelFill(l), color)
            }
        }
    }
}

// ---------------------------------------------------------------- trade plan (one clear line + details)
@Composable
private fun planHeadline(p: Plan): String {
    val entry = p.entryLow?.let { lo -> p.entryHigh?.takeIf { it != lo }?.let { "${lo.p2()}–${it.p2()}" } ?: lo.p2() }
    return when (p.setup) {
        "BUY_NOW" -> stringResource(R.string.pl_buy_now, ltr(entry ?: "—"), ltr(p.target!!.p2()), ltr(p.stop!!.p2()))
        "SELL_NOW" -> stringResource(R.string.pl_sell_now, ltr(entry ?: "—"), ltr(p.target!!.p2()), ltr(p.stop!!.p2()))
        "WAIT_TO_BUY" -> if (p.recommendation && p.stop != null && p.target != null)
            stringResource(R.string.pl_wait_buy_rec, ltr(p.watchPrice?.p2() ?: "—"), ltr(p.target.p2()), ltr(p.stop.p2()))
            else stringResource(R.string.pl_wait_buy, ltr(p.watchPrice?.p2() ?: "—"))
        "WAIT_TO_SELL" -> if (p.recommendation && p.stop != null && p.target != null)
            stringResource(R.string.pl_wait_sell_rec, ltr(p.watchPrice?.p2() ?: "—"), ltr(p.target.p2()), ltr(p.stop.p2()))
            else stringResource(R.string.pl_wait_sell, ltr(p.watchPrice?.p2() ?: "—"))
        "UNAVAILABLE" -> stringResource(R.string.pl_unavailable)
        else -> stringResource(R.string.pl_wait)
    }
}

@Composable
private fun PlanLine(p: Plan, d: Decision) {
    val rec = p.recommendation && !d.isDemo
    val color = when {
        rec -> if (p.side == "SELL") SellRed else BuyGreen
        p.isNow -> WaitGold
        else -> TextMain
    }
    Text(planHeadline(p), color = color, fontSize = 13.sp, fontWeight = FontWeight.Bold, lineHeight = 17.sp)
    if (p.isNow || rec) Text(stringResource(if (rec) R.string.pl_rec else R.string.pl_not_rec),
        color = if (rec) TextDim else WaitGold, fontSize = 10.sp)
}

@Composable
private fun briefLine(sc: Scenario): String = when {  // plain words, no level codes (S1/R1) for beginners
    sc.kind == "BULL" && sc.target != null -> stringResource(R.string.sc_up, ltr(sc.trigger.p2()), ltr(sc.target.p2()))
    sc.kind == "BULL" -> stringResource(R.string.sc_up_open, ltr(sc.trigger.p2()))
    sc.target != null -> stringResource(R.string.sc_down, ltr(sc.trigger.p2()), ltr(sc.target.p2()))
    else -> stringResource(R.string.sc_down_open, ltr(sc.trigger.p2()))
}

@Composable
private fun checkText(k: Check): String {
    val a0 = k.args.getOrNull(0) ?: ""; val a1 = k.args.getOrNull(1)?.let { ltr(it) } ?: ""
    return when (k.code) {
        "session" -> stringResource(if (k.ok == true) R.string.ck_session_ok else R.string.ck_session_no)
        "news" -> when (k.ok) {
            true -> stringResource(R.string.ck_news_ok)
            false -> stringResource(R.string.ck_news_no, a0)
            else -> when (k.state) {  // unknown is never shown as "no news"
                "STALE" -> stringResource(R.string.ck_news_stale, k.updatedAt?.let {
                    ltr(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm").format(it.atZone(java.time.ZoneId.systemDefault())))
                } ?: "—")
                "NOT_CONFIGURED" -> stringResource(R.string.ck_news_unconf)
                else -> stringResource(R.string.ck_news_na)
            }
        }
        "volatility" -> stringResource(when (k.ok) { true -> R.string.ck_vol_ok; false -> R.string.ck_vol_no; else -> R.string.ck_vol_na })
        "trend" -> stringResource(when (k.ok) { true -> R.string.ck_trend_ok; false -> R.string.ck_trend_no; else -> R.string.ck_trend_na })
        "level" -> when (k.ok) { true -> stringResource(R.string.ck_level_ok, a0); false -> stringResource(R.string.ck_level_no, a0, a1)
            else -> stringResource(R.string.ck_level_na) }
        "reward_risk" -> stringResource(if (k.ok == true) R.string.ck_rr_ok else R.string.ck_rr_no, ltr(a0))
        "model" -> stringResource(if (k.ok == true) R.string.ck_model_ok else R.string.ck_model_no)
        else -> k.code
    }
}

@Composable
private fun ChecklistDialog(c: HorizonCard, onClose: () -> Unit) {
    DialogFrame(stringResource(R.string.ck_title) + " · " + horizonName(c.horizon), onClose) {
        val known = c.checklist.filter { it.ok != null }
        Body(stringResource(R.string.ck_count, known.count { it.ok == true }, known.size), TextMain, 13.sp)
        c.checklist.forEach { k ->
            val (mark, col) = when (k.ok) { true -> "✓" to BuyGreen; false -> "✗" to SellRed; else -> "?" to TextDim }
            Spacer(Modifier.height(4.dp))
            Body("$mark  " + checkText(k), col, 13.sp)
            Body(stringResource(when (k.code) {
                "session" -> R.string.ck_why_session; "news" -> R.string.ck_why_news
                "volatility" -> R.string.ck_why_volatility; "trend" -> R.string.ck_why_trend
                "level" -> R.string.ck_why_level; "reward_risk" -> R.string.ck_why_rr
                "model" -> R.string.ck_why_model; else -> R.string.ck_why_other
            }), TextDim, 11.sp)
        }
        Spacer(Modifier.height(6.dp))
        if (c.checklist.any { it.ok == null }) Body(stringResource(R.string.ck_unknown_note), TextDim, 11.sp)
        Body(stringResource(R.string.ck_dialog_note), WaitGold, 11.sp)
    }
}

@Composable
private fun CheckSection(list: List<Check>) {
    if (list.isEmpty()) return
    Section(stringResource(R.string.ck_title))
    list.forEach { k ->
        val (mark, col) = when (k.ok) { true -> "✓" to BuyGreen; false -> "✗" to SellRed; else -> "?" to TextDim }
        Body("$mark  " + checkText(k), col, 12.sp)
    }
}

@Composable
private fun BriefLines(b: Brief, s: UiState? = null, price: Double? = null, onBell: (PriceAlert) -> Unit = {}) {
    Text(stringResource(R.string.card_sc_title), color = Gold, fontSize = 13.sp, fontWeight = FontWeight.Bold)
    b.scenarios.take(2).forEach { sc ->
        val col = if (sc.kind == "BULL") BuyGreen else SellRed
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 2.dp)) {
            Text(if (sc.kind == "BULL") "▲ " else "▼ ", color = col, fontSize = 13.sp)
            Text(briefLine(sc), color = col, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, lineHeight = 20.sp,
                modifier = Modifier.weight(1f))
            if (s != null) BellChip(PriceAlerts.isOn(s.priceAlerts, s.asset, sc.trigger), compact = true) {
                onBell(PriceAlerts.make(s.asset, sc.trigger, price, sc.triggerLevel))
            }
        }
    }
}

@Composable
private fun BellChip(on: Boolean, compact: Boolean = false, onClick: () -> Unit) {
    val shape = RoundedCornerShape(10.dp)
    val cd = stringResource(if (on) R.string.bell_on else R.string.bell_off)
    Text(if (compact) "🔔" else cd, color = if (on) Color.Black else Gold, fontSize = if (compact) 10.sp else 10.sp,
        maxLines = 1,
        modifier = Modifier.padding(start = 4.dp).background(if (on) Gold else Color.Transparent, shape)
            .border(1.dp, Gold, shape).clickable(role = Role.Switch, onClickLabel = cd, onClick = onClick)
            .semantics { contentDescription = cd }.padding(horizontal = 6.dp, vertical = 2.dp))
}

/** The level a WAIT should watch: today's first scenario (hours), the plan's watch price, else the nearest level
 *  on the side of the bias. */
private fun watchPrice(c: HorizonCard, d: Decision): Double? {
    if (c.horizon == "HOURS") d.brief?.scenarios?.firstOrNull()?.let { return it.trigger }
    c.plan?.watchPrice?.let { return it }
    val lv = c.levels ?: return null
    val s1 = lv.supports.firstOrNull()?.price
    val r1 = lv.resistances.firstOrNull()?.price
    return if (c.tilt < 0) s1 ?: r1 else if (c.tilt > 0) r1 ?: s1 else (s1 ?: r1)
}

@Composable
private fun setupName(s: String): String = stringResource(when (s) {
    "BUY_NOW" -> R.string.su_buy_now; "SELL_NOW" -> R.string.su_sell_now; "WAIT_TO_BUY" -> R.string.su_wait_buy
    "WAIT_TO_SELL" -> R.string.su_wait_sell; "UNAVAILABLE" -> R.string.su_unavailable; else -> R.string.su_wait
})

@Composable
private fun PlanSection(p: Plan, d: Decision) {
    val rec = p.recommendation && !d.isDemo
    Section(stringResource(R.string.sec_plan))
    KV(stringResource(R.string.pl_setup), setupName(p.setup))
    Body(stringResource(if (rec) R.string.pl_rec else if (p.isNow) R.string.pl_not_rec else R.string.pl_watch_note),
        if (rec) TextDim else WaitGold, 11.sp)
    if (p.stop != null && p.target != null && p.entryLow != null) {
        val lo = p.entryLow
        KV(stringResource(R.string.pl_entry), ltr(p.entryHigh?.takeIf { it != lo }?.let { "${lo.p2()} – ${it.p2()}" } ?: lo.p2()))
        KV(stringResource(R.string.l_target), p.target.p2())
        KV(stringResource(R.string.l_stop), p.stop.p2())
        p.rewardRisk?.let { KV(stringResource(R.string.pl_rr), ltr("${it.p2()} : 1")) }
        val dur = p.expectedMinutes?.let { if (it % 60 == 0) stringResource(R.string.dur_hours, it / 60) else stringResource(R.string.dur_minutes, it) }
            ?: p.expectedDays?.let { stringResource(R.string.dur_days, it) }
        dur?.let { KV(stringResource(R.string.l_duration), it) }
        p.validUntil?.let { KV(stringResource(R.string.pl_valid), ltr(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")
            .withZone(java.time.ZoneId.systemDefault()).format(it))) }
        if (rec && p.pTarget != null && p.pStop != null && p.pTimeout != null) {
            Body(stringResource(R.string.pl_probs, Math.round(p.pTarget * 100).toInt(), Math.round(p.pStop * 100).toInt(),
                Math.round(p.pTimeout * 100).toInt()), TextMain, 11.sp)
        }
        if (rec && p.pFill != null && p.fillDays != null) Body(stringResource(R.string.pl_fill, p.fillDays, Math.round(p.pFill * 100).toInt()), TextMain, 11.sp)
        if (rec) p.medianDaysToTarget?.let { Body(stringResource(R.string.pl_days_to_target, ltr(String.format(Locale.US, "%.0f", it))), TextMain, 11.sp) }
        if (rec) p.evPct?.let { Body(stringResource(R.string.pl_ev, ltr(String.format(Locale.US, "%+.2f%%", it))), TextMain, 11.sp) }
        Body(stringResource(R.string.pl_expire_note), TextDim, 11.sp)
        if (p.invalidation.isNotEmpty()) {
            Body(stringResource(R.string.pl_cancel), TextDim, 11.sp)
            p.invalidation.take(4).forEach { Body("• ${rt(it)}", TextMain, 11.sp) }
        }
        if (p.side == "SELL") Body(stringResource(R.string.pl_sell_note), WaitGold, 11.sp)
    } else if (p.watchPrice != null) {
        KV(stringResource(R.string.pl_watch), p.watchPrice.p2())
    }
}

@Composable
private fun PerfSection(list: List<Perf>) {
    Section(stringResource(R.string.sec_perf))
    if (list.isEmpty() || list.all { it.trades == 0 && it.pending == 0 && it.notFilled == 0 }) {
        Body(stringResource(R.string.perf_none), TextDim, 11.sp)
    }
    list.forEach { p ->
        Body(stringResource(when (p.source) {
            "OOS_BACKTEST" -> R.string.src_oos; "OOS_PLANNER" -> R.string.src_planner
            "LIVE_PAPER" -> R.string.src_paper; else -> R.string.src_live
        }), Gold, 12.sp)
        if (p.directionAccuracy != null && p.directionBaseline != null) Body(stringResource(R.string.perf_dir,
            Math.round(p.directionAccuracy * 100).toInt(), Math.round(p.directionBaseline * 100).toInt()), TextMain, 11.sp)
        val u = { v: Double? -> v?.let { if (p.unit == "PCT") String.format(Locale.US, "%+.2f%%", it) else String.format(Locale.US, "%+.2f $", it) } ?: "—" }
        if (p.trades > 0) {
            Body(stringResource(R.string.perf_trades, p.trades, Math.round(100.0 * p.hits / p.trades).toInt()), TextMain, 11.sp)
            Body(stringResource(R.string.perf_avg, ltr(u(p.avgWin)), ltr(u(p.avgLoss))), TextMain, 11.sp)
            Body(stringResource(R.string.perf_exp, ltr(u(p.expectancy)), ltr(u(p.maxDrawdown?.let { -kotlin.math.abs(it) }))), TextMain, 11.sp)
            if (p.trades < 30) Body(stringResource(R.string.live_few), WaitGold, 11.sp)
        } else Body(stringResource(R.string.perf_none), TextDim, 11.sp)
        if (p.pending > 0 || p.notFilled > 0) Body(stringResource(R.string.perf_pending, p.pending, p.notFilled), TextDim, 11.sp)
        p.baselineExpectancy?.let { Body(stringResource(R.string.perf_base, ltr(u(it))), TextMain, 11.sp) }
        p.qualified?.let { Body(stringResource(if (it) R.string.perf_q_yes else R.string.perf_q_no), if (it) BuyGreen else WaitGold, 11.sp) }
        p.period?.let { Body(ltr(it), TextDim, 10.sp) }
    }
    Body(stringResource(R.string.perf_hit_note), TextDim, 10.sp)
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
// ---------------------------------------------------------------- dialogs (in-screen, no extra pages)
/** Dialogs are separate windows: they get FLAG_SECURE explicitly (not only by inheritance). */
internal val SecureDialog: DialogProperties
    get() = DialogProperties(securePolicy = if (com.goldaiquant.app.Protection.dialogsSecure) SecureFlagPolicy.SecureOn
                             else SecureFlagPolicy.SecureOff)

@Composable
private fun DialogFrame(title: String, onClose: () -> Unit, content: @Composable () -> Unit) {
    Dialog(onDismissRequest = onClose, properties = SecureDialog) {
        Column(Modifier.fillMaxWidth().heightIn(max = 620.dp).background(Card, RoundedCornerShape(16.dp))
            .watermark(LocalWatermark.current)
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
private fun LevelDialog(l: Level, isSupport: Boolean, c: HorizonCard, onTouch: () -> Unit = {}, onClose: () -> Unit) {
    val color = if (isSupport) BuyGreen else SellRed
    val locale = LocalConfiguration.current.locales[0]
    val fmt = remember(locale) { DateTimeFormatter.ofLocalizedDateTime(FormatStyle.MEDIUM).withLocale(locale) }
    DialogFrame(stringResource(if (isSupport) R.string.lv_support else R.string.lv_resistance), onClose) {
        Text(l.price.p2(), color = color, fontSize = 26.sp, fontWeight = FontWeight.Black)
        Text(stringResource(R.string.touch_open), color = Color.Black, fontSize = 12.sp, fontWeight = FontWeight.Bold,
            modifier = Modifier.background(Gold, RoundedCornerShape(10.dp)).clickable(role = Role.Button, onClick = onTouch)
                .padding(horizontal = 10.dp, vertical = 4.dp))
        KV(stringResource(R.string.lv_zone), ltr("${l.zoneLow.p2()} – ${l.zoneHigh.p2()}"))
        // strength only when the engine validated it; otherwise it is explicitly "not validated"
        KV(stringResource(R.string.lv_strength), l.strength?.let { stringResource(R.string.lv_strength_val, it) }
            ?: stringResource(R.string.lv_not_validated))
        l.holdProbability?.let { KV(stringResource(R.string.lv_hold_prob), "${Math.round(it * 100)}%") }
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
private fun ProbabilityDialog(c: HorizonCard, d: Decision, track: List<TrackItem>, onClose: () -> Unit) {
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
        val mine = track.filter { it.horizon == c.horizon }.take(8)
        if (mine.isNotEmpty()) {
            Section(stringResource(R.string.track_title))
            mine.forEach { t ->
                Body(stringResource(R.string.track_row, ltr(t.bar),
                    stringResource(if (t.tilt > 0) R.string.track_up else R.string.track_down),
                    ltr(t.close.p2()), ltr(t.exitClose.p2()),
                    stringResource(if (t.hit) R.string.track_hit else R.string.track_miss)),
                    if (t.hit) BuyGreen else SellRed, 11.sp)
            }
        }
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
        CheckSection(c.checklist)
        c.plan?.let { PlanSection(it, d) }
        PerfSection(c.performance)
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
                           onAlertAsset: (String) -> Unit = {}, onHow: () -> Unit = {}, onNews: () -> Unit = {}, onClose: () -> Unit) {
    val askPermission = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) { granted -> onNotify(granted) }
    Dialog(onDismissRequest = onClose, properties = SecureDialog) {
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
            if (s.notify) {
                Text(stringResource(R.string.alerts_assets), color = TextMain, fontSize = 12.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("XAU", "BTC", "ETH", "SOL").forEach { a ->
                        val on = a in s.alertAssets
                        Text((if (on) "✓ " else "") + a, color = if (on) Color.Black else TextMain, fontSize = 12.sp,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.background(if (on) Gold else Color.Transparent, RoundedCornerShape(10.dp))
                                .border(1.dp, Gold, RoundedCornerShape(10.dp)).clickable(role = Role.Checkbox) { onAlertAsset(a) }
                                .padding(horizontal = 10.dp, vertical = 6.dp))
                    }
                }
            }
            if (!s.liveMode) TextButton(onClick = { onNextDemo(); onClose() }) {
                Text(stringResource(R.string.set_demo_next, s.demoStep + 1), color = TextDim)
            }
            Row {
                TextButton(onClick = onHow) { Text(stringResource(R.string.how_title), color = Gold) }
                TextButton(onClick = onNews) { Text(stringResource(R.string.news_title), color = Gold) }
            }
            if (com.goldaiquant.app.BuildConfig.DEBUG) {
                val act = LocalContext.current.findActivity()
                var allow by remember { mutableStateOf(act?.let { com.goldaiquant.app.Protection.screenshotsAllowed(it) } ?: false) }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(stringResource(R.string.set_allow_shots), color = TextMain, fontSize = 14.sp, modifier = Modifier.weight(1f))
                    Switch(checked = allow, onCheckedChange = { on ->
                        allow = on
                        act?.let { com.goldaiquant.app.Protection.setScreenshotsAllowed(it, on); onClose(); it.recreate() }
                    })
                }
                Text(stringResource(R.string.set_allow_shots_note), color = TextDim, fontSize = 11.sp)
            }
            Text(stringResource(R.string.app_version, com.goldaiquant.app.BuildConfig.VERSION_NAME,
                com.goldaiquant.app.BuildConfig.VERSION_CODE), color = TextDim, fontSize = 11.sp)
            Row {
                TextButton(onClick = { onSave(url, tok); onClose() }) { Text(stringResource(R.string.save), color = Gold) }
                TextButton(onClick = onClose) { Text(stringResource(R.string.cancel), color = TextDim) }
            }
        }
    }
}

// ---------------------------------------------------------------- public trust ledger
private fun rFmt(v: Double?): String = v?.let { String.format(Locale.US, "%+.2fR", it) } ?: "—"
private fun pct(v: Double?): Int = Math.round((v ?: 0.0) * 100).toInt()

@Composable
private fun TrustDialog(t: Trust?, position: String = "CASH", onClose: () -> Unit) {
    val uri = LocalUriHandler.current
    DialogFrame(stringResource(R.string.trust_title), onClose) {
        Body(stringResource(R.string.trust_how))
        if (t != null) {
            Body(stringResource(R.string.trust_summary, t.all.completed, t.daysTracked))
            if (t.open > 0) Body(stringResource(R.string.trust_open, t.open), TextDim, 11.sp)
            if (t.all.completed > 0) {
                Body(stringResource(R.string.trust_win, pct(t.all.winRate), ltr(rFmt(t.all.avgR))))
                t.all.baselineAvgR?.let { b ->
                    Body(stringResource(R.string.trust_base, ltr(rFmt(b))), TextMain, 11.sp)
                    val better = (t.all.avgR ?: 0.0) > b
                    Body(stringResource(if (better) R.string.trust_better else R.string.trust_worse),
                        if (better) BuyGreen else WaitGold, 12.sp)
                }
                if (t.all.completed < 30) Body(stringResource(R.string.live_few), WaitGold, 11.sp)
            } else Body(stringResource(R.string.trust_empty), TextDim, 11.sp)
            if (t.analysisScored > 0) Body(stringResource(R.string.trust_analysis, pct(t.accuracy), t.analysisScored,
                pct(t.baselineAccuracy)), TextMain, 11.sp)
            else Body(stringResource(R.string.trust_analysis_none), TextDim, 11.sp)
            if (t.byModel.isNotEmpty()) {
                Section(stringResource(R.string.trust_by_model))
                t.byModel.forEach { (v, b) -> Body(stringResource(R.string.trust_model_row, ltr(v), b.completed, ltr(rFmt(b.avgR))), TextMain, 11.sp) }
            }
            if (t.recent.isNotEmpty()) {
                Section(stringResource(R.string.trust_recent))
                t.recent.filter { it.r != null }.take(10).forEach { r ->
                    val out = stringResource(when (r.outcome) {
                        "TARGET" -> R.string.out_target; "STOP" -> R.string.out_stop; else -> R.string.out_timeout })
                    Body("${ltr(r.date)} · ${horizonName(r.horizon)} · ${if (r.side == "BUY") "BUY" else "SELL"} · $out · ${ltr(rFmt(r.r))}",
                        if ((r.r ?: 0.0) > 0) BuyGreen else SellRed, 11.sp)
                }
            }
            ScenarioSection(t, position)
            Body(ltr("SHA-256 " + t.head.take(16) + "…"), TextDim, 10.sp)
        }
        TextButton(onClick = { uri.openUri(TrustLedger.REPO_URL) }) {
            Text(stringResource(R.string.trust_verify), color = Gold, fontWeight = FontWeight.Bold)
        }
    }
}

// ---------------------------------------------------------------- data health (automatic checks, shown in the asset sheet)
@Composable
private fun dqName(code: String): String = stringResource(when (code) {
    "freshness" -> R.string.dq_freshness; "coverage" -> R.string.dq_coverage; "gaps" -> R.string.dq_gaps
    "outliers" -> R.string.dq_outliers; "flat" -> R.string.dq_flat; "weekend" -> R.string.dq_weekend
    "ohlc" -> R.string.dq_ohlc; "cross_source" -> R.string.dq_cross; else -> R.string.dq_other
})

@Composable
private fun DataHealthSection(h: DataHealth) {
    Section(stringResource(R.string.dq_title))
    val (word, col) = when (h.status) {
        "OK" -> R.string.dq_ok to BuyGreen; "FAIL" -> R.string.dq_fail to SellRed; else -> R.string.dq_warn to WaitGold
    }
    Body(stringResource(word), col, 12.sp)
    h.checks.forEach { c ->
        val (mark, cc) = when (c.status) { "OK" -> "✓" to BuyGreen; "FAIL" -> "✗" to SellRed; else -> "!" to WaitGold }
        Body("$mark  ${dqName(c.code)}" + (c.value?.let { " · " + ltr(it) } ?: ""), cc, 11.sp)
    }
    Body(stringResource(R.string.dq_note), TextDim, 10.sp)
}

// ---------------------------------------------------------------- position (cash / holder): same analysis, phrased for the user
@Composable
private fun PositionChip(pos: String, onToggle: () -> Unit) {
    Text(stringResource(R.string.pos_label, stringResource(if (pos == "HOLD") R.string.pos_hold else R.string.pos_cash)),
        color = Gold, fontSize = 11.sp, maxLines = 1,
        modifier = Modifier.border(1.dp, CardEdge, RoundedCornerShape(10.dp)).clickable(role = Role.Button, onClick = onToggle)
            .padding(horizontal = 8.dp, vertical = 3.dp))
}

@Composable
private fun PositionLine(c: HorizonCard, d: Decision, pos: String, rec: Boolean) {
    val hold = pos == "HOLD"
    val p = c.plan
    if (rec && p != null) {
        val txt = when {
            p.side == "BUY" && hold -> stringResource(R.string.pos_buy_rec_hold)
            p.side == "SELL" && !hold -> stringResource(R.string.pos_sell_rec_cash)
            p.side == "SELL" -> stringResource(R.string.pos_reduce_now,
                ltr(p.entryLow?.p2() ?: d.quote?.p2() ?: "—"), ltr(p.target?.p2() ?: "—"), ltr(p.stop?.p2() ?: "—"))
            else -> null
        }
        txt?.let { Text(it, color = if (p.side == "SELL") SellRed else BuyGreen, fontSize = 13.sp, fontWeight = FontWeight.Bold) }
        return
    }
    val lv = c.levels
    val s1 = lv?.supports?.firstOrNull()?.let { ltr(it.price.p2()) } ?: "—"
    val r1 = lv?.resistances?.firstOrNull()?.let { ltr(it.price.p2()) } ?: "—"
    val s2 = lv?.supports?.getOrNull(1)?.let { ltr(it.price.p2()) } ?: s1
    val bias = when {
        c.tilt > 0 -> 1; c.tilt < 0 -> -1
        d.brief?.bias == "UP" -> 1; d.brief?.bias == "DOWN" -> -1; else -> 0
    }
    val txt = when (bias) {
        1 -> stringResource(if (hold) R.string.pos_up_hold else R.string.pos_up_cash, s1, r1)
        -1 -> stringResource(if (hold) R.string.pos_down_hold else R.string.pos_down_cash, s1, s2)
        else -> stringResource(if (hold) R.string.pos_side_hold else R.string.pos_side_cash, s1, r1)
    }
    Text(txt, color = TextMain, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, lineHeight = 17.sp)
    Text(stringResource(R.string.pos_watch_note), color = TextDim, fontSize = 10.sp)
}

/** One plain line for the user's own situation: the number that matters to them (never a trade). */
@Composable
private fun MineLine(c: HorizonCard, s: UiState) {
    val hold = s.position == "HOLD"
    val key = if (hold) c.levels?.supports?.firstOrNull()?.price else c.levels?.resistances?.firstOrNull()?.price
    if (key == null) return
    val name = stringResource(when (s.asset) { "BTC" -> R.string.asset_btc; "ETH" -> R.string.asset_eth
        "SOL" -> R.string.asset_sol; else -> R.string.asset_gold })
    val txt = stringResource(if (hold) R.string.mine_hold else R.string.mine_cash, name, ltr(key.p2()))
    val i = txt.indexOf(ltr(key.p2()))
    Text(buildAnnotatedString {
        append(txt)
        if (i >= 0) addStyle(SpanStyle(color = Gold, fontWeight = FontWeight.Bold), i, i + ltr(key.p2()).length)
    }, color = TextMain, fontSize = 13.sp, lineHeight = 19.sp,
        modifier = Modifier.fillMaxWidth().padding(top = 4.dp).background(Color(0xFF1A1610), RoundedCornerShape(12.dp))
            .padding(horizontal = 10.dp, vertical = 8.dp))
}

// ---------------------------------------------------------------- how it works / what's new
@Composable
private fun HowDialog(onClose: () -> Unit) {
    val uri = LocalUriHandler.current
    DialogFrame(stringResource(R.string.how_title), onClose) {
        listOf(R.string.how_1, R.string.how_2, R.string.how_3, R.string.how_4, R.string.how_5, R.string.how_6).forEach {
            Body("• " + stringResource(it), TextMain, 12.sp)
        }
        TextButton(onClick = { uri.openUri(TrustLedger.REPO_URL) }) {
            Text(stringResource(R.string.trust_verify), color = Gold, fontWeight = FontWeight.Bold)
        }
        Body(stringResource(R.string.how_disclaimer), TextDim, 11.sp)
        LocalWatermark.current?.let { Body(stringResource(R.string.protect_note, it), TextDim, 11.sp) }
    }
}

@Composable
private fun NewsDialog(onClose: () -> Unit) {
    DialogFrame(stringResource(R.string.news_title), onClose) {
        Body(stringResource(R.string.app_version, com.goldaiquant.app.BuildConfig.VERSION_NAME,
            com.goldaiquant.app.BuildConfig.VERSION_CODE), Gold, 12.sp)
        listOf(R.string.news_1, R.string.news_2, R.string.news_3, R.string.news_4, R.string.news_5, R.string.news_6).forEach {
            Body("• " + stringResource(it), TextMain, 12.sp)
        }
    }
}

// ---------------------------------------------------------------- experimental strategy scenarios for "my position"
@Composable
private fun ScenarioSection(t: Trust, position: String) {
    val names = if (position == "HOLD") listOf("HOLD_SELL_REBUY") else listOf("CASH_BUY_DIP", "CASH_WAIT_LOWER")
    Section(stringResource(R.string.scen_title))
    Body(stringResource(R.string.scen_note), WaitGold, 11.sp)
    names.forEach { n ->
        Body(stringResource(when (n) {
            "CASH_BUY_DIP" -> R.string.scen_buy_dip; "CASH_WAIT_LOWER" -> R.string.scen_wait_lower; else -> R.string.scen_sell_rebuy
        }), Gold, 12.sp)
        val b = t.scenarios[n]
        if (b == null || b.scenarios == 0) { Body(stringResource(R.string.scen_none), TextDim, 11.sp); return@forEach }
        Body(stringResource(R.string.scen_counts, b.scenarios, b.triggered, b.notTriggered, b.wins, b.losses), TextMain, 11.sp)
        val pct = { v: Double? -> v?.let { String.format(java.util.Locale.US, "%+.2f%%", it) } ?: "—" }
        Body(stringResource(R.string.scen_perf, ltr(pct(b.avgReturnPct)), ltr(pct(b.maxDrawdownPct?.let { -kotlin.math.abs(it) })),
            Math.round((b.beatRefShare ?: 0.0) * 100).toInt()), TextMain, 11.sp)
        b.avgR?.let { Body(stringResource(R.string.scen_r, ltr(String.format(java.util.Locale.US, "%+.2fR", it))), TextMain, 11.sp) }
    }
}

/** Dialog windows get a wrapped context: walk the wrappers to reach the Activity. */
private fun android.content.Context.findActivity(): android.app.Activity? {
    var c: android.content.Context? = this
    while (c is android.content.ContextWrapper) {
        if (c is android.app.Activity) return c
        c = c.baseContext
    }
    return null
}

// ---------------------------------------------------------------- chart, calendar, onboarding
/** Thin price line of the last closes (inside the price card). */
@Composable
private fun Sparkline(c: Candles?, modifier: Modifier) {
    if (c == null || c.size < 5) return
    val xs = c.c.takeLast(48)
    val up = xs.last() >= xs.first()
    androidx.compose.foundation.Canvas(modifier) {
        val lo = xs.min(); val hi = xs.max(); val span = (hi - lo).takeIf { it > 0 } ?: 1.0
        val path = androidx.compose.ui.graphics.Path()
        xs.forEachIndexed { i, v ->
            val x = size.width * i / (xs.size - 1)
            val y = size.height * (1 - ((v - lo) / span)).toFloat()
            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        drawPath(path, if (up) BuyGreen else SellRed, style = androidx.compose.ui.graphics.drawscope.Stroke(width = 2f))
    }
}

/** Candlestick chart with the horizon's levels and today's scenario triggers drawn on it. Closed candles only. */
@Composable
private fun ChartDialog(s: UiState, card: HorizonCard?, d: Decision?, onTf: (String) -> Unit,
                        onTouch: () -> Unit = {}, onFollow: () -> Unit = {}, onClose: () -> Unit) {
    var tf by remember { mutableStateOf("H1") }
    LaunchedEffect(tf, s.asset) { onTf(tf) }
    val c = s.candles["${s.asset}/$tf"]
    DialogFrame(stringResource(R.string.chart_title, ltr(assetPair(s.asset))), onClose) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("H1" to R.string.chart_h1, "D1" to R.string.chart_d1).forEach { (k, label) ->
                val on = tf == k
                Text(stringResource(label), color = if (on) Color.Black else Gold, fontSize = 12.sp, fontWeight = FontWeight.Bold,
                    modifier = Modifier.background(if (on) Gold else Color.Transparent, RoundedCornerShape(10.dp))
                        .border(1.dp, Gold, RoundedCornerShape(10.dp)).clickable(role = Role.Tab) { tf = k }
                        .padding(horizontal = 12.dp, vertical = 4.dp))
            }
        }
        if (c == null || c.size < 2) {
            Body(stringResource(R.string.chart_loading), TextDim, 12.sp)
            return@DialogFrame
        }
        val sup = card?.levels?.supports.orEmpty()
        val res = card?.levels?.resistances.orEmpty()
        // pinch to zoom (fewer candles AND a taller chart), drag to scroll back in time, double tap to reset
        var shownBars by remember(tf, s.asset) { mutableStateOf(CHART_BARS.toFloat()) }
        var back by remember(tf, s.asset) { mutableStateOf(0f) }
        var grow by remember(tf, s.asset) { mutableStateOf(1f) }
        val nb = shownBars.toInt().coerceIn(20, maxOf(20, c.size))
        val end = (c.size - back.toInt()).coerceIn(minOf(nb, c.size), c.size)
        val from = maxOf(0, end - nb)
        val n = end - from
        val o = c.o.subList(from, end); val hh = c.h.subList(from, end)
        val ll = c.l.subList(from, end); val cc = c.c.subList(from, end)
        val lo0 = ll.min(); val hi0 = hh.max()
        val span0 = (hi0 - lo0).coerceAtLeast(1e-9)
        // at most the two nearest zones on each side, and only those close to the visible prices
        val near = { l: Level -> l.zoneHigh >= lo0 - span0 * 0.25 && l.zoneLow <= hi0 + span0 * 0.25 }
        val shown = (sup.take(2).map { it to true } + res.take(2).map { it to false }).filter { near(it.first) }
        val edges = shown.flatMap { listOf(it.first.zoneLow, it.first.zoneHigh) }
        val pad = span0 * 0.05
        val lo = minOf(lo0, edges.minOrNull() ?: lo0) - pad
        val hi = maxOf(hi0, edges.maxOrNull() ?: hi0) + pad
        val measurer = androidx.compose.ui.text.rememberTextMeasurer()
        val live = c.c.last()
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End)) {
            Text(stringResource(R.string.touch_open), color = Color.Black, fontSize = 12.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.background(Gold, RoundedCornerShape(10.dp)).clickable(role = Role.Button, onClick = onTouch)
                    .padding(horizontal = 10.dp, vertical = 3.dp))
        }
        androidx.compose.foundation.Canvas(Modifier.fillMaxWidth().height((300 * grow).dp)
            .background(Bg, RoundedCornerShape(10.dp))
            .pointerInput(tf, s.asset, c.size) {
                detectTransformGestures { _, panXY, zoom, _ ->
                    shownBars = (shownBars / zoom).coerceIn(20f, c.size.toFloat().coerceAtLeast(20f))
                    grow = (grow * zoom).coerceIn(1f, 1.8f)
                    val perBar = size.width / shownBars
                    back = (back + panXY.x / perBar).coerceIn(0f, (c.size - 20).toFloat().coerceAtLeast(0f))
                }
            }
            .pointerInput(tf, s.asset) {
                detectTapGestures(onDoubleTap = { shownBars = CHART_BARS.toFloat(); back = 0f; grow = 1f })
            }
            .semantics { contentDescription = "chart" }) {
            val small = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.Bold)
            val fmtP = { p: Double -> if (live >= 1000) String.format(Locale.US, "%.0f", p) else String.format(Locale.US, "%.2f", p) }
            // the right-hand price column is as wide as its longest label: labels never wrap
            val sample = (shown.map { it.first.price } + live).maxByOrNull { fmtP(it).length } ?: live
            val gutter = measurer.measure(fmtP(sample), small, softWrap = false, maxLines = 1).size.width + 16f
            val w = size.width - gutter
            val y = { p: Double -> (size.height * (1 - (p - lo) / (hi - lo))).toFloat() }
            val O = { x: Float, yy: Float -> androidx.compose.ui.geometry.Offset(x, yy) }
            val labels = mutableListOf<Float>()  // right-side price labels already placed (no overlap)
            val clampY = { yy: Float, hgt: Int -> yy.coerceIn(0f, size.height - hgt) }
            val yl = y(live)
            labels += yl
            fun priceLabel(p: Double, yy: Float, col: Color) {
                val t = measurer.measure(fmtP(p), small.copy(color = col), softWrap = false, maxLines = 1)
                if (labels.any { kotlin.math.abs(it - yy) < t.size.height + 4 }) return
                labels += yy
                drawText(t, topLeft = O(w + 8f, clampY(yy - t.size.height / 2f, t.size.height)))
            }
            // one clean line per level (red = ceiling, green = floor); no overlapping grey bands
            shown.forEach { (l, isSup) ->
                val col = if (isSup) BuyGreen else SellRed
                drawLine(col.copy(alpha = 0.9f), O(0f, y(l.price)), O(w, y(l.price)), 3f)
                priceLabel(l.price, y(l.price), col)
            }
            val cw = w / n
            for (i in 0 until n) {
                val up = cc[i] >= o[i]
                val col = if (up) BuyGreen else SellRed
                val cx = cw * i + cw / 2
                drawLine(col, O(cx, y(hh[i])), O(cx, y(ll[i])), 1.5f)
                val top = y(maxOf(o[i], cc[i])); val bot = y(minOf(o[i], cc[i]))
                drawRect(col, O(cx - cw * 0.35f, top), androidx.compose.ui.geometry.Size(cw * 0.7f, maxOf(1.5f, bot - top)))
            }
            if (yl in 0f..size.height) {
                drawLine(Color.White, O(0f, yl), O(w, yl), 1.5f, pathEffect = androidx.compose.ui.graphics.PathEffect.dashPathEffect(floatArrayOf(10f, 8f)))
                val t = measurer.measure(fmtP(live), small.copy(color = Color.Black, fontWeight = FontWeight.Black),
                    softWrap = false, maxLines = 1)
                val ty = clampY(yl - t.size.height / 2f, t.size.height)
                drawRect(Gold, O(w + 2f, ty - 2f), androidx.compose.ui.geometry.Size(gutter - 4f, t.size.height + 4f))
                drawText(t, topLeft = O(w + 8f, ty))
            }
        }
        Text(stringResource(R.string.chart_hint2), color = TextDim, fontSize = 10.sp, textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth())
        val q = d?.quote ?: cc.last()
        val pz = { v: Double -> if (q >= 1000) v.p0() else v.p2() }  // whole dollars for gold / BTC / ETH
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(stringResource(R.string.now_price), color = TextDim, fontSize = 13.sp)
            Text(ltr(pz(q)), color = Gold, fontSize = 28.sp, fontWeight = FontWeight.Black)
        }
        // a five-step ladder: two ceilings above, the price, two floors below (plain words, no codes)
        val ceil = res.filter { it.price > q }.sortedBy { it.price }.take(2)
        val floor = sup.filter { it.price < q }.sortedByDescending { it.price }.take(2)
        Column(Modifier.fillMaxWidth().border(1.dp, Color(0xFF262118), RoundedCornerShape(12.dp)).clip(RoundedCornerShape(12.dp))) {
            @Composable
            fun step(price: String, label: String, col: Color, here: Boolean = false) =
                Row(Modifier.fillMaxWidth().background(if (here) Color(0xFF2A230F) else Color.Transparent)
                    .padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(price, color = col, fontSize = 16.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.width(12.dp))
                    Text(label, color = if (here) Gold else TextDim, fontSize = 12.sp, lineHeight = 16.sp, modifier = Modifier.weight(1f))
                }
            ceil.getOrNull(1)?.let { step(ltr(pz(it.price)), stringResource(R.string.lad_far_ceiling), SellRed) }
            ceil.getOrNull(0)?.let { step(ltr(pz(it.price)), stringResource(R.string.lad_near_ceiling), SellRed) }
            step("● " + ltr(pz(q)), stringResource(R.string.lad_here), Gold, here = true)
            floor.getOrNull(0)?.let { step(ltr(pz(it.price)), stringResource(R.string.lad_near_floor), BuyGreen) }
            floor.getOrNull(1)?.let { step(ltr(pz(it.price)), stringResource(R.string.lad_far_floor), BuyGreen) }
        }
        if (card?.horizon == "HOURS") d?.brief?.scenarios?.take(2)?.takeIf { it.isNotEmpty() }?.let { list ->
            Text(stringResource(R.string.what_next), color = Gold, fontSize = 14.sp, fontWeight = FontWeight.Bold)
            list.forEach { sc ->
                Text((if (sc.kind == "BULL") "▲ " else "▼ ") + briefLine(sc), color = if (sc.kind == "BULL") BuyGreen else SellRed,
                    fontSize = 14.sp, fontWeight = FontWeight.SemiBold, lineHeight = 20.sp)
            }
        }
        if (card?.horizon == "HOURS") d?.brief?.firstTouch?.let { ft ->
            Text(stringResource(R.string.ft_title2), color = Gold, fontSize = 14.sp, fontWeight = FontWeight.Bold)
            Row(Modifier.fillMaxWidth().height(10.dp).clip(RoundedCornerShape(5.dp))) {
                Box(Modifier.weight(ft.downFirst.toFloat().coerceAtLeast(0.01f)).fillMaxHeight().background(SellRed))
                Box(Modifier.weight(ft.upFirst.toFloat().coerceAtLeast(0.01f)).fillMaxHeight().background(BuyGreen))
            }
            Row(Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.ft_down, ltr(pz(ft.downLevel)), Math.round(ft.downFirst * 100).toInt()),
                    color = SellRed, fontSize = 13.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                Text(stringResource(R.string.ft_up, ltr(pz(ft.upLevel)), Math.round(ft.upFirst * 100).toInt()),
                    color = BuyGreen, fontSize = 13.sp, fontWeight = FontWeight.Bold)
            }
        }
        val on = s.asset in s.alertAssets && s.notify
        Text(stringResource(if (on) R.string.zone_follow2_on else R.string.zone_follow2), color = if (on) Color.Black else Gold,
            fontSize = 13.sp, textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp).background(if (on) Gold else Color.Transparent, RoundedCornerShape(12.dp))
                .border(1.dp, Gold, RoundedCornerShape(12.dp)).clickable(role = Role.Button, onClick = onFollow)
                .padding(vertical = 9.dp))
        Text(stringResource(R.string.card_foot), color = TextDim, fontSize = 11.sp, textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth())
    }
}

@Composable
private fun TouchDialog(s: UiState, card: HorizonCard?, focus: Double?, onLoad: (List<Double>) -> Unit, onClose: () -> Unit) {
    val lv = card?.levels
    val levels = (lv?.resistances.orEmpty().take(2).reversed().map { Triple(it.price, it.name, false) } +
        lv?.supports.orEmpty().take(2).map { Triple(it.price, it.name, true) })
    var custom by remember { mutableStateOf(focus?.let { String.format(Locale.US, "%.2f", it) } ?: "") }
    val customVal = custom.replace(',', '.').toDoubleOrNull()?.takeIf { it > 0 }
    val prices = (levels.map { it.first } + listOfNotNull(customVal)).distinct()
    LaunchedEffect(s.asset, prices.joinToString()) { if (prices.isNotEmpty()) onLoad(prices) }
    var hz by remember { mutableStateOf("24") }
    DialogFrame(stringResource(R.string.touch_title, ltr(assetPair(s.asset))), onClose) {
        val t = s.touch?.takeIf { it.asset == s.asset }
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf("4" to R.string.touch_h4, "24" to R.string.touch_h24, "120" to R.string.touch_h120).forEach { (k, label) ->
                val on = hz == k
                Text(stringResource(label), color = if (on) Color.Black else Gold, fontSize = 12.sp, fontWeight = FontWeight.Bold,
                    textAlign = TextAlign.Center, modifier = Modifier.weight(1f)
                        .background(if (on) Gold else Color.Transparent, RoundedCornerShape(10.dp))
                        .border(1.dp, Gold, RoundedCornerShape(10.dp)).clickable(role = Role.Tab) { hz = k }
                        .padding(vertical = 5.dp))
            }
        }
        when {
            s.touchLoading && t == null -> { Body(stringResource(R.string.chart_loading), TextDim, 12.sp); return@DialogFrame }
            s.touchFailed && t == null -> {
                Body(stringResource(R.string.touch_failed), WaitGold, 12.sp)
                Text(stringResource(R.string.touch_retry), color = Color.Black, fontSize = 12.sp, fontWeight = FontWeight.Bold,
                    modifier = Modifier.background(Gold, RoundedCornerShape(10.dp)).clickable(role = Role.Button) { onLoad(prices) }
                        .padding(horizontal = 12.dp, vertical = 5.dp))
                return@DialogFrame
            }
            t == null -> { Body(stringResource(R.string.chart_loading), TextDim, 12.sp); return@DialogFrame }
            !t.available -> { Body(stringResource(R.string.touch_unavailable), TextDim, 12.sp); return@DialogFrame }
        }
        val h = t!!.horizons[hz]
        if (h == null) { Body(stringResource(R.string.touch_not_validated), TextDim, 12.sp) }
        t.price?.let { Body(stringResource(R.string.touch_now, ltr(it.p2())), TextDim, 12.sp) }
        @Composable
        fun row(label: String, price: Double, isSup: Boolean) {
            val r = h?.results?.firstOrNull { kotlin.math.abs(it.price - price) < 1e-6 * maxOf(1.0, price) } ?: return
            val col = if (isSup) BuyGreen else SellRed
            Column(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(label + " · " + ltr(price.p2()), color = col, fontSize = 13.sp, modifier = Modifier.weight(1f))
                    val pct = r.probability?.let { Math.round(it * 100).toInt() }
                    Text(when {
                        pct == null -> "—"
                        r.status == "AT_LEAST" -> ltr("≥ $pct%")
                        r.status == "AT_MOST" -> ltr("≤ $pct%")
                        else -> "$pct%"
                    }, color = TextMain, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                }
                if (r.probability != null && r.status != "OUT_OF_RANGE") {
                    Bar(r.probability.toFloat(), col, Modifier.fillMaxWidth().padding(top = 3.dp))
                    when (r.status) {
                        "AT_LEAST" -> Text(stringResource(R.string.touch_at_least), color = TextDim, fontSize = 11.sp)
                        "AT_MOST" -> Text(stringResource(R.string.touch_at_most), color = TextDim, fontSize = 11.sp)
                        else -> r.usual?.let { Text(stringResource(R.string.touch_usual, Math.round(it * 100).toInt()), color = TextDim, fontSize = 11.sp) }
                    }
                } else Text(stringResource(R.string.touch_out_of_range), color = TextDim, fontSize = 11.sp)
            }
        }
        levels.forEach { (p, name, sup) ->
            row("${stringResource(if (sup) R.string.zone_support else R.string.zone_resistance)} $name", p, sup)
        }
        Divider()
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(value = custom, onValueChange = { v -> custom = v.filter { it.isDigit() || it == '.' || it == ',' }.take(12) },
                singleLine = true, label = { Text(stringResource(R.string.touch_custom)) },
                keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.Decimal),
                modifier = Modifier.weight(1f))
        }
        customVal?.takeIf { v -> levels.none { kotlin.math.abs(it.first - v) < 1e-9 } }?.let { v ->
            row(stringResource(R.string.touch_custom_row), v, v < (t.price ?: v))
        }
        if (h?.weak == true) Body(stringResource(R.string.touch_weak), WaitGold, 11.sp)
        Body(stringResource(R.string.touch_note), TextDim, 11.sp)
    }
}

@Composable
private fun CalendarDialog(info: CalendarInfo?, onClose: () -> Unit) {
    DialogFrame(stringResource(R.string.cal_title), onClose) {
        if (info == null) { Body(stringResource(R.string.chart_loading), TextDim, 12.sp); return@DialogFrame }
        val fmt = java.time.format.DateTimeFormatter.ofPattern("EEE d MMM · HH:mm", Locale.getDefault())
        Body(when (info.state) {
            "CONNECTED", "NO_EVENTS" -> stringResource(R.string.cal_ok, info.updatedAt?.let { ltr(fmt.format(it.atZone(ZoneId.systemDefault()))) } ?: "—")
            "STALE" -> stringResource(R.string.ck_news_stale, info.updatedAt?.let { ltr(fmt.format(it.atZone(ZoneId.systemDefault()))) } ?: "—")
            "NOT_CONFIGURED" -> stringResource(R.string.ck_news_unconf)
            else -> stringResource(R.string.ck_news_na)
        }, TextDim, 11.sp)
        val now = Instant.now()
        val next = info.events.firstOrNull { it.time.isAfter(now) && it.importance >= 3 }
        next?.let {
            val mins = java.time.Duration.between(now, it.time).toMinutes()
            Text(stringResource(R.string.cal_next, it.name, (mins / 60).toInt(), (mins % 60).toInt()), color = WaitGold,
                fontSize = 14.sp, fontWeight = FontWeight.Bold)
        }
        if (info.events.isEmpty()) Body(stringResource(R.string.cal_none), TextDim, 12.sp)
        info.events.forEach { e ->
            val past = e.time.isBefore(now)
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("★".repeat(e.importance.coerceIn(1, 3)), color = if (e.importance >= 3) SellRed else WaitGold, fontSize = 11.sp,
                    modifier = Modifier.width(36.dp))
                Text(e.name, color = if (past) TextDim else TextMain, fontSize = 13.sp, modifier = Modifier.weight(1f), maxLines = 1,
                    overflow = TextOverflow.Ellipsis)
                Text(ltr(fmt.format(e.time.atZone(ZoneId.systemDefault()))), color = TextDim, fontSize = 11.sp)
            }
        }
        Body(stringResource(R.string.cal_note), TextDim, 10.sp)
    }
}

@Composable
private fun OnboardingDialog(onDone: () -> Unit) {
    var page by remember { mutableStateOf(0) }
    val pages = listOf(
        R.string.ob1_title to R.string.ob1_text, R.string.ob2_title to R.string.ob2_text, R.string.ob3_title to R.string.ob3_text)
    Dialog(onDismissRequest = onDone, properties = SecureDialog) {
        Column(Modifier.fillMaxWidth().background(Card, RoundedCornerShape(18.dp)).border(1.dp, Gold, RoundedCornerShape(18.dp))
            .padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(stringResource(R.string.app_name), color = Gold, fontSize = 20.sp, fontWeight = FontWeight.ExtraBold)
            Text(stringResource(pages[page].first), color = TextMain, fontSize = 17.sp, fontWeight = FontWeight.Bold)
            Text(stringResource(pages[page].second), color = TextDim, fontSize = 14.sp, lineHeight = 20.sp)
            Row(verticalAlignment = Alignment.CenterVertically) {
                repeat(pages.size) { i ->
                    Box(Modifier.padding(end = 6.dp).size(if (i == page) 10.dp else 7.dp)
                        .background(if (i == page) Gold else Track, CircleShape))
                }
                Spacer(Modifier.weight(1f))
                if (page < pages.lastIndex) Text(stringResource(R.string.ob_skip), color = TextDim, fontSize = 13.sp,
                    modifier = Modifier.clickable(role = Role.Button, onClick = onDone).padding(8.dp))
                Text(stringResource(if (page < pages.lastIndex) R.string.ob_next else R.string.ob_start), color = Color.Black,
                    fontSize = 14.sp, fontWeight = FontWeight.Bold,
                    modifier = Modifier.background(Gold, RoundedCornerShape(12.dp))
                        .clickable(role = Role.Button) { if (page < pages.lastIndex) page++ else onDone() }
                        .padding(horizontal = 16.dp, vertical = 8.dp))
            }
        }
    }
}

// ---------------------------------------------------------------- results record (daily direction calls vs outcome)
@Composable
private fun recordTile(rows: List<BriefRow>): String {
    val sm = Record.summary(rows)
    return if (sm.settled == 0) stringResource(R.string.record_tile_none)
           else ltr(stringResource(R.string.record_tile, sm.correct, sm.settled))
}

private fun recPrice(v: Double?): String = when {
    v == null -> "—"
    v >= 10_000 -> String.format(Locale.US, "%,.0f", v)
    else -> String.format(Locale.US, "%.2f", v)
}

@Composable
private fun recAssetName(a: String): String = if (a == "XAU") stringResource(R.string.asset_gold) else a

@Composable
private fun RecAvatar(a: String) {
    val (letter, bg, fg) = when (a) {
        "BTC" -> Triple("B", Color(0xFFF7931A), Color(0xFF111111))
        "ETH" -> Triple("E", Color(0xFF1A2033), Color(0xFF8FA8FF))
        "SOL" -> Triple("S", Color(0xFF1D1430), Color(0xFFB28CFF))
        else -> Triple("G", Color(0xFF2E260E), WaitGold)
    }
    Box(Modifier.size(40.dp).background(bg, RoundedCornerShape(20.dp)).border(1.dp, fg.copy(alpha = 0.7f), RoundedCornerShape(20.dp)),
        contentAlignment = Alignment.Center) { Text(letter, color = fg, fontSize = 16.sp, fontWeight = FontWeight.Black) }
}

@Composable
private fun RecBadge(st: RecStatus, short: Boolean = true) {
    val (txt, bg, fg) = when (st) {
        RecStatus.CORRECT -> Triple("✓ " + stringResource(R.string.rec_c), Color(0xFF1F8F4E), Color.White)
        RecStatus.WRONG -> Triple("✕ " + stringResource(R.string.rec_w), Color(0xFFB3363B), Color.White)
        RecStatus.NEUTRAL -> Triple("— " + stringResource(R.string.rec_n), Track, Color(0xFFC8CCD4))
        RecStatus.NO_DATA -> Triple(stringResource(R.string.rec_nodata), Track, Color(0xFFC8CCD4))
        RecStatus.PENDING -> Triple("⏱ " + stringResource(if (short) R.string.rec_wait else R.string.rec_p), Track, Color(0xFFC8CCD4))
    }
    Text(txt, color = fg, fontSize = 13.sp, fontWeight = FontWeight.Bold, maxLines = 1,
        modifier = Modifier.background(bg, RoundedCornerShape(14.dp)).padding(horizontal = 12.dp, vertical = 4.dp))
}

@Composable
private fun RecGauge(acc: Double?, enough: Boolean) {
    val col = if (enough) BuyGreen else Grey
    Box(Modifier.size(width = 130.dp, height = 92.dp), contentAlignment = Alignment.BottomCenter) {
        Canvas(Modifier.fillMaxSize().padding(8.dp)) {
            val stroke = androidx.compose.ui.graphics.drawscope.Stroke(width = 22f, cap = androidx.compose.ui.graphics.StrokeCap.Round)
            val d = minOf(size.width, size.height * 2f)
            val tl = androidx.compose.ui.geometry.Offset((size.width - d) / 2f, 0f)
            val sz = androidx.compose.ui.geometry.Size(d, d)
            drawArc(Track, 180f, 180f, false, tl, sz, style = stroke)
            if (acc != null) drawArc(col, 180f, (180f * acc.toFloat()).coerceAtLeast(1f), false, tl, sz, style = stroke)
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(acc?.let { ltr("${Math.round(it * 100)}%") } ?: "—", color = TextMain, fontSize = 26.sp, fontWeight = FontWeight.Black)
            Text(stringResource(if (enough) R.string.rec_acc else R.string.rec_small), color = TextDim, fontSize = 11.sp)
        }
    }
}

@Composable
private fun RecDropdown(label: String, options: List<Pair<String, String>>, modifier: Modifier, onPick: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box(modifier) {
        Row(Modifier.fillMaxWidth().border(1.5.dp, Gold, RoundedCornerShape(22.dp)).clickable(role = Role.Button) { open = true }
            .padding(horizontal = 14.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(label, color = TextMain, fontSize = 14.sp, fontWeight = FontWeight.Bold, maxLines = 1, modifier = Modifier.weight(1f))
            Text("▾", color = Gold, fontSize = 14.sp)
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }, modifier = Modifier.background(Card)) {
            options.forEach { (k, v) ->
                DropdownMenuItem(text = { Text(v, color = TextMain) }, onClick = { open = false; onPick(k) })
            }
        }
    }
}

@Composable
private fun RecordPage(rows: List<BriefRow>, onMore: () -> Unit, onClose: () -> Unit) {
    val uri = LocalUriHandler.current
    var days by remember { mutableStateOf(7) }
    var asset by remember { mutableStateOf<String?>(null) }
    var showAll by remember { mutableStateOf(false) }
    var method by remember { mutableStateOf(false) }
    var detail by remember { mutableStateOf<BriefRow?>(null) }
    detail?.let { RecDetail(it) { detail = null } }
    val today = java.time.LocalDate.now(java.time.ZoneOffset.UTC)
    val shown = Record.filter(rows, asset, days, today)
    val sm = Record.summary(shown)
    val periods = listOf("1" to stringResource(R.string.rec_p_today), "7" to stringResource(R.string.rec_p_7),
        "30" to stringResource(R.string.rec_p_30))
    val assets = listOf("" to stringResource(R.string.rec_all_assets), "XAU" to stringResource(R.string.asset_gold),
        "BTC" to "BTC", "ETH" to "ETH", "SOL" to "SOL")
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false,
        securePolicy = SecureDialog.securePolicy)) {
        Column(Modifier.fillMaxSize().background(Bg).watermark(LocalWatermark.current).verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                val circle = Modifier.size(40.dp).border(1.5.dp, Gold, RoundedCornerShape(20.dp))
                Box(circle.clickable(role = Role.Button, onClickLabel = stringResource(R.string.rec_how)) { method = !method },
                    contentAlignment = Alignment.Center) { Text("i", color = WaitGold, fontSize = 18.sp, fontWeight = FontWeight.Black) }
                Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("AI QUANT", color = WaitGold, fontSize = 20.sp, fontWeight = FontWeight.Black)
                    Text(stringResource(R.string.rec_title), color = TextMain, fontSize = 14.sp)
                }
                Box(circle.clickable(role = Role.Button, onClickLabel = stringResource(R.string.close), onClick = onClose),
                    contentAlignment = Alignment.Center) { Text("→", color = WaitGold, fontSize = 18.sp, fontWeight = FontWeight.Bold) }
            }
            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                Text(stringResource(R.string.rec_q), color = TextMain, fontSize = 22.sp, fontWeight = FontWeight.Black, textAlign = TextAlign.Center)
                Text(stringResource(R.string.rec_sub), color = TextDim, fontSize = 13.sp, textAlign = TextAlign.Center)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                RecDropdown(periods.first { it.first == "$days" }.second, periods, Modifier.weight(1f)) { days = it.toInt(); showAll = false }
                RecDropdown(assets.first { it.first == (asset ?: "") }.second, assets, Modifier.weight(1f)) {
                    asset = it.ifEmpty { null }; showAll = false
                }
            }
            // summary: settled correct of settled, and the accuracy gauge (grey until enough settled calls)
            Row(Modifier.fillMaxWidth().background(Color(0xFF0F0E0B), RoundedCornerShape(20.dp))
                .border(1.dp, Color(0xFF6B5A22), RoundedCornerShape(20.dp)).padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(ltr(stringResource(R.string.rec_of, sm.correct, sm.settled)), color = WaitGold, fontSize = 34.sp, fontWeight = FontWeight.Black)
                    Text(stringResource(R.string.rec_correct_lbl), color = TextMain, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                }
                Box(Modifier.width(1.dp).height(80.dp).background(Track))
                Box(Modifier.weight(1f), contentAlignment = Alignment.Center) { RecGauge(sm.accuracy, sm.settled >= Record.MIN_SETTLED) }
            }
            if (days == 1) Text(stringResource(R.string.rec_today_note), color = TextDim, fontSize = 12.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                @Composable
                fun chip(t: String, n: Int, bg: Color, edge: Color, fg: Color) = Text("$t ${ltr("$n")}", color = fg, fontSize = 12.sp,
                    fontWeight = FontWeight.Bold, maxLines = 1, textAlign = TextAlign.Center,
                    modifier = Modifier.weight(1f).background(bg, RoundedCornerShape(16.dp)).border(1.dp, edge, RoundedCornerShape(16.dp))
                        .padding(vertical = 6.dp))
                chip("✓ " + stringResource(R.string.rec_c), sm.correct, Color(0xFF0F3A22), Color(0xFF1F8F4E), Color(0xFF3FE08A))
                chip("✕ " + stringResource(R.string.rec_w), sm.wrong, Color(0xFF3A1416), Color(0xFFB3363B), Color(0xFFFF7B80))
                chip("— " + stringResource(R.string.rec_n), sm.neutral, Track, Grey, Color(0xFFD0D0D6))
                chip("⏱ " + stringResource(R.string.rec_p), sm.pending, Track, Grey, Color(0xFFD0D0D6))
            }
            Text(stringResource(R.string.rec_latest), color = TextMain, fontSize = 17.sp, fontWeight = FontWeight.Black)
            Column(Modifier.fillMaxWidth().background(Color(0xFF0C0C0F), RoundedCornerShape(18.dp))
                .border(1.dp, Track, RoundedCornerShape(18.dp)).padding(horizontal = 12.dp)) {
                if (shown.isEmpty()) Text(stringResource(R.string.rec_empty), color = TextDim, fontSize = 13.sp,
                    modifier = Modifier.padding(vertical = 14.dp))
                val list = if (showAll) shown else shown.take(3)
                list.forEachIndexed { i, r ->
                    if (i > 0) Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0xFF222222)))
                    RecRow(r) { detail = r }
                }
            }
            if (shown.size > 3) Text(stringResource(if (showAll) R.string.rec_show_less else R.string.rec_show_all), color = WaitGold,
                fontSize = 16.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().background(Color(0xFF14120C), RoundedCornerShape(24.dp))
                    .border(1.5.dp, Gold, RoundedCornerShape(24.dp)).clickable(role = Role.Button) { showAll = !showAll }
                    .padding(vertical = 11.dp))
            // optional methodology: how accuracy is measured, and the "always up" baseline on the same calls
            Column(Modifier.fillMaxWidth().border(1.dp, Track, RoundedCornerShape(16.dp))) {
                Row(Modifier.fillMaxWidth().clickable(role = Role.Button) { method = !method }.padding(12.dp)) {
                    Text(stringResource(R.string.rec_how), color = TextMain, fontSize = 14.sp, fontWeight = FontWeight.Bold,
                        modifier = Modifier.weight(1f))
                    Text(if (method) "▴" else "▾", color = Gold)
                }
                if (method) Column(Modifier.padding(start = 12.dp, end = 12.dp, bottom = 12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf(R.string.rec_how_1, R.string.rec_how_2, R.string.rec_how_3, R.string.rec_how_4).forEach {
                        Text("• " + stringResource(it), color = TextMain, fontSize = 13.sp, lineHeight = 19.sp)
                    }
                    if (sm.settled > 0) Column(Modifier.fillMaxWidth().background(Color(0xFF1A1610), RoundedCornerShape(12.dp)).padding(10.dp)) {
                        Text(stringResource(R.string.rec_base_title), color = WaitGold, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                        @Composable
                        fun line(t: String, k: Int) = Row(Modifier.fillMaxWidth()) {
                            Text(t, color = TextMain, fontSize = 13.sp, modifier = Modifier.weight(1f))
                            Text(ltr(stringResource(R.string.rec_frac, k, sm.settled, Math.round(100.0 * k / sm.settled).toInt())),
                                color = TextMain, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                        }
                        line(stringResource(R.string.rec_base_ours), sm.correct)
                        line(stringResource(R.string.rec_base_up), sm.baselineUp)
                    }
                    Text(stringResource(R.string.rec_verify), color = WaitGold, fontSize = 12.sp,
                        modifier = Modifier.clickable(role = Role.Button) { uri.openUri(TrustLedger.REPO_URL) })
                    Text(stringResource(R.string.rec_more), color = TextDim, fontSize = 12.sp,
                        modifier = Modifier.clickable(role = Role.Button, onClick = onMore))
                }
            }
            Text("ⓘ " + stringResource(R.string.rec_foot), color = TextDim, fontSize = 12.sp, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun recDay(r: BriefRow): String {
    val locale = LocalConfiguration.current.locales[0]
    val d = try { java.time.LocalDate.parse(r.date) } catch (e: Exception) { null }
    return d?.let { DateTimeFormatter.ofPattern("d MMMM", locale).format(it) } ?: r.date
}

@Composable
private fun RecRow(r: BriefRow, onClick: () -> Unit) {
    val st = Record.status(r)
    Row(Modifier.fillMaxWidth().clickable(role = Role.Button, onClick = onClick).padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        RecAvatar(r.asset)
        Column(Modifier.weight(1f)) {
            Text(recDay(r) + " · " + ltr(recAssetName(r.asset)), color = TextMain, fontSize = 14.sp, fontWeight = FontWeight.Bold, maxLines = 1)
            if (st == RecStatus.NEUTRAL) Text(stringResource(R.string.rec_no_bias), color = TextDim, fontSize = 13.sp)
            else Text(buildAnnotatedString {
                val dir = stringResource(if (r.bias == "UP") R.string.rec_up else R.string.rec_down)
                val full = stringResource(R.string.rec_pred, dir)
                append(full)
                val i = full.indexOf(dir)
                if (i >= 0) addStyle(SpanStyle(color = if (r.bias == "UP") BuyGreen else SellRed), i, i + dir.length)
            }, color = TextMain, fontSize = 13.sp)
        }
        RecBadge(st)
    }
}

@Composable
private fun RecDetail(r: BriefRow, onClose: () -> Unit) {
    val st = Record.status(r)
    val title = stringResource(when (st) {
        RecStatus.CORRECT -> R.string.rec_why_ok; RecStatus.WRONG -> R.string.rec_why_bad
        RecStatus.NEUTRAL -> R.string.rec_why_neutral; else -> R.string.rec_why_wait
    })
    DialogFrame(title, onClose) {
        KV(stringResource(R.string.rec_d_asset), recDay(r) + " · " + ltr(recAssetName(r.asset)), 13.sp)
        KV(stringResource(R.string.rec_d_pred), if (st == RecStatus.NEUTRAL) stringResource(R.string.rec_no_bias)
            else stringResource(if (r.bias == "UP") R.string.rec_up else R.string.rec_down), 13.sp)
        KV(stringResource(R.string.rec_d_price), ltr(recPrice(r.price)), 13.sp)
        KV(stringResource(R.string.rec_d_close), ltr(recPrice(r.close)), 13.sp)
        val why = stringResource(when (st) {
            RecStatus.CORRECT -> if (r.bias == "UP") R.string.rec_x_ok_up else R.string.rec_x_ok_down
            RecStatus.WRONG -> if (r.bias == "UP") R.string.rec_x_bad_up else R.string.rec_x_bad_down
            RecStatus.NEUTRAL -> R.string.rec_x_neutral
            RecStatus.NO_DATA -> R.string.rec_x_nodata
            RecStatus.PENDING -> R.string.rec_x_wait
        })
        val bg = when (st) { RecStatus.CORRECT -> Color(0xFF0F3A22); RecStatus.WRONG -> Color(0xFF2A1214); else -> Track }
        Text(why, color = TextMain, fontSize = 14.sp, lineHeight = 21.sp,
            modifier = Modifier.fillMaxWidth().padding(top = 6.dp).background(bg, RoundedCornerShape(12.dp)).padding(10.dp))
        Body(stringResource(R.string.rec_d_note), TextDim, 11.sp)
    }
}


// ---------------------------------------------------------------- price range (experimental 80 % close interval)
@Composable
private fun rangeHorizonName(h: String): String = stringResource(if (h == "4h") R.string.rng_h4 else R.string.rng_h24)

@Composable
private fun RangeStrip(r: RangeInfo, onClick: () -> Unit) {
    val h = r.display?.let { r.horizons[it] } ?: return
    val shape = RoundedCornerShape(16.dp)
    Row(Modifier.fillMaxWidth().background(Card, shape).border(1.5.dp, Gold, shape).clickable(role = Role.Button, onClick = onClick)
        .padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("▮▮", color = WaitGold, fontSize = 11.sp)
        val txt = if (h.eventName != null) stringResource(R.string.rng_event_strip)
                  else stringResource(R.string.rng_strip, rangeHorizonName(h.horizon), ltr(recPrice(h.low)), ltr(recPrice(h.high)))
        Text(txt, color = TextMain, fontSize = 13.sp, fontWeight = FontWeight.Bold, maxLines = 1,
            overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        Text("ⓘ", color = WaitGold, fontSize = 14.sp)
        Text(stringResource(R.string.rng_exp), color = WaitGold, fontSize = 11.sp, fontWeight = FontWeight.Bold,
            modifier = Modifier.background(Color(0xFF3D3010), RoundedCornerShape(10.dp)).padding(horizontal = 8.dp, vertical = 2.dp))
    }
}

@Composable
private fun RangeDialog(s: UiState, now: Double?, onClose: () -> Unit) {
    val r = s.range?.takeIf { it.asset == s.asset }
    var tab by remember { mutableStateOf(r?.display ?: "24h") }
    DialogFrame(stringResource(R.string.rng_title), onClose) {
        Text(stringResource(R.string.rng_exp), color = Color(0xFF7FA7FF), fontSize = 11.sp, fontWeight = FontWeight.Bold,
            modifier = Modifier.background(Color(0xFF1D2A3D), RoundedCornerShape(8.dp)).padding(horizontal = 8.dp, vertical = 2.dp))
        Row(Modifier.fillMaxWidth().border(1.dp, Track, RoundedCornerShape(18.dp)).padding(3.dp)) {
            listOf("4h", "24h").forEach { k ->
                val on = tab == k
                Text(rangeHorizonName(k), color = if (on) Color.Black else TextMain, fontSize = 13.sp,
                    fontWeight = if (on) FontWeight.Bold else FontWeight.Normal, textAlign = TextAlign.Center,
                    modifier = Modifier.weight(1f).background(if (on) WaitGold else Color.Transparent, RoundedCornerShape(15.dp))
                        .clickable(role = Role.Tab) { tab = k }.padding(vertical = 5.dp))
            }
        }
        val h = r?.horizons?.get(tab)
        when {
            r == null -> Body(stringResource(R.string.rng_unavailable), TextDim, 13.sp)
            h == null -> Text(stringResource(R.string.rng_na, rangeHorizonName(tab), recAssetName(s.asset)), color = TextDim,
                fontSize = 13.sp, lineHeight = 19.sp, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().background(Color(0xFF16161B), RoundedCornerShape(12.dp)).padding(12.dp))
            h.eventName != null -> {
                val tm = h.eventTime?.let { t -> try { ltr(DateTimeFormatter.ofPattern("HH:mm").format(Instant.parse(t.replace("+00:00", "Z")).atZone(ZoneId.systemDefault()))) } catch (e: Exception) { "" } } ?: ""
                Column(Modifier.fillMaxWidth().background(Color(0xFF3D3010), RoundedCornerShape(12.dp)).padding(12.dp),
                    horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(stringResource(R.string.rng_event_title, ltr(h.eventName), tm), color = WaitGold, fontSize = 14.sp,
                        fontWeight = FontWeight.Bold, textAlign = TextAlign.Center)
                    Text(stringResource(R.string.rng_event_body), color = TextMain, fontSize = 13.sp, lineHeight = 19.sp, textAlign = TextAlign.Center)
                }
                Body(stringResource(R.string.rng_event_hist), TextDim, 11.sp)
            }
            else -> {
                Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(stringResource(R.string.rng_after, rangeHorizonName(tab)), color = TextDim, fontSize = 13.sp)
                    Text(stringResource(R.string.rng_between, ltr(recPrice(h.low)), ltr(recPrice(h.high))), color = WaitGold,
                        fontSize = 24.sp, fontWeight = FontWeight.Black)
                }
                // the band (low..high) on a wider scale, with the current price marked
                val p = now ?: h.closeAtIssue
                val pad = (h.high - h.low) * 0.45
                val lo0 = minOf(h.low - pad, p); val hi0 = maxOf(h.high + pad, p)
                androidx.compose.foundation.Canvas(Modifier.fillMaxWidth().height(34.dp).padding(horizontal = 6.dp)) {
                    val x = { v: Double -> (size.width * ((v - lo0) / (hi0 - lo0))).toFloat() }
                    val cy = size.height * 0.62f
                    val bh = 6.dp.toPx()
                    drawRoundRect(Track, androidx.compose.ui.geometry.Offset(0f, cy - bh), androidx.compose.ui.geometry.Size(size.width, bh * 2),
                        androidx.compose.ui.geometry.CornerRadius(bh, bh))
                    drawRoundRect(Color(0xFF5A4A1C), androidx.compose.ui.geometry.Offset(x(h.low), cy - bh),
                        androidx.compose.ui.geometry.Size(x(h.high) - x(h.low), bh * 2), androidx.compose.ui.geometry.CornerRadius(bh, bh))
                    drawRoundRect(Gold, androidx.compose.ui.geometry.Offset(x(h.low), cy - bh),
                        androidx.compose.ui.geometry.Size(x(h.high) - x(h.low), bh * 2), androidx.compose.ui.geometry.CornerRadius(bh, bh),
                        style = androidx.compose.ui.graphics.drawscope.Stroke(width = 4f))
                    drawLine(Color.White, androidx.compose.ui.geometry.Offset(x(p), 0f), androidx.compose.ui.geometry.Offset(x(p), size.height), 5f)
                }
                Row(Modifier.fillMaxWidth()) {
                    Text(ltr(recPrice(h.low)), color = SellRed, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                    Text(stringResource(R.string.rng_now, ltr(recPrice(p))), color = TextMain, fontSize = 11.sp,
                        textAlign = TextAlign.Center, modifier = Modifier.weight(1f))
                    Text(ltr(recPrice(h.high)), color = BuyGreen, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
                Body(stringResource(R.string.rng_note), TextMain, 13.sp)
                val tr = s.rangeTracks[s.asset]?.get(tab) ?: RangeTrack(0, 0, 0)
                Column(Modifier.fillMaxWidth().background(Color(0xFF16161B), RoundedCornerShape(12.dp)).padding(10.dp)) {
                    Text(stringResource(R.string.rng_live, tr.inside, tr.settled), color = WaitGold, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                    Text(stringResource(R.string.rng_live_note), color = TextDim, fontSize = 12.sp)
                }
            }
        }
        Body(stringResource(R.string.rng_disc), TextDim, 11.sp)
    }
}
