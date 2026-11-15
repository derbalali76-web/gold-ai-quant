package com.goldaiquant.app

import android.app.Activity
import android.content.Context
import android.os.Build
import android.view.WindowManager
import androidx.compose.runtime.Composable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.sp
import java.security.SecureRandom

/**
 * Content protection. What it does: blocks the usual screenshot / screen-recording paths and the recent-apps preview
 * (FLAG_SECURE, also on dialogs), and marks the analysis screens with a faint watermark carrying an anonymous install
 * code. What it cannot do: stop a photo taken with another camera, a rooted / modified device, or other workarounds.
 */
object Protection {
    private const val PREFS = "protection"
    private const val KEY_ALLOW = "allow_screenshots"

    /** Dialog windows follow the same choice as the activity. */
    @Volatile var dialogsSecure: Boolean = true
        private set

    /** Test builds only (debug APK): the owner may allow screenshots to send them for review. Release: never. */
    fun screenshotsAllowed(ctx: Context): Boolean =
        BuildConfig.DEBUG && ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY_ALLOW, false)

    fun setScreenshotsAllowed(ctx: Context, allow: Boolean) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY_ALLOW, allow && BuildConfig.DEBUG).apply()
    }

    fun secure(activity: Activity) {
        if (screenshotsAllowed(activity)) {
            activity.window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
            if (Build.VERSION.SDK_INT >= 33) activity.setRecentsScreenshotEnabled(true)
            dialogsSecure = false
            return
        }
        activity.window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)
        if (Build.VERSION.SDK_INT >= 33) activity.setRecentsScreenshotEnabled(false)
        dialogsSecure = true
    }

    fun isSecure(activity: Activity): Boolean =
        activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0
}

/** Anonymous install code for the watermark: random, made on this phone, never derived from e-mail / phone / name. */
object InstallCode {
    private const val PREFS = "protection"
    private const val KEY = "install_code"
    private const val ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789" // no 0/O/1/I/L confusion

    fun get(ctx: Context): String {
        val p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        p.getString(KEY, null)?.let { if (isValid(it)) return it }
        val code = make(SecureRandom())
        p.edit().putString(KEY, code).apply()
        return code
    }

    fun make(r: java.util.Random): String {
        val c = (0 until 8).map { ALPHABET[r.nextInt(ALPHABET.length)] }.joinToString("")
        return "AQ-${c.take(4)}-${c.drop(4)}"
    }

    fun isValid(s: String) = Regex("AQ-[A-Z2-9]{4}-[A-Z2-9]{4}").matches(s)
}

/** The watermark text for the current screen (null = none, e.g. in tests that do not provide one). */
val LocalWatermark = compositionLocalOf<String?> { null }

/** Faint diagonal repeated text drawn ABOVE the content; it does not take touches and is not read by TalkBack. */
@Composable
fun Modifier.watermark(text: String?): Modifier {
    if (text.isNullOrBlank()) return this
    val measurer = rememberTextMeasurer()
    val layout = remember(text) {
        measurer.measure(text, TextStyle(color = Color(0x12FFFFFF), fontSize = 12.sp))
    }
    return this.testTag("watermark").drawWithContent {
        drawContent()
        val stepX = layout.size.width + 110f
        val stepY = layout.size.height + 170f
        // only the disc that stays visible after rotating around the centre (keeps it to ~100 draws per frame)
        val r = kotlin.math.hypot(size.width, size.height) / 2
        val cx = size.width / 2
        val cy = size.height / 2
        rotate(-28f) {
            var y = cy - r
            var row = 0
            while (y < cy + r) {
                var x = cx - r + (if (row % 2 == 0) 0f else stepX / 2)
                while (x < cx + r) {
                    drawText(layout, topLeft = androidx.compose.ui.geometry.Offset(x, y))
                    x += stepX
                }
                y += stepY
                row++
            }
        }
    }
}
