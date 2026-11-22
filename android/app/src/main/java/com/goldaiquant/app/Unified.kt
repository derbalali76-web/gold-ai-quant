package com.goldaiquant.app

import org.json.JSONArray
import org.json.JSONObject

/** AI QUANT 2.0 — one decision state for «ماذا أفعل؟», the opportunity radar and the record (public ledger
 *  decision/state.json, schema decision-state-2). The app never decides by itself: it renders this file.
 *
 *  Owner rules (approved 2026-11-22):
 *  - the likely scenario is always shown, but a scenario alone never becomes «buy now» / «sell now»;
 *  - an executive decision appears only when the ledger marks it QUALIFIED; otherwise WAIT with its reasons;
 *  - a cash user is never told to sell; a holder may be told to sell before a break (then buy back) if qualified;
 *  - a QUALIFIED radar item exists exactly when a non-WAIT verdict with the same signal id exists. */
enum class Verdict { SELL_THEN_REBUY, BUY, BUY_LIMIT, WAIT }

enum class RadarState { FORMING, READY_FOR_VALIDATION, QUALIFIED, REJECTED, EXPIRED }

data class Plan2(val sell: Double? = null, val rebuyAt: Double? = null, val invalidateAbove: Double? = null,
                 val entry: Double? = null, val target: Double? = null, val invalidateBelow: Double? = null,
                 val durationH: Int? = null)

data class ModeView(val verdict: Verdict, val signalId: String?, val plan: Plan2?, val why: List<String>)

data class RadarItem(val id: String, val source: String, val state: RadarState, val paper: Boolean,
                     val level: Double?, val entry: Double?, val target: Double?, val invalidateBelow: Double?,
                     val holderAction: String?, val cashAction: String?)

data class AssetState(val asset: String, val price: Double?, val priceAt: String?, val holder: ModeView, val cash: ModeView,
                      val radar: List<RadarItem>, val gatesOk: Boolean) {
    fun mode(hold: Boolean): ModeView = if (hold) holder else cash
    val qualified: List<RadarItem> get() = radar.filter { it.state == RadarState.QUALIFIED }
    val forming: List<RadarItem> get() = radar.filter { it.state == RadarState.FORMING || it.state == RadarState.READY_FOR_VALIDATION }
    val closed: List<RadarItem> get() = radar.filter { it.state == RadarState.REJECTED || it.state == RadarState.EXPIRED }
}

data class UnifiedState(val updatedAt: String, val assets: Map<String, AssetState>)

object Unified {
    const val URL = "https://raw.githubusercontent.com/derbalali76-web/ai-quant-ledger/main/decision/state.json"

    private fun JSONObject.d(k: String): Double? = if (has(k) && !isNull(k)) optDouble(k).takeIf { it.isFinite() } else null
    private fun JSONObject.s(k: String): String? = if (has(k) && !isNull(k)) optString(k) else null
    private fun JSONArray?.strings(): List<String> = if (this == null) emptyList() else (0 until length()).mapNotNull { optString(it, null) }

    private val WAIT_ONLY = ModeView(Verdict.WAIT, null, null, listOf("state_unavailable"))

    /** Parses one mode; anything inconsistent degrades to WAIT (never to an unverified order). */
    internal fun mode(o: JSONObject?, cash: Boolean): ModeView {
        if (o == null) return WAIT_ONLY
        val v = runCatching { Verdict.valueOf(o.optString("verdict")) }.getOrNull() ?: return WAIT_ONLY
        val why = o.optJSONArray("why").strings()
        val id = o.s("signal_id")
        if (v == Verdict.WAIT) return ModeView(v, id, null, why.ifEmpty { listOf("not_yet_qualified") })
        if (cash && v == Verdict.SELL_THEN_REBUY) return WAIT_ONLY          // a cash user is never told to sell
        if (!cash && v != Verdict.SELL_THEN_REBUY) return WAIT_ONLY
        val p = o.optJSONObject("plan") ?: return WAIT_ONLY
        val plan = Plan2(p.d("sell"), p.d("rebuy_at"), p.d("invalidate_above"), p.d("entry"), p.d("target"),
            p.d("invalidate_below"), if (p.has("duration_h") && !p.isNull("duration_h")) p.optInt("duration_h") else null)
        val complete = when (v) {
            Verdict.SELL_THEN_REBUY -> plan.sell != null && plan.rebuyAt != null && plan.invalidateAbove != null &&
                plan.rebuyAt < plan.sell && plan.invalidateAbove > plan.sell
            else -> plan.entry != null && (plan.invalidateBelow == null || plan.invalidateBelow < plan.entry) &&
                (plan.target == null || plan.target > plan.entry)
        }
        if (!complete || id == null) return WAIT_ONLY
        return ModeView(v, id, plan, emptyList())
    }

    private fun radar(a: JSONArray?): List<RadarItem> {
        if (a == null) return emptyList()
        return (0 until a.length()).mapNotNull { i ->
            val x = a.optJSONObject(i) ?: return@mapNotNull null
            val st = runCatching { RadarState.valueOf(x.optString("state")) }.getOrNull() ?: return@mapNotNull null
            RadarItem(x.optString("id"), x.optString("source"), st, x.optString("stage") == "PAPER_TEST",
                x.d("level"), x.d("entry"), x.d("target"), x.d("invalidate_below"), x.s("holder"), x.s("cash"))
        }
    }

    fun parse(body: String?): UnifiedState? {
        val o = try { JSONObject(body ?: return null) } catch (e: Exception) { return null }
        if (o.optString("schema") != "decision-state-2") return null
        val assets = o.optJSONObject("assets") ?: return null
        val out = mutableMapOf<String, AssetState>()
        for (k in assets.keys()) {
            val a = assets.optJSONObject(k) ?: continue
            val v = a.optJSONObject("view")
            var holder = mode(v?.optJSONObject("holder"), cash = false)
            var cash = mode(v?.optJSONObject("cash"), cash = true)
            var items = radar(a.optJSONArray("radar"))
            // one state everywhere: an order without its QUALIFIED radar item (or the reverse) is not shown as an order
            val execIds = listOf(holder, cash).filter { it.verdict != Verdict.WAIT }.mapNotNull { it.signalId }.toSet()
            val qIds = items.filter { it.state == RadarState.QUALIFIED }.map { it.id }.toSet()
            if (execIds != qIds) {
                if (holder.verdict != Verdict.WAIT) holder = ModeView(Verdict.WAIT, null, null, listOf("state_inconsistent"))
                if (cash.verdict != Verdict.WAIT) cash = ModeView(Verdict.WAIT, null, null, listOf("state_inconsistent"))
                items = items.map { if (it.state == RadarState.QUALIFIED) it.copy(state = RadarState.FORMING) else it }
            }
            val price = a.optJSONObject("price")
            out[k] = AssetState(k, price?.d("value"), price?.s("at"), holder, cash, items,
                a.optJSONObject("gates")?.optBoolean("ok", false) ?: false)
        }
        return UnifiedState(o.optString("updated_at"), out)
    }
}
