package com.goldaiquant.app.ui

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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
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
import com.goldaiquant.app.Decision
import com.goldaiquant.app.Level
import com.goldaiquant.app.MainViewModel
import com.goldaiquant.app.UiState
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
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
private val stamp = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss", Locale.US)
private fun Instant.hms(): String = clock.format(atZone(ZoneId.systemDefault()))
private fun Instant.full(): String = stamp.format(atZone(ZoneId.systemDefault()))
private fun Double.p2(): String = String.format(Locale.US, "%.2f", this)
/** Keeps numbers, signs and ranges in reading order inside the RTL layout. */
fun ltr(s: String): String = "⁦$s⁩"

private enum class Health(val label: String, val color: Color) {
    LIVE("بيانات حية", BuyGreen), STALE("بيانات متأخرة", WaitGold), DEMO("بيانات تجريبية", WaitGold),
    NONE("غير متاحة", SellRed), SAVED("محفوظ — ليس حديثاً", Grey)
}

private fun health(s: UiState): Health {
    val d = s.decision
    return when {
        s.error != null || d == null -> Health.NONE
        s.decisionFromCache -> Health.SAVED
        d.isDemo -> Health.DEMO
        d.action == Action.UNAVAILABLE && d.quote == null -> Health.NONE
        !d.isFresh -> Health.STALE
        else -> Health.LIVE
    }
}

// ---------------------------------------------------------------- screen
@Composable
fun GoldScreen(vm: MainViewModel) {
    val s by vm.state.collectAsStateWithLifecycle()
    GoldContent(s, onAsk = vm::ask, onNextDemo = vm::nextDemoMoment, onSave = { u, t -> vm.setServerUrl(u); vm.setToken(t) },
        onLive = vm::setLiveMode)
}

/** Stateless screen (also used by the UI tests on several screen sizes). */
@Composable
fun GoldContent(s: UiState, onAsk: () -> Unit, onNextDemo: () -> Unit, onSave: (String, String) -> Unit,
                onLive: (Boolean) -> Unit) {
    var showDetails by remember { mutableStateOf(false) }
    var showSettings by remember { mutableStateOf(false) }
    BoxWithConstraints(Modifier.fillMaxSize().background(Bg).safeDrawingPadding()) {
        // Compact layout on short screens: secondary details are dropped instead of shrinking the text.
        val compact = maxHeight < 700.dp
        val gap = if (compact) 6.dp else 8.dp
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(gap),
        ) {
            TopBar(s, compact) { showSettings = true }
            val d = s.decision
            Row(horizontalArrangement = Arrangement.spacedBy(gap)) {
                PriceCard(d, s, Modifier.weight(1.1f))
                TrendCard(d, Modifier.weight(1f))
            }
            if (d?.isDemo == true) Text("تجريبي: أسعار اصطناعية — ليست توصيات حقيقية",
                color = Color.Black, fontSize = 12.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().background(WaitGold, RoundedCornerShape(8.dp)).padding(vertical = 4.dp))
            AskButton(s.loading, compact, onAsk)
            s.error?.let { ErrorStrip(it) }
            if (d != null) {
                Row(horizontalArrangement = Arrangement.spacedBy(gap)) {
                    DecisionCard(d, s, compact, Modifier.weight(1.45f))
                    ProbabilityCard(d, Modifier.weight(1f))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(gap)) {
                    LevelsCard("الدعوم", BuyGreen, d.levels?.supports.orEmpty(), d.levels?.validated == true,
                        if (compact) 2 else 3, Modifier.weight(1f))
                    LevelsCard("المقاومات", SellRed, d.levels?.resistances.orEmpty(), d.levels?.validated == true,
                        if (compact) 2 else 3, Modifier.weight(1f))
                }
                ReasonCard(d) { showDetails = true }
            } else if (s.error == null) {
                Text("اضغط «ماذا أفعل؟» للحصول على تحليل السوق الحالي", color = TextDim, fontSize = 14.sp,
                    textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(16.dp))
            }
            Text("للتداول الورقي والبحث فقط. لا تنفيذ للصفقات ولا ضمان لأي نتيجة.", color = TextDim, fontSize = 10.sp,
                textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        }
    }
    if (showDetails) s.decision?.let { DetailsDialog(it) { showDetails = false } }
    if (showSettings) SettingsDialog(s, onNextDemo, onSave, onLive) { showSettings = false }
}

// ---------------------------------------------------------------- building blocks
@Composable
private fun Panel(modifier: Modifier = Modifier, edge: Color = CardEdge, content: @Composable () -> Unit) {
    Box(modifier.background(Card, RoundedCornerShape(14.dp)).border(1.dp, edge, RoundedCornerShape(14.dp))
        .padding(horizontal = 10.dp, vertical = 8.dp)) { content() }
}

@Composable
private fun Bar(fraction: Float, color: Color, modifier: Modifier = Modifier, height: Dp = 6.dp) {
    Box(modifier.height(height).background(Track, RoundedCornerShape(50))) {
        Box(Modifier.fillMaxHeight().fillMaxWidth(fraction.coerceIn(0f, 1f)).background(color, RoundedCornerShape(50)))
    }
}

@Composable
private fun TopBar(s: UiState, compact: Boolean, onSettings: () -> Unit) {
    val h = health(s)
    // RTL row: status pill on the right, title in the middle, settings on the left (no overlap on narrow screens)
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Row(Modifier.border(1.dp, h.color, RoundedCornerShape(50)).padding(horizontal = 8.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).background(h.color, CircleShape))
            Spacer(Modifier.width(5.dp))
            Text(h.label, color = TextMain, fontSize = 11.sp, maxLines = 1)
        }
        Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
            Text("GOLD AI QUANT", color = Gold, fontWeight = FontWeight.ExtraBold, fontSize = 18.sp, maxLines = 1)
            if (!compact) Text("الذكاء الاصطناعي للذهب", color = TextDim, fontSize = 10.sp)
        }
        Box(Modifier.size(34.dp).border(1.dp, Gold, CircleShape)
            .clickable(onClick = onSettings).semantics { contentDescription = "الإعدادات" },
            contentAlignment = Alignment.Center) { Text("⚙", color = Gold, fontSize = 17.sp) }
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
            Text("آخر تحديث ${t?.hms() ?: "—"}", color = TextDim, fontSize = 10.sp, maxLines = 1)
        }
    }
}

@Composable
private fun TrendCard(d: Decision?, modifier: Modifier) {
    val t = d?.trend
    val color = when (t?.direction) { "UP" -> BuyGreen; "DOWN" -> SellRed; "SIDEWAYS" -> WaitGold; else -> Grey }
    Panel(modifier) {
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text("اتجاه السوق", color = TextMain, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            Text(t?.labelAr ?: "—", color = color, fontSize = 22.sp, fontWeight = FontWeight.ExtraBold)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("قوة الاتجاه:", color = TextDim, fontSize = 11.sp, modifier = Modifier.weight(1f))
                Text(t?.strength?.let { ltr("$it/100") } ?: "—", color = TextMain, fontSize = 12.sp, fontWeight = FontWeight.Bold)
            }
            Bar((t?.strength ?: 0) / 100f, color, Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun AskButton(loading: Boolean, compact: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(40.dp)
    Box(Modifier.fillMaxWidth().height(if (compact) 60.dp else 70.dp)
        .background(Brush.verticalGradient(listOf(GoldLight, Gold, Color(0xFFB8901F))), shape)
        .border(1.dp, GoldLight, shape).clickable(enabled = !loading, onClick = onClick)
        .semantics { contentDescription = "ماذا أفعل؟" }, contentAlignment = Alignment.Center) {
        if (loading) Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(color = Color.Black, strokeWidth = 3.dp, modifier = Modifier.size(24.dp))
            Spacer(Modifier.width(10.dp))
            Text("جارٍ التحليل…", color = Color.Black, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        } else Row(verticalAlignment = Alignment.CenterVertically) {
            Text("ماذا أفعل؟", color = Color.Black, fontSize = if (compact) 25.sp else 28.sp, fontWeight = FontWeight.ExtraBold)
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
private fun ErrorStrip(msg: String) {
    Text(msg, color = TextMain, fontSize = 13.sp,
        modifier = Modifier.fillMaxWidth().background(SellRed.copy(alpha = 0.22f), RoundedCornerShape(10.dp)).padding(8.dp))
}

@Composable
private fun KV(k: String, v: String, size: TextUnit = 13.sp) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(k, color = TextDim, fontSize = 12.sp, modifier = Modifier.weight(1f), maxLines = 1)
        Text(v, color = TextMain, fontSize = size, fontWeight = FontWeight.SemiBold, maxLines = 1)
    }
}

private fun hoursLabel(min: Int?): String = when {
    min == null -> "—"
    min % 60 == 0 -> "حتى ${min / 60} ساعات"
    else -> "حتى $min دقيقة"
}

@Composable
private fun DecisionCard(d: Decision, s: UiState, compact: Boolean, modifier: Modifier) {
    val expired = d.isExpired(Instant.now())
    val (title, color, sub) = when (d.action) {
        Action.BUY -> Triple("شراء", BuyGreen, "اجتازت محكمة القرار")
        Action.SELL -> Triple("بيع", SellRed, "اجتازت محكمة القرار")
        Action.WAIT -> Triple("انتظار", WaitGold, "لا توجد صفقة مؤهلة الآن")
        Action.UNAVAILABLE -> Triple("غير متاح", Grey, "البيانات غير كافية أو متأخرة")
    }
    Panel(modifier, edge = color) {
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(title, color = color, fontSize = if (d.action == Action.UNAVAILABLE) 22.sp else 30.sp,
                    fontWeight = FontWeight.Black, maxLines = 1)
                Spacer(Modifier.width(8.dp))
                Text(sub, color = TextDim, fontSize = 11.sp, maxLines = 2)
            }
            if (s.decisionFromCache || expired)
                Text("قرار سابق — اضغط «ماذا أفعل؟» للتحديث", color = WaitGold, fontSize = 11.sp)
            when (d.action) {
                Action.BUY, Action.SELL -> {
                    KV("الدخول", ltr("${d.entryMin!!.p2()} – ${d.entryMax!!.p2()}"))
                    KV("وقف الخسارة", d.stopLoss!!.p2())
                    KV("الهدف", d.tp1!!.p2())
                    KV("المدة المتوقعة", hoursLabel(d.horizonMinutes))
                }
                Action.WAIT -> {
                    val better = d.waitForPrice ?: d.alternativeEntryPrice
                    if (better != null) KV("سعر إعادة التقييم", better.p2())
                    d.reevaluateAr.take(if (compact) 1 else 2).forEach {
                        Text("• $it", color = TextMain, fontSize = 11.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                }
                Action.UNAVAILABLE -> Text(d.warningAr ?: "", color = TextMain, fontSize = 12.sp, maxLines = 3)
            }
        }
    }
}

@Composable
private fun ProbabilityCard(d: Decision, modifier: Modifier) {
    Panel(modifier) {
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("الاحتمالات", color = TextMain, fontSize = 13.sp, fontWeight = FontWeight.Bold)
            val o = d.displayableOutcomes
            if (o == null) {
                Text("غير متاحة", color = WaitGold, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                Text(if (d.isDemo) "لا تُعرض في الوضع التجريبي" else "لم تجتز اختبارات المعايرة بعد",
                    color = TextDim, fontSize = 11.sp)
            } else {
                ProbRow("الوصول للهدف", o.first, BuyGreen)
                ProbRow("وقف الخسارة", o.second, SellRed)
                ProbRow("عدم الوصول", o.third, Color(0xFFB8BCC4))
                Text("معايرة خارج العينة: ${d.calibrationSamples} حالة", color = TextDim, fontSize = 9.sp)
            }
        }
    }
}

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

private fun labelFill(l: Level): Float = l.strength?.let { it / 100f } ?: when (l.labelAr) {
    "قوي" -> 0.85f; "متوسط" -> 0.55f; "ضعيف" -> 0.25f; else -> 0f
}

@Composable
private fun LevelsCard(title: String, color: Color, items: List<Level>, validated: Boolean, rows: Int, modifier: Modifier) {
    Panel(modifier, edge = color.copy(alpha = 0.6f)) {
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(title, color = color, fontSize = 15.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                if (!validated) Text("قوة تقديرية", color = TextDim, fontSize = 9.sp)
            }
            if (items.isEmpty()) Text("لا مستويات قريبة", color = TextDim, fontSize = 11.sp)
            items.take(rows).forEach { l ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(l.name, color = color, fontSize = 12.sp, fontWeight = FontWeight.Bold, modifier = Modifier.width(24.dp))
                    Text(l.price.p2(), color = TextMain, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.weight(1f))
                    Column(horizontalAlignment = Alignment.End, modifier = Modifier.width(54.dp)) {
                        Text(l.strength?.let { "$it" } ?: l.labelAr, color = TextDim, fontSize = 10.sp, maxLines = 1)
                        Segments(labelFill(l), color)
                    }
                }
            }
        }
    }
}

@Composable
private fun Segments(fill: Float, color: Color) {
    val n = (fill * 6 + 0.5f).toInt().coerceIn(0, 6)
    Row(horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        repeat(6) { i -> Box(Modifier.size(width = 6.dp, height = 7.dp)
            .background(if (i < n) color else Track, RoundedCornerShape(2.dp))) }
    }
}

@Composable
private fun ReasonCard(d: Decision, onDetails: () -> Unit) {
    Panel(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("سبب القرار:", color = Gold, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                Text(d.reasonShortAr ?: d.warningAr ?: "", color = TextMain, fontSize = 13.sp, lineHeight = 18.sp,
                    maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
            Spacer(Modifier.width(8.dp))
            Box(Modifier.border(1.dp, Gold, RoundedCornerShape(20.dp)).clickable(onClick = onDetails)
                .padding(horizontal = 12.dp, vertical = 8.dp)) {
                Text("التفاصيل ⌄", color = TextMain, fontSize = 13.sp)
            }
        }
    }
}

// ---------------------------------------------------------------- in-screen dialogs (no extra pages)
@Composable
private fun DetailsDialog(d: Decision, onClose: () -> Unit) {
    Dialog(onDismissRequest = onClose) {
        Column(Modifier.fillMaxWidth().heightIn(max = 620.dp).background(Card, RoundedCornerShape(16.dp))
            .border(1.dp, Gold, RoundedCornerShape(16.dp)).verticalScroll(rememberScrollState()).padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Text("التحليل الكامل", color = Gold, fontSize = 17.sp, fontWeight = FontWeight.Bold)
            d.marketRegime?.let { Item("حالة السوق", it) }
            d.trend?.let { t ->
                Item("الاتجاه حسب الإطار", t.perTimeframe.entries.joinToString("، ") { "${it.key}: ${it.value}" })
                Text("قوة الاتجاه درجة تحليلية وليست احتمالاً لاستمراره.", color = TextDim, fontSize = 11.sp)
            }
            if (d.supporting.isNotEmpty() || d.contrary.isNotEmpty()) Section("الأدلة")
            d.supporting.forEach { Text("✔ ${it.textAr}", color = BuyGreen, fontSize = 12.sp) }
            d.contrary.forEach { Text("✖ ${it.textAr}", color = SellRed, fontSize = 12.sp) }
            if (d.court.isNotEmpty()) {
                Section("محكمة القرار")
                val names = mapOf("evidence" to "الأدلة", "statistics" to "الإحصاء", "risk_governor" to "حارس المخاطر")
                d.court.forEach { j ->
                    Text("${if (j.passed) "✔" else "✖"} ${names[j.judge] ?: j.judge}" + (j.reasonsAr.firstOrNull()?.let { ": $it" } ?: ""),
                        color = if (j.passed) BuyGreen else SellRed, fontSize = 12.sp)
                }
            }
            if (d.reevaluateAr.isNotEmpty()) {
                Section("متى نعيد التقييم")
                d.reevaluateAr.forEach { Text("• $it", color = TextMain, fontSize = 12.sp) }
            }
            d.levels?.let { lv ->
                Section("الدعوم والمقاومات")
                (lv.supports + lv.resistances).forEach { l ->
                    Text("${l.name}: ${ltr("${l.zoneLow.p2()}–${l.zoneHigh.p2()}")} • ${l.strength?.let { "قوة $it/100" } ?: l.labelAr}" +
                        " • اختبارات ${l.tests} • ${l.timeframes.joinToString("/")}" + if (l.brokenRecently) " • كُسر مؤخراً" else "",
                        color = TextMain, fontSize = 11.sp)
                }
                lv.validationAr?.let { Text(it, color = TextDim, fontSize = 11.sp) }
                Text("القوة ترتيب مقارنة بالمستويات التاريخية، وليست احتمال ارتداد.", color = TextDim, fontSize = 11.sp)
            }
            if (d.horizonProbs.isNotEmpty() && d.displayableOutcomes != null) {
                Section("الاحتمالات حسب المدة")
                d.horizonProbs.forEach { h ->
                    Text("${h.minutes} د: هدف ${(h.pTarget * 100).toInt()}% • وقف ${(h.pStop * 100).toInt()}% • لا شيء ${(h.pNeither * 100).toInt()}%",
                        color = TextMain, fontSize = 11.sp)
                }
            }
            d.reliabilityAr?.let { Item("موثوقية النموذج", it) }
            if (d.budgetUsed != null && d.budgetLimit != null) Item("ميزانية عدم اليقين", "${d.budgetUsed.p2()} من ${d.budgetLimit.p2()}")
            d.alternativeEntryNoteAr?.let { Item("الدخول البديل", it) }
            if (d.missingData.isNotEmpty()) {
                Section("بيانات ناقصة")
                d.missingData.forEach { Text("• $it", color = TextDim, fontSize = 11.sp) }
            }
            Text("${d.provider} • ${d.quoteTime?.full() ?: "—"} • ${d.modelVersion} • ${d.decisionId}", color = TextDim, fontSize = 10.sp)
            TextButton(onClick = onClose, modifier = Modifier.align(Alignment.End)) { Text("إغلاق", color = Gold) }
        }
    }
}

@Composable
private fun Section(t: String) = Text(t, color = Gold, fontSize = 13.sp, fontWeight = FontWeight.Bold,
    modifier = Modifier.padding(top = 4.dp))

@Composable
private fun Item(k: String, v: String) {
    Text(k, color = TextDim, fontSize = 11.sp)
    Text(v, color = TextMain, fontSize = 12.sp)
}

@Composable
private fun SettingsDialog(s: UiState, onNextDemo: () -> Unit, onSave: (String, String) -> Unit,
                           onLive: (Boolean) -> Unit, onClose: () -> Unit) {
    Dialog(onDismissRequest = onClose) {
        Column(Modifier.fillMaxWidth().background(Card, RoundedCornerShape(16.dp)).border(1.dp, Gold, RoundedCornerShape(16.dp))
            .padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("الإعدادات", color = Gold, fontSize = 17.sp, fontWeight = FontWeight.Bold)
            var url by remember(s.serverUrl) { mutableStateOf(s.serverUrl) }
            var tok by remember(s.token) { mutableStateOf(s.token) }
            OutlinedTextField(value = url, onValueChange = { url = it }, singleLine = true,
                label = { Text("عنوان خادم التحليل") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(value = tok, onValueChange = { tok = it }, singleLine = true,
                label = { Text("الرمز السري (اختياري)") }, modifier = Modifier.fillMaxWidth())
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("الوضع الحي", color = TextMain, fontSize = 14.sp, modifier = Modifier.weight(1f))
                Switch(checked = s.liveMode, onCheckedChange = onLive)
            }
            if (!s.liveMode) TextButton(onClick = { onNextDemo(); onClose() }) {
                Text("لحظة تجريبية أخرى (${s.demoStep + 1}/40)", color = TextDim)
            }
            Row {
                TextButton(onClick = { onSave(url, tok); onClose() }) { Text("حفظ", color = Gold) }
                TextButton(onClick = onClose) { Text("إلغاء", color = TextDim) }
            }
        }
    }
}
