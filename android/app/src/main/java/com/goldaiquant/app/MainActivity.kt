package com.goldaiquant.app

import android.content.Context
import android.os.Bundle
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

    override fun attachBaseContext(newBase: Context) {
        lang = LanguageStore.resolve(newBase)
        super.attachBaseContext(LanguageStore.wrap(newBase, lang))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
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
}
