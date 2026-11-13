package com.goldaiquant.app

/** Supported UI languages. English is the default; [detect] is used on first launch only. */
enum class Lang(val tag: String, val nativeName: String, val rtl: Boolean) {
    EN("en", "English", false),
    AR("ar", "العربية", true),
    FR("fr", "Français", false),
    ES("es", "Español", false),
    PT("pt-BR", "Português (Brasil)", false);

    companion object {
        val DEFAULT = EN

        fun fromTag(tag: String?): Lang? = entries.firstOrNull { it.tag.equals(tag, ignoreCase = true) }

        /** Maps a device language ("fr-CA", "pt_PT", "ar") to a supported language; unsupported -> English. */
        fun detect(deviceTag: String?): Lang {
            val code = deviceTag?.lowercase()?.replace('_', '-')?.substringBefore('-') ?: return DEFAULT
            return when (code) {
                "ar" -> AR
                "fr" -> FR
                "es" -> ES
                "pt" -> PT
                else -> EN
            }
        }
    }
}
