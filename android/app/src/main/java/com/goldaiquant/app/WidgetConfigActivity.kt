package com.goldaiquant.app

import android.app.Activity
import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Choose the asset (and, for the wide widget, cash / holder) when a widget is added or edited. */
class WidgetConfigActivity : ComponentActivity() {
    private lateinit var lang: Lang

    override fun attachBaseContext(newBase: Context) {
        lang = LanguageStore.resolve(newBase)
        super.attachBaseContext(LanguageStore.wrap(newBase, lang))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val id = intent?.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)
            ?: AppWidgetManager.INVALID_APPWIDGET_ID
        setResult(Activity.RESULT_CANCELED, Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id))
        if (id == AppWidgetManager.INVALID_APPWIDGET_ID) { finish(); return }
        val info = AppWidgetManager.getInstance(this).getAppWidgetInfo(id)
        val withPosition = info?.provider?.className == PriceWidget::class.java.name
        val p = Widgets.prefs(this)
        setContent {
            CompositionLocalProvider(LocalLayoutDirection provides if (lang.rtl) LayoutDirection.Rtl else LayoutDirection.Ltr) {
                Screen(Widgets.asset(p, id), withPosition, { a -> Widgets.hold(p, a) }) { a, h ->
                    Widgets.setAsset(p, id, a)
                    if (withPosition) Widgets.setHold(p, a, h)
                    Widgets.refreshAll(this)
                    WidgetWorker.enqueue(this, true)
                    setResult(Activity.RESULT_OK, Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id))
                    finish()
                }
            }
        }
    }
}

private val Bg = Color(0xFF0B0B0C)
private val Card = Color(0xFF161618)
private val Edge = Color(0xFF2A2A2D)
private val GoldC = Color(0xFFD4AF37)
private val Txt = Color(0xFFF3F1EA)
private val Dim = Color(0xFF8C8A83)

@Composable
private fun Chips(items: List<Pair<String, String>>, selected: String, onPick: (String) -> Unit) {
    Row(Modifier.fillMaxWidth().background(Card, RoundedCornerShape(14.dp)).border(1.dp, Edge, RoundedCornerShape(14.dp))
        .padding(4.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        items.forEach { (k, label) ->
            val on = k == selected
            Text(label, color = if (on) Color.Black else Txt, fontSize = 15.sp, fontWeight = FontWeight.Bold,
                textAlign = TextAlign.Center, modifier = Modifier.weight(1f)
                    .background(if (on) GoldC else Color.Transparent, RoundedCornerShape(10.dp))
                    .clickable(role = Role.Button) { onPick(k) }.padding(vertical = 11.dp))
        }
    }
}

@Composable
private fun Screen(asset0: String, withPosition: Boolean, holdOf: (String) -> Boolean, onSave: (String, Boolean) -> Unit) {
    var asset by remember { mutableStateOf(asset0) }
    var hold by remember { mutableStateOf(holdOf(asset0)) }
    Column(Modifier.fillMaxSize().background(Bg).padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text(stringResource(R.string.w_cfg_title), color = GoldC, fontSize = 22.sp, fontWeight = FontWeight.ExtraBold)
        Text(stringResource(R.string.w_cfg_asset), color = Dim, fontSize = 13.sp)
        Chips(Widgets.ASSETS.map { it to (if (it == "XAU") "XAU" else it) }, asset) { asset = it; hold = holdOf(it) }
        if (withPosition) {
            Text(stringResource(R.string.w_cfg_pos), color = Dim, fontSize = 13.sp)
            Chips(listOf("C" to stringResource(R.string.sa_cash), "H" to stringResource(R.string.sa_hold)),
                if (hold) "H" else "C") { hold = it == "H" }
            Text(stringResource(R.string.w_cfg_pos_note), color = Dim, fontSize = 11.sp)
        }
        Text(stringResource(R.string.w_cfg_save), color = Color.Black, fontSize = 16.sp, fontWeight = FontWeight.ExtraBold,
            textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().background(GoldC, RoundedCornerShape(14.dp))
                .clickable(role = Role.Button) { onSave(asset, hold) }.padding(vertical = 14.dp))
    }
}
