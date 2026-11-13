package com.goldaiquant.app

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.goldaiquant.app.ui.GoldContent
import com.goldaiquant.app.ui.GoldTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Instant

/** Renders the real screen with real backend fixtures on small / medium / large phone sizes, RTL. */
@RunWith(AndroidJUnit4::class)
class ScreenSizesTest {
    @get:Rule val rule = createComposeRule()

    private fun decision(name: String): Decision = DecisionParser.parse(
        InstrumentationRegistry.getInstrumentation().context.assets.open("fixtures/$name").bufferedReader().readText())

    private fun show(name: String, w: Int, h: Int): Decision {
        val d = decision(name)
        rule.setContent {
            GoldTheme {
                CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
                    Box(Modifier.size(w.dp, h.dp)) {
                        GoldContent(UiState(decision = d, receivedAt = Instant.now()), {}, {}, { _, _ -> }, {})
                    }
                }
            }
        }
        return d
    }

    private fun essentials(d: Decision, title: String) {
        rule.onNodeWithText("ماذا أفعل؟").assertIsDisplayed()
        rule.onNodeWithText(title).assertIsDisplayed()
        rule.onNodeWithText(String.format(java.util.Locale.US, "%.2f", d.quote!!)).assertIsDisplayed()
        rule.onNodeWithText("الدعوم").assertIsDisplayed()
        rule.onNodeWithText("المقاومات").assertIsDisplayed()
    }

    @Test fun smallPhoneWait() { essentials(show("wait_demo.json", 360, 640), "انتظار") }
    @Test fun mediumPhoneBuy() { essentials(show("live_qualified_stub.json", 393, 851), "شراء") }
    @Test fun largePhoneSell() { essentials(show("sell_demo_stub.json", 430, 932), "بيع") }

    @Test fun probabilitiesOnlyWhenCalibrated() {
        show("live_qualified_stub.json", 393, 851)
        rule.onNodeWithText("58%").assertIsDisplayed()
    }

    @Test fun demoNeverShowsProbabilities() {
        show("buy_demo_stub.json", 393, 851)
        assertTrue(rule.onAllNodesWithText("غير متاحة").fetchSemanticsNodes().isNotEmpty())
        rule.onNodeWithText("تجريبي: أسعار اصطناعية — ليست توصيات حقيقية").assertIsDisplayed()
    }

    @Test fun unavailableState() {
        show("unavailable_live.json", 360, 640)
        rule.onNodeWithText("غير متاح").assertIsDisplayed()
    }
}
