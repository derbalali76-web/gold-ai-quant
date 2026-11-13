package com.goldaiquant.app

import android.content.Context
import android.content.res.Configuration
import java.util.Locale

/** Persisted language choice. On first launch the device language is detected (unsupported -> English) and saved. */
object LanguageStore {
    private const val PREFS = "gold_ai_quant"
    private const val KEY = "language"

    fun resolve(ctx: Context): Lang {
        val prefs = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        Lang.fromTag(prefs.getString(KEY, null))?.let { return it }
        val detected = Lang.detect(Locale.getDefault().toLanguageTag())
        prefs.edit().putString(KEY, detected.tag).apply()
        return detected
    }

    fun save(ctx: Context, lang: Lang) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY, lang.tag).apply()
    }

    /** Context whose resources, locale and layout direction follow [lang] (not the device setting). */
    fun wrap(base: Context, lang: Lang): Context {
        val locale = Locale.forLanguageTag(lang.tag)
        Locale.setDefault(locale)
        val cfg = Configuration(base.resources.configuration)
        cfg.setLocale(locale)
        cfg.setLayoutDirection(locale)
        return base.createConfigurationContext(cfg)
    }
}
