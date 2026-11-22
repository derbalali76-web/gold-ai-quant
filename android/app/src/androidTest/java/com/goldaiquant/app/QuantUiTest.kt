package com.goldaiquant.app

import android.content.Context
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.goldaiquant.app.ui.DecisionBlock
import com.goldaiquant.app.ui.GoldTheme
import com.goldaiquant.app.ui.RadarTile
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Phase 4 (approved 2026-11-22): holder / cash × qualified / not qualified, rendered for real in Arabic (RTL). */
@RunWith(AndroidJUnit4::class)
class QuantUiTest {
    @get:Rule val rule = createComposeRule()
    private val target: Context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val ar: Context get() = LanguageStore.wrap(target, Lang.AR)
    private fun s(id: Int, vararg a: Any) = ar.getString(id, *a)

    private val wait = """{"verdict":"WAIT","signal_id":"S-1","plan":null,"why":["not_yet_qualified"]}"""
    private val sell = """{"verdict":"SELL_THEN_REBUY","signal_id":"S-1","why":[],
      "plan":{"sell":61240.0,"rebuy_at":59900.0,"invalidate_above":62600.0,"duration_h":72,"adaptive":true}}"""
    private val buy = """{"verdict":"BUY_LIMIT","signal_id":"S-1","why":[],
      "plan":{"entry":59900.0,"target":60290.0,"invalidate_below":59300.0,"duration_h":72,"adaptive":true}}"""

    private fun state(holder: String, cash: String, qualified: Boolean): AssetState = Unified.parse("""{"schema":"decision-state-2",
      "updated_at":"2026-11-22T12:00:00Z","assets":{"BTC":{"price":{"value":61240.0,"at":"2026-11-22T11:30:00Z"},
      "gates":{"ok":true,"reasons":[]},"view":{"holder":$holder,"cash":$cash},
      "radar":[{"id":"S-1","source":"advice-0.1.0","state":"${if (qualified) "QUALIFIED" else "FORMING"}","level":59900.0}]}}}""")!!.assets["BTC"]!!

    private fun show(st: AssetState, hold: Boolean) = rule.setContent {
        CompositionLocalProvider(LocalContext provides ar, LocalLayoutDirection provides LayoutDirection.Rtl) {
            GoldTheme { Column(Modifier.width(360.dp)) {
                DecisionBlock(st, hold)
                RadarTile(st, Modifier.width(120.dp)) {}
            } }
        }
    }

    private fun count(t: String) = rule.onAllNodesWithText(t, substring = true).fetchSemanticsNodes().size

    @Test fun holderQualifiedShowsPreemptiveSellPlan() {
        show(state(sell, wait, true), hold = true)
        rule.onNodeWithText(s(R.string.q_sell_rebuy)).assertIsDisplayed()
        rule.onNodeWithText(s(R.string.p_rebuy)).assertIsDisplayed()
        rule.onNodeWithText(s(R.string.p_inval_above)).assertIsDisplayed()
        rule.onNodeWithText(s(R.string.p_dur_val, 72)).assertIsDisplayed()
        rule.onNodeWithText(s(R.string.rd_tile_q, 1)).assertIsDisplayed()
        assertEquals(0, count(s(R.string.q_why_title)))
    }

    @Test fun holderWithoutQualifiedShowsWaitAndWhy() {
        show(state(wait, wait, false), hold = true)
        rule.onNodeWithText(s(R.string.wd_wait)).assertIsDisplayed()
        rule.onNodeWithText(s(R.string.q_why_title)).assertIsDisplayed()
        rule.onNodeWithText(s(R.string.rd_tile_f, 1)).assertIsDisplayed()
        assertEquals(0, count(s(R.string.q_sell_rebuy)))
    }

    @Test fun cashQualifiedShowsLimitBuyNeverSell() {
        show(state(wait, buy, true), hold = false)
        rule.onNodeWithText(s(R.string.p_entry)).assertIsDisplayed()
        rule.onNodeWithText(s(R.string.p_inval_below)).assertIsDisplayed()
        assertEquals(0, count(s(R.string.q_sell_rebuy)))
    }

    @Test fun cashWithoutQualifiedShowsWait() {
        show(state(wait, wait, false), hold = false)
        rule.onNodeWithText(s(R.string.wd_wait)).assertIsDisplayed()
        rule.onNodeWithText(s(R.string.q_wait_cash_sub)).assertIsDisplayed()
        assertEquals(0, count(s(R.string.q_sell_rebuy)))
    }
}
