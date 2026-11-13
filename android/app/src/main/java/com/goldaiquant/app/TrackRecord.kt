package com.goldaiquant.app

import org.json.JSONObject

/** One resolved WEEK / MONTH signal from the server's live forward log (recorded before its outcome). */
data class TrackItem(val bar: String, val horizon: String, val tilt: Int, val close: Double, val exitClose: Double, val hit: Boolean)

object TrackParser {
    /** Newest first; malformed entries are skipped (the log is informational, never a reason to fail). */
    fun parse(body: String): List<TrackItem> {
        val o = try { JSONObject(body) } catch (e: Exception) { return emptyList() }
        val a = o.optJSONArray("recent") ?: return emptyList()
        return (0 until a.length()).mapNotNull { i ->
            val e = a.optJSONObject(i) ?: return@mapNotNull null
            val tilt = e.optInt("tilt", 0)
            if (tilt == 0 || !e.has("exit_close") || !e.has("hit")) return@mapNotNull null
            TrackItem(e.optString("bar").take(10), e.optString("horizon"), tilt, e.optDouble("close"),
                e.optDouble("exit_close"), e.optBoolean("hit"))
        }.filter { it.close.isFinite() && it.exitClose.isFinite() }.sortedByDescending { it.bar }
    }
}
