package com.goldaiquant.app

import com.goldaiquant.app.ui.trendCode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TrendCodeTest {
    @Test fun perFrameArabicWordsAreRecognised() {
        // the server sends per-timeframe trends as Arabic words; they must not show as "unknown"
        assertEquals("DOWN", trendCode("هابط"))
        assertEquals("UP", trendCode("صاعد"))
        assertEquals("SIDEWAYS", trendCode("محايد"))
        assertEquals("DOWN", trendCode("DOWN"))
        assertNull(trendCode("UNKNOWN"))
    }
}
