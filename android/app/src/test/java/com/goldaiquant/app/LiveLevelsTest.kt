package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LiveLevelsTest {
    private fun lv(p: Double) = Level("L", p, p, p, null, "", 0, emptyList(), false)
    private val levels = Levels(listOf(70.58, 67.50, 64.04).map(::lv), listOf(75.45, 81.40).map(::lv), false, null)

    @Test fun supportAbovePriceBecomesResistance() {
        val r = LiveLevels.reanchor(levels, 69.63)!!
        assertEquals(listOf(67.50, 64.04), r.supports.map { it.price })
        assertEquals(listOf(70.58, 75.45, 81.40), r.resistances.map { it.price })
    }

    @Test fun unchangedWhenPriceBetweenSameLevels() {
        val r = LiveLevels.reanchor(levels, 72.0)!!
        assertEquals(listOf(70.58, 67.50, 64.04), r.supports.map { it.price })
        assertEquals(listOf(75.45, 81.40), r.resistances.map { it.price })
    }

    @Test fun noPriceKeepsLevels() { assertTrue(LiveLevels.reanchor(levels, null) === levels) }
}
