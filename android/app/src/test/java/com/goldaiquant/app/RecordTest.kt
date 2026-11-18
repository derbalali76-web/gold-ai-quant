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

    private val ranges = """{"range_rows":[
      {"seq":40,"asset":"XAU","horizon":"4h","issued_at":"2026-11-18T08:00:00Z","low":3742.0,"high":3804.1,"outcome":"PENDING","close":null},
      {"seq":39,"asset":"XAU","horizon":"4h","issued_at":"2026-11-18T04:00:00Z","low":3763.0,"high":3814.9,"outcome":"INSIDE","close":3772.43},
      {"seq":38,"asset":"XAU","horizon":"24h","issued_at":"2026-11-18T00:00:00Z","low":3790.8,"high":3913.8,"outcome":"PENDING","close":null},
      {"seq":37,"asset":"XAU","horizon":"4h","issued_at":"2026-11-18T00:00:00Z","low":3836.7,"high":3867.4,"outcome":"BELOW","close":3788.5},
      {"seq":36,"asset":"BTC","horizon":"4h","issued_at":"2026-11-17T20:00:00Z","low":1.0,"high":2.0,"outcome":"ABOVE","close":2.5},
      {"seq":35,"asset":"SOL","horizon":"4h","issued_at":"2026-11-17T16:00:00Z","low":1.0,"high":2.0,"outcome":"NO_DATA","close":null},
      {"seq":34,"asset":"XAU","horizon":"4h","issued_at":"bad","low":1.0,"high":2.0,"outcome":"INSIDE","close":1.5}]}"""

    @Test fun rangeRowsMapToCorrectWrongNeutral() {
        val rows = Record.rangeRows(ranges)
        assertEquals(6, rows.size)  // the malformed time is dropped
        assertEquals(40, rows.first().seq)
        assertEquals(RecStatus.CORRECT, Record.status(rows.first { it.seq == 39 }))
        assertEquals(RecStatus.WRONG, Record.status(rows.first { it.seq == 37 }))
        assertEquals(RecStatus.WRONG, Record.status(rows.first { it.seq == 36 }))
        assertEquals(RecStatus.NEUTRAL, Record.status(rows.first { it.seq == 35 }))
        assertEquals(RecStatus.PENDING, Record.status(rows.first { it.seq == 40 }))
    }

    @Test fun rangeFilterByHorizonAssetAndDays() {
        val rows = Record.rangeRows(ranges)
        val today = LocalDate.parse("2026-11-18")
        val gold4h = Record.filterRanges(rows, "4h", "XAU", 7, today)
        assertEquals(listOf(40, 39, 37), gold4h.map { it.seq })
        val s = Record.rangeSummary(gold4h)
        assertEquals(1, s.correct); assertEquals(1, s.wrong); assertEquals(0, s.neutral); assertEquals(1, s.pending)
        assertEquals(5, Record.filterRanges(rows, "4h", null, 7, today).size)
        assertEquals(3, Record.filterRanges(rows, "4h", null, 1, today).size)
        assertEquals(1, Record.filterRanges(rows, "24h", null, 7, today).size)
        assertEquals(0, Record.filterRanges(rows, "1w", null, 30, today).size)
    }
}
