package com.goldaiquant.app

import org.json.JSONObject
import java.time.LocalDate

/** One recorded daily direction call from the public ledger (stats.json "briefs"). Read-only: never re-scored here. */
data class BriefRow(val seq: Int, val asset: String, val date: String, val bias: String, val price: Double?,
                    val outcome: String, val close: Double?, val baselineUp: Boolean?)

/** Live tracking of the experimental ranges (public ledger stats "ranges"): recorded, settled, inside. */
data class RangeTrack(val recorded: Int, val settled: Int, val inside: Int)

/** One recorded price range (stats.json "range_rows"): did the price close inside it at the horizon's end? */
data class RangeRow(val seq: Int, val asset: String, val horizon: String, val issuedAt: String, val low: Double,
                    val high: Double, val outcome: String, val close: Double?)

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

    fun rangeTracks(body: String?): Map<String, Map<String, RangeTrack>> {
        val root = try { JSONObject(body ?: return emptyMap()) } catch (e: Exception) { return emptyMap() }
        val r = root.optJSONObject("ranges") ?: return emptyMap()
        return r.keys().asSequence().associateWith { a ->
            val o = r.optJSONObject(a)
            o?.keys()?.asSequence()?.associateWith { h ->
                val b = o.optJSONObject(h)
                RangeTrack(b?.optInt("recorded") ?: 0, b?.optInt("settled") ?: 0, b?.optInt("inside") ?: 0)
            } ?: emptyMap()
        }
    }

    fun rangeRows(body: String?): List<RangeRow> {
        val root = try { JSONObject(body ?: return emptyList()) } catch (e: Exception) { return emptyList() }
        val a = root.optJSONArray("range_rows") ?: return emptyList()
        return (0 until a.length()).mapNotNull { i ->
            val o = a.optJSONObject(i) ?: return@mapNotNull null
            val t = o.optString("issued_at").takeIf { it.length >= 16 } ?: return@mapNotNull null
            val lo = o.optDouble("low"); val hi = o.optDouble("high")
            if (!lo.isFinite() || !hi.isFinite()) return@mapNotNull null
            RangeRow(o.optInt("seq"), o.optString("asset", "XAU"), o.optString("horizon"), t, lo, hi,
                o.optString("outcome", "PENDING"), o.optDouble("close").takeIf { !o.isNull("close") && it.isFinite() })
        }.sortedWith(compareByDescending<RangeRow> { it.issuedAt }.thenByDescending { it.seq })
    }

    /** Inside the range = correct; closed above or below = wrong; no closing price = neutral (not counted). */
    fun status(r: RangeRow): RecStatus = when (r.outcome) {
        "INSIDE" -> RecStatus.CORRECT
        "ABOVE", "BELOW" -> RecStatus.WRONG
        "NO_DATA" -> RecStatus.NEUTRAL
        else -> RecStatus.PENDING
    }

    /** horizon "4h" | "24h" | "1w"; asset = null for all; days counted back from today by the UTC issue date. */
    fun filterRanges(rows: List<RangeRow>, horizon: String, asset: String?, days: Int, today: LocalDate): List<RangeRow> {
        val from = today.minusDays((days - 1).toLong()).toString()
        val to = today.toString()
        return rows.filter { r ->
            val d = r.issuedAt.take(10)
            r.horizon == horizon && (asset == null || r.asset == asset) && d >= from && d <= to
        }
    }

    fun rangeSummary(rows: List<RangeRow>): RecSummary {
        var c = 0; var w = 0; var n = 0; var p = 0
        rows.forEach { when (status(it)) { RecStatus.CORRECT -> c++; RecStatus.WRONG -> w++; RecStatus.NEUTRAL -> n++; else -> p++ } }
        return RecSummary(c, w, n, p, 0)
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
