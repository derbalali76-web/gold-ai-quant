package com.goldaiquant.app

import com.goldaiquant.app.ui.trendCode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TrendCodeTest {
    @Test fun codesAreRecognised() {
        assertEquals("DOWN", trendCode("DOWN"))
        assertEquals("UP", trendCode("UP"))
        assertEquals("SIDEWAYS", trendCode("SIDEWAYS"))
        assertNull(trendCode("UNKNOWN"))
    }
}
