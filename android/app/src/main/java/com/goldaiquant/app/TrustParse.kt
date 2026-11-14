package com.goldaiquant.app

import org.json.JSONObject

/** Parsed stats.json of the public trust ledger. */
data class TrustBlock(val completed: Int, val wins: Int, val winRate: Double?, val avgR: Double?, val baselineAvgR: Double?)
data class TrustRow(val date: String, val horizon: String, val side: String, val outcome: String, val r: Double?)
data class Trust(
    val all: TrustBlock, val published: Int, val open: Int, val daysTracked: Int, val since: String?,
    val analysisScored: Int, val accuracy: Double?, val baselineAccuracy: Double?,
    val byModel: Map<String, TrustBlock>, val recent: List<TrustRow>, val head: String,
)

object TrustParser {
    private fun JSONObject.dOrNull(k: String): Double? = if (!has(k) || isNull(k)) null else optDouble(k).takeIf { it.isFinite() }

    private fun block(o: JSONObject?): TrustBlock = TrustBlock(
        o?.optInt("completed", 0) ?: 0, o?.optInt("wins", 0) ?: 0, o?.dOrNull("win_rate"), o?.dOrNull("avg_r"),
        o?.dOrNull("baseline_avg_r"))

    /** Every asset's record (gold at the top level, the others under "assets"). */
    fun parseAll(body: String?): Map<String, Trust> =
        listOf("XAU", "BTC", "ETH", "SOL").mapNotNull { a -> parse(body, a)?.let { a to it } }.toMap()

    /** Null when the body is not a ledger stats file (never a reason to fail the screen). */
    fun parse(body: String?, asset: String = "XAU"): Trust? {
        val root = try { JSONObject(body ?: return null) } catch (e: Exception) { return null }
        if (!root.has("chain_head")) return null
        val o = if (asset == "XAU") root else root.optJSONObject("assets")?.optJSONObject(asset) ?: return null
        if (!o.has("recommendations")) return null
        val rec = o.optJSONObject("recommendations")
        val an = o.optJSONObject("analysis")
        val bm = o.optJSONObject("by_model")
        val models = bm?.keys()?.asSequence()?.associateWith { block(bm.optJSONObject(it)) } ?: emptyMap()
        val ra = o.optJSONArray("recent")
        val recent = (0 until (ra?.length() ?: 0)).mapNotNull { i ->
            val e = ra!!.optJSONObject(i) ?: return@mapNotNull null
            TrustRow(e.optString("recorded_at").take(10), e.optString("horizon"), e.optString("side"),
                e.optString("outcome"), e.dOrNull("r"))
        }
        return Trust(block(rec), rec?.optInt("published", 0) ?: 0, rec?.optInt("open", 0) ?: 0,
            o.optInt("days_tracked", 0), o.optString("tracking_since").takeIf { it.isNotBlank() && it != "null" },
            an?.optInt("scored", 0) ?: 0, an?.dOrNull("accuracy"), an?.dOrNull("baseline_accuracy"),
            models, recent, root.optString("chain_head"))
    }
}
