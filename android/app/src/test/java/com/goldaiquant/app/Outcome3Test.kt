package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Test

class Outcome3Test {
    @Test fun percentsAlwaysAddUpTo100() {
        val p = Outcome3(0.525, 0.236, 0.238, "DOWN", 24, 69.82, 76.77).percents()
        assertEquals(100, p.values.sum()); assertEquals(53, p["DOWN"])
        assertEquals(100, Outcome3(0.333, 0.333, 0.334, null, 24, 1.0, 2.0).percents().values.sum())
    }
}
