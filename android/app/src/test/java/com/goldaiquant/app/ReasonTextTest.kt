package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Test

class ReasonTextTest {
    private val en = ReasonStrings { c ->
        mapOf(
            "rs.short" to "{0}. {1}.",
            "rs.ctx" to "H4 trend {0}, overall trend {1}{2}",
            "w.up" to "up", "w.down" to "down", "w.none" to "",
            "rs.tail_above" to ", price above support {0}",
            "rs.ok" to "Expected return after costs is positive",
        )[c]
    }

    @Test fun rendersNestedReasonsAndPlaceholdersInOrder() {
        val r = Reason("rs.short", listOf(
            Reason("rs.ctx", listOf(Reason("w.up", emptyList(), "صاعد"), Reason("w.down", emptyList(), "هابط"),
                Reason("rs.tail_above", listOf("4000.00"), "x")), "ar"),
            Reason("rs.ok", emptyList(), "ar")), "ar")
        assertEquals("H4 trend up, overall trend down, price above support 4000.00. Expected return after costs is positive.",
            ReasonText.render(r, en))
    }

    @Test fun unknownCodeFallsBackToServerArabic() {
        assertEquals("نص عربي", ReasonText.render(Reason("zz.unknown", listOf("1"), "نص عربي"), en))
    }

    @Test fun rawCodeIsShownAsIs() {
        assertEquals("anything", ReasonText.render(Reason("raw", emptyList(), "anything"), en))
    }

    @Test fun missingArgumentRendersEmptyNotCrash() {
        val s = ReasonStrings { "a {0} b {1}" }
        assertEquals("a x b ", ReasonText.render(Reason("t", listOf("x"), ""), s))
    }

    @Test fun resourceNameMapsDotsToUnderscores() {
        assertEquals("r_ev_lv_sup_guard", ReasonText.resourceName("ev.lv_sup_guard"))
    }
}
