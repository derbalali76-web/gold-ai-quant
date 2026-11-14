package com.goldaiquant.app

import android.content.Context
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.io.File
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import com.goldaiquant.app.ui.GoldScreen
import com.goldaiquant.app.ui.GoldTheme

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()
    private lateinit var lang: Lang

    private fun crashFile() = File(filesDir, "last_crash.txt")

    override fun attachBaseContext(newBase: Context) {
        val dir = newBase.filesDir
        val prev = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { t, e ->
            try { File(dir, "last_crash.txt").writeText(android.util.Log.getStackTraceString(e).take(6000)) } catch (_: Throwable) {}
            prev?.uncaughtException(t, e)
        }
        lang = LanguageStore.resolve(newBase)
        super.attachBaseContext(LanguageStore.wrap(newBase, lang))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val crash = try { crashFile().takeIf { it.exists() }?.readText() } catch (_: Throwable) { null }
        if (crash != null) { reportCrash(crash); showCrash(crash); return }
        enableEdgeToEdge()
        setContent {
            GoldTheme {
                CompositionLocalProvider(
                    LocalLayoutDirection provides if (lang.rtl) LayoutDirection.Rtl else LayoutDirection.Ltr,
                ) {
                    GoldScreen(vm, lang) { chosen ->
                        if (chosen != lang) {
                            LanguageStore.save(this, chosen)
                            recreate() // reload resources and layout direction in the new language
                        }
                    }
                }
            }
        }
    }

    /** Sends the crash report to the user's own server once, in the background (no personal data: stack trace,
     *  app version, Android version). Never blocks or fails the screen. */
    private fun reportCrash(text: String) {
        val prefs = getSharedPreferences("gold_ai_quant", Context.MODE_PRIVATE)
        if (prefs.getString("crash_sent", null) == text.hashCode().toString()) return
        val url = prefs.getString("server_url", "https://gold-ai-quant.onrender.com") ?: return
        val token = prefs.getString("token", "") ?: ""
        Thread {
            try {
                if (UrlPolicy.check(url) != null) return@Thread
                val body = org.json.JSONObject().put("trace", text.take(6000))
                    .put("app", BuildConfig.VERSION_NAME + " (" + BuildConfig.VERSION_CODE + ")")
                    .put("android", android.os.Build.VERSION.SDK_INT).toString()
                val c = (java.net.URI(url.trimEnd('/') + "/crash").toURL().openConnection() as java.net.HttpURLConnection).apply {
                    requestMethod = "POST"; doOutput = true; connectTimeout = 20_000; readTimeout = 60_000
                    setRequestProperty("Content-Type", "application/json")
                    if (token.isNotBlank()) setRequestProperty("X-Goldquant-Token", token.trim())
                }
                c.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
                if (c.responseCode in 200..299) prefs.edit().putString("crash_sent", text.hashCode().toString()).apply()
                c.disconnect()
            } catch (_: Throwable) {}
        }.start()
    }

    /** Diagnostic screen: shows the previous crash's stack trace (selectable) with a button to clear it and retry. */
    private fun showCrash(text: String) {
        val tv = TextView(this).apply { this.text = text; textSize = 11f; setTextIsSelectable(true); setTextColor(0xFFFFFFFF.toInt()) }
        val btn = Button(this).apply {
            this.text = "OK"
            setOnClickListener { crashFile().delete(); recreate() }
        }
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(24, 80, 24, 24); setBackgroundColor(0xFF000000.toInt()); addView(btn); addView(tv) }
        setContentView(ScrollView(this).apply { addView(col) })
    }
}
