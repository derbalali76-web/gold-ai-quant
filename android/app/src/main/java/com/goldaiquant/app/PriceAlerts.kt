package com.goldaiquant.app

import android.content.SharedPreferences
import java.util.Locale

/** One-tap price alert the user set on a level or scenario ("نبّهني"). Stored on the phone only; fires once. */
data class PriceAlert(val asset: String, val price: Double, val dir: String, val label: String) {
    val key: String get() = "$asset|$dir|" + String.format(Locale.US, "%.6f", price)
}

object PriceAlerts {
    private const val KEY = "price_alerts"
    private const val MAX = 30

    /** ABOVE when the level is above the current price (resistance / breakout), BELOW otherwise. */
    fun make(asset: String, level: Double, current: Double?, label: String): PriceAlert =
        PriceAlert(asset, level, if (current != null && level > current) "ABOVE" else "BELOW", label)

    fun encode(list: List<PriceAlert>): String =
        list.takeLast(MAX).joinToString("\n") { "${it.asset}|${it.dir}|${it.price}|${it.label.replace("|", "/").replace("\n", " ")}" }

    fun decode(s: String?): List<PriceAlert> = s.orEmpty().lines().mapNotNull { ln ->
        val p = ln.split('|')
        if (p.size < 4) return@mapNotNull null
        val price = p[2].toDoubleOrNull() ?: return@mapNotNull null
        if (p[1] != "ABOVE" && p[1] != "BELOW") return@mapNotNull null
        PriceAlert(p[0], price, p[1], p[3])
    }

    fun load(prefs: SharedPreferences): List<PriceAlert> = decode(prefs.getString(KEY, null))
    fun save(prefs: SharedPreferences, list: List<PriceAlert>) = prefs.edit().putString(KEY, encode(list)).apply()

    fun toggle(list: List<PriceAlert>, a: PriceAlert): List<PriceAlert> =
        if (list.any { it.key == a.key }) list.filterNot { it.key == a.key } else list + a

    fun isOn(list: List<PriceAlert>, asset: String, price: Double): Boolean =
        list.any { it.asset == asset && kotlin.math.abs(it.price - price) < 1e-9 }

    /** Reached: the price is now at or through the level in the alert's direction. */
    fun reached(a: PriceAlert, price: Double): Boolean = if (a.dir == "ABOVE") price >= a.price else price <= a.price
}
