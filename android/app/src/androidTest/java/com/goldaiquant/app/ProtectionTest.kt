package com.goldaiquant.app

import android.os.Build
import android.view.WindowManager
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Runs on the emulator matrix (API 30, 35 = Android 15, 36 = Android 16). */
@RunWith(AndroidJUnit4::class)
class ProtectionTest {
    @get:Rule val rule = createAndroidComposeRule<MainActivity>()

    @Test fun mainWindowIsSecure() {
        rule.activityRule.scenario.onActivity { a ->
            assertTrue("FLAG_SECURE on API ${Build.VERSION.SDK_INT}", Protection.isSecure(a))
            assertTrue(a.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0)
        }
    }

    @Test fun installCodeIsAnonymousAndStable() {
        val ctx = rule.activity
        val a = InstallCode.get(ctx)
        assertTrue(InstallCode.isValid(a))
        assertTrue(a == InstallCode.get(ctx))
        assertTrue(!a.contains("@") && a.none { it.isWhitespace() })
    }

    @Test fun watermarkIsDrawnOnTheMainScreen() {
        rule.waitForIdle()
        rule.onAllNodesWithTag("watermark", useUnmergedTree = true).fetchSemanticsNodes().let {
            assertTrue("watermark present", it.isNotEmpty())
        }
    }
}
