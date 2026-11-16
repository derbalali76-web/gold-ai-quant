package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDate

class RecordTest {
    private val body = """{"chain_head":"x","briefs":[
      {"seq":28,"asset":"SOL","date":"2026-11-16","bias":"DOWN","price":72.24,"outcome":"PENDING","close":null,"baseline_up_correct":null},
      {"seq":17,"asset":"XAU","date":"2026-11-16","bias":"UNKNOWN","price":3880.32,"outcome":"PENDING","close":null,"baseline_up_correct":null},
      {"seq":8,"asset":"SOL","date":"2026-11-15","bias":"DOWN","price":70.64,"outcome":"WRONG","close":72.77,"baseline_up_correct":true},
      {"seq":3,"asset":"BTC","date":"2026-11-15","bias":"DOWN","price":64500.0,"outcome":"WRONG","close":65351.05,"baseline_up_correct":true},
      {"seq":2,"asset":"SOL","date":"2026-11-14","bias":"DOWN","price":72.68,"outcome":"CORRECT","close":70.28,"baseline_up_correct":false},
      {"seq":1,"asset":"BTC","date":"2026-11-01","bias":"UP","price":1.0,"outcome":"NO_DATA","close":null,"baseline_up_correct":null}]}"""

    @Test fun statusUsesTheLedgerOutcomeAndNeutralForNoCall() {
        val rows = Record.parse(body)
        assertEquals(6, rows.size)
        assertEquals(RecStatus.NEUTRAL, Record.status(rows.first { it.asset == "XAU" }))
        assertEquals(RecStatus.PENDING, Record.status(rows.first { it.seq == 28 }))
        assertEquals(RecStatus.NO_DATA, Record.status(rows.first { it.seq == 1 }))
    }

    @Test fun accuracyCountsSettledDirectionalCallsOnly() {
        val rows = Record.filter(Record.parse(body), null, 7, LocalDate.parse("2026-11-16"))
        val s = Record.summary(rows)
        assertEquals(5, rows.size)  // the 1 Nov row is outside 7 days
        assertEquals(1, s.correct); assertEquals(2, s.wrong); assertEquals(1, s.neutral); assertEquals(1, s.pending)
        assertEquals(1.0 / 3, s.accuracy!!, 1e-9)
        assertEquals(2, s.baselineUp)
    }

    @Test fun filtersByAssetAndToday() {
        val all = Record.parse(body)
        assertEquals(2, Record.filter(all, null, 1, LocalDate.parse("2026-11-16")).size)
        val sol = Record.filter(all, "SOL", 30, LocalDate.parse("2026-11-16"))
        assertEquals(3, sol.size)
        assertNull(Record.summary(emptyList()).accuracy)
    }
}
