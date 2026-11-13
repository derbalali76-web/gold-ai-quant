package com.goldaiquant.app

import android.content.Context
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
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

/**
 * Renders the real screen with real backend fixtures on small / medium / large phones, in every supported language
 * (RTL for Arabic), and checks the interactions: horizon switching, level / probability / trend / details dialogs.
 */
@RunWith(AndroidJUnit4::class)
class ScreenSizesTest {
    @get:Rule val rule = createComposeRule()

    private val target: Context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private fun ctx(lang: Lang): Context = LanguageStore.wrap(target, lang)
    private fun str(lang: Lang, id: Int): String = ctx(lang).getString(id)

    private fun decision(name: String): Decision = DecisionParser.parse(
        InstrumentationRegistry.getInstrumentation().context.assets.open("fixtures/$name").bufferedReader().readText())

    private fun show(name: String, w: Int, h: Int, lang: Lang = Lang.EN, horizon: String = "HOURS"): Decision {
        val d = decision(name)
        val c = ctx(lang)
        rule.setContent {
            CompositionLocalProvider(LocalContext provides c,
                LocalLayoutDirection provides if (lang.rtl) LayoutDirection.Rtl else LayoutDirection.Ltr) {
                GoldTheme {
                    var state by androidx.compose.runtime.remember {
                        androidx.compose.runtime.mutableStateOf(UiState(decision = d, receivedAt = Instant.now(), selectedHorizon = horizon))
                    }
                    Box(Modifier.size(w.dp, h.dp)) {
                        GoldContent(state, lang, {}, {}, { _, _ -> }, {}, { h2 -> state = state.copy(selectedHorizon = h2) }, {})
                    }
                }
            }
        }
        return d
    }

    private fun shown(text: String) = rule.onAllNodesWithTextCompat(text).isNotEmpty()

    private fun androidx.compose.ui.test.junit4.ComposeContentTestRule.onAllNodesWithTextCompat(t: String) =
        onAllNodesWithText(t).fetchSemanticsNodes()

    private fun essentials(d: Decision, lang: Lang, actionRes: Int) {
        assertTrue(shown(str(lang, R.string.ask)))
        assertTrue(shown(str(lang, actionRes)))
        assertTrue(shown(String.format(java.util.Locale.US, "%.2f", d.quote!!)))
        assertTrue(shown(str(lang, R.string.lv_supports)))
        assertTrue(shown(str(lang, R.string.lv_resistances)))
    }

    @Test fun smallPhoneWait() { essentials(show("wait_demo.json", 360, 640), Lang.EN, R.string.a_wait) }
    @Test fun mediumPhoneBuy() { essentials(show("live_qualified_stub.json", 393, 851), Lang.EN, R.string.a_buy) }
    @Test fun largePhoneSell() { essentials(show("sell_demo_stub.json", 430, 932), Lang.EN, R.string.a_sell) }

    // One test per language: Compose allows a single setContent per test.
    private fun language(lang: Lang) = essentials(show("wait_demo.json", 360, 640, lang), lang, R.string.a_wait)
    @Test fun languageEnglish() = language(Lang.EN)
    @Test fun languageArabic() = language(Lang.AR)
    @Test fun languageFrench() = language(Lang.FR)
    @Test fun languageSpanish() = language(Lang.ES)
    @Test fun languagePortuguese() = language(Lang.PT)

    @Test fun probabilitiesOnlyWhenCalibrated() {
        show("live_qualified_stub.json", 393, 851)
        assertTrue(shown("58%"))
    }

    @Test fun demoNeverShowsProbabilities() {
        show("buy_demo_stub.json", 393, 851)
        assertTrue(shown(str(Lang.EN, R.string.prob_na)))
        assertTrue(shown(str(Lang.EN, R.string.demo_banner)))
    }

    @Test fun unavailableState() {
        show("unavailable_live.json", 360, 640)
        assertTrue(shown(str(Lang.EN, R.string.a_unavailable)))
    }

    @Test fun tappingAHorizonSwitchesTheWholeMainCard() {
        show("live_qualified_stub.json", 393, 851)
        assertTrue(shown("58%")) // HOURS: calibrated probabilities
        rule.onNodeWithContentDescription(str(Lang.EN, R.string.cd_horizon).format(str(Lang.EN, R.string.h_week))).performClick()
        rule.waitForIdle()
        assertTrue(rule.onAllNodes(hasContentDescription(str(Lang.EN, R.string.cd_horizon_selected).format(str(Lang.EN, R.string.h_week))))
            .fetchSemanticsNodes().isNotEmpty())
        assertTrue(shown(str(Lang.EN, R.string.prob_horizon))) // WEEK has no calibrated probabilities
    }

    @Test fun probabilityCardOpensItsExplanation() {
        show("live_qualified_stub.json", 393, 851)
        rule.onNodeWithText(str(Lang.EN, R.string.prob_title)).performClick()
        rule.waitForIdle()
        assertTrue(shown(str(Lang.EN, R.string.prob_dialog_title) + " · " + str(Lang.EN, R.string.h_hours)))
    }

    @Test fun trendCardOpensItsDialog() {
        show("live_qualified_stub.json", 393, 851)
        rule.onNodeWithText(str(Lang.EN, R.string.tr_title)).performClick()
        rule.waitForIdle()
        assertTrue(shown(str(Lang.EN, R.string.tr_dialog) + " · " + str(Lang.EN, R.string.h_hours)))
    }

    @Test fun detailsButtonOpensExpandedAnalysis() {
        show("wait_demo.json", 393, 851)
        rule.onNodeWithText(str(Lang.EN, R.string.details) + " ⌄").performClick()
        rule.waitForIdle()
        assertTrue(rule.onAllNodesWithText(str(Lang.EN, R.string.details_dialog), substring = true)
            .fetchSemanticsNodes().isNotEmpty())
    }
}
