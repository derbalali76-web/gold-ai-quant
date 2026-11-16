package com.goldaiquant.app

import org.json.JSONObject
import java.time.LocalDate

/** One recorded daily direction call from the public ledger (stats.json "briefs"). Read-only: never re-scored here. */
data class BriefRow(val seq: Int, val asset: String, val date: String, val bias: String, val price: Double?,
                    val outcome: String, val close: Double?, val baselineUp: Boolean?)

enum class RecStatus { CORRECT, WRONG, NEUTRAL, PENDING, NO_DATA }

data class RecSummary(val correct: Int, val wrong: Int, val neutral: Int, val pending: Int, val baselineUp: Int) {
    val settled get() = correct + wrong
    /** Accuracy over settled directional calls only (null when none). */
    val accuracy: Double? get() = if (settled > 0) correct.toDouble() / settled else null
}

object Record {
    const val MIN_SETTLED = 30  // below this the gauge stays grey: too few to judge

    fun parse(body: String?): List<BriefRow> {
        val root = try { JSONObject(body ?: return emptyList()) } catch (e: Exception) { return emptyList() }
        val a = root.optJSONArray("briefs") ?: return emptyList()
        return (0 until a.length()).mapNotNull { i ->
            val o = a.optJSONObject(i) ?: return@mapNotNull null
            val date = o.optString("date").takeIf { it.length == 10 } ?: return@mapNotNull null
            BriefRow(o.optInt("seq"), o.optString("asset", "XAU"), date, o.optString("bias"),
                o.optDouble("price").takeIf { !o.isNull("price") && it.isFinite() }, o.optString("outcome", "PENDING"),
                o.optDouble("close").takeIf { !o.isNull("close") && it.isFinite() },
                if (o.isNull("baseline_up_correct") || !o.has("baseline_up_correct")) null else o.optBoolean("baseline_up_correct"))
        }.sortedWith(compareByDescending<BriefRow> { it.date }.thenByDescending { it.seq })
    }

    /** The ledger's own outcome; a day without an UP/DOWN call is neutral whatever else was recorded. */
    fun status(r: BriefRow): RecStatus = when {
        r.bias != "UP" && r.bias != "DOWN" -> RecStatus.NEUTRAL
        r.outcome == "CORRECT" -> RecStatus.CORRECT
        r.outcome == "WRONG" -> RecStatus.WRONG
        r.outcome == "NO_DATA" -> RecStatus.NO_DATA
        else -> RecStatus.PENDING
    }

    /** asset = null for all; days = 1 (today), 7 or 30, counted back from today (UTC trading days). */
    fun filter(rows: List<BriefRow>, asset: String?, days: Int, today: LocalDate): List<BriefRow> {
        val from = today.minusDays((days - 1).toLong()).toString()
        val to = today.toString()
        return rows.filter { (asset == null || it.asset == asset) && it.date >= from && it.date <= to }
    }

    fun summary(rows: List<BriefRow>): RecSummary {
        var c = 0; var w = 0; var n = 0; var p = 0; var b = 0
        rows.forEach { r ->
            when (status(r)) {
                RecStatus.CORRECT -> c++
                RecStatus.WRONG -> w++
                RecStatus.NEUTRAL -> n++
                else -> p++
            }
            if ((status(r) == RecStatus.CORRECT || status(r) == RecStatus.WRONG) && r.baselineUp == true) b++
        }
        return RecSummary(c, w, n, p, b)
    }
}
