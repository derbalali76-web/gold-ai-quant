package com.goldaiquant.app

/**
 * A translatable sentence produced by the engine: [code] + ordered [args] (each a String or a nested [Reason]).
 * [textAr] is the server's Arabic rendering, used only when the app has no string for [code].
 */
data class Reason(val code: String, val args: List<Any>, val textAr: String)

/** Looks up the localized template for a reason code (null when the app has no string for it). */
fun interface ReasonStrings {
    fun lookup(code: String): String?
}

object ReasonText {
    private val placeholder = Regex("""\{(\d+)}""")

    /** Resource name for a code: "ev.lv_sup_guard" -> "r_ev_lv_sup_guard". */
    fun resourceName(code: String): String = "r_" + code.replace('.', '_')

    fun render(r: Reason, strings: ReasonStrings): String {
        if (r.code == "raw") return r.textAr
        val template = strings.lookup(r.code) ?: return r.textAr
        val args = r.args.map { if (it is Reason) render(it, strings) else it.toString() }
        return placeholder.replace(template) { m -> args.getOrNull(m.groupValues[1].toInt()) ?: "" }
    }
}
