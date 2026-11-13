package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LangTest {
    @Test fun englishIsTheDefault() {
        assertEquals(Lang.EN, Lang.DEFAULT)
        assertEquals(Lang.EN, Lang.detect(null))
        assertEquals(Lang.EN, Lang.detect("de-DE"))
        assertEquals(Lang.EN, Lang.detect("zh-Hans-CN"))
    }

    @Test fun detectsSupportedDeviceLanguages() {
        assertEquals(Lang.AR, Lang.detect("ar"))
        assertEquals(Lang.AR, Lang.detect("ar-DZ"))
        assertEquals(Lang.FR, Lang.detect("fr-CA"))
        assertEquals(Lang.ES, Lang.detect("es_MX"))
        assertEquals(Lang.PT, Lang.detect("pt-PT"))
        assertEquals(Lang.PT, Lang.detect("pt-BR"))
    }

    @Test fun onlyArabicIsRightToLeft() {
        assertEquals(listOf(Lang.AR), Lang.entries.filter { it.rtl })
    }

    @Test fun savedTagsRoundTrip() {
        Lang.entries.forEach { assertEquals(it, Lang.fromTag(it.tag)) }
        assertNull(Lang.fromTag("xx"))
        assertNull(Lang.fromTag(null))
        assertEquals(5, Lang.entries.size)
    }
}
