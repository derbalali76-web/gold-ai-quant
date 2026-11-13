package com.goldaiquant.app

import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant

/** Mirror of schema/decision.schema.json (v1). Parsed and validated strictly; anything off -> ParseException. */
enum class Action { BUY, SELL, WAIT, UNAVAILABLE }

data class EvidenceItem(val engine: String, val textAr: String, val weight: Double, val ref: Reason? = null) {
    val reason: Reason get() = ref ?: Reason("raw", emptyList(), textAr)
}

data class Trend(val direction: String, val strength: Int?, val labelAr: String, val perTimeframe: Map<String, String>,
                 val agreement: Double? = null)

data class Level(val name: String, val price: Double, val zoneLow: Double, val zoneHigh: Double, val strength: Int?,
                 val labelAr: String, val tests: Int, val timeframes: List<String>, val brokenRecently: Boolean,
                 val lastTest: Instant? = null, val roleFlip: Boolean = false, val distanceAtr: Double? = null)

data class Levels(val supports: List<Level>, val resistances: List<Level>, val validated: Boolean, val validationAr: String?)

data class Judgement(val judge: String, val passed: Boolean, val reasonsAr: List<String>, val refs: List<Reason> = emptyList()) {
    val reasons: List<Reason> get() = if (refs.isNotEmpty()) refs else reasonsAr.map { Reason("raw", emptyList(), it) }
}

/** Per-horizon card: HOURS mirrors the main decision; WEEK / MONTH come from validated daily rules. */
data class Outlook(
    val horizon: String, val labelAr: String, val action: Action, val tilt: Int, val stanceAr: String,
    val reasonAr: String, val validated: Boolean, val validationAr: String?, val hitRate: Double?,
    val baseRate: Double?, val samples: Int, val horizonDays: Int?, val entryPrice: Double?, val stopLoss: Double?,
    val target: Double?, val waitForPrice: Double?, val warningsAr: List<String>,
    val stance: Reason? = null, val reason: Reason? = null, val validation: Reason? = null, val method: Reason? = null,
    val warnings: List<Reason> = emptyList(), val facts: List<Reason> = emptyList(),
    val levels: Levels? = null, val trend: Trend? = null,
    val liveResolved: Int = 0, val liveHits: Int = 0,
    val plan: Plan? = null, val performance: List<Perf> = emptyList(),
)

/** v1.7 trade plan of one horizon. A watch plan (WAIT_TO_*) never carries a stop or a target. */
data class Plan(
    val setup: String, val recommendation: Boolean, val side: String?, val entryLow: Double?, val entryHigh: Double?,
    val watchPrice: Double?, val stop: Double?, val target: Double?, val rewardRisk: Double?,
    val expectedMinutes: Int?, val expectedDays: Int?, val validUntil: Instant?, val invalidation: List<Reason>,
    val pTarget: Double? = null, val pStop: Double? = null, val pTimeout: Double? = null, val pFill: Double? = null,
    val evPct: Double? = null, val medianDaysToTarget: Double? = null, val fillDays: Int? = null,
) {
    val isNow: Boolean get() = setup == "BUY_NOW" || setup == "SELL_NOW"
}

/** Track record from one source; trades = completed only. */
data class Perf(
    val source: String, val unit: String, val trades: Int, val hits: Int, val pending: Int, val notFilled: Int,
    val avgWin: Double?, val avgLoss: Double?, val expectancy: Double?, val maxDrawdown: Double?, val period: String?,
    val directionAccuracy: Double? = null, val directionBaseline: Double? = null, val baselineExpectancy: Double? = null,
    val qualified: Boolean? = null,
)

data class HorizonProb(val minutes: Int, val pTarget: Double, val pStop: Double, val pNeither: Double, val qualified: Boolean)

data class Decision(
    val schemaVersion: String,
    val decisionId: String,
    val mode: String,
    val action: Action,
    val spotOrProxy: String,
    val provider: String,
    val quote: Double?,
    val quoteTime: Instant?,
    val analyzedAt: Instant,
    val entryMin: Double?,
    val entryMax: Double?,
    val stopLoss: Double?,
    val tp1: Double?,
    val tp2: Double?,
    val tp3: Double?,
    val horizonMinutes: Int?,
    val validUntil: Instant?,
    val probability: Double?,
    val probabilityStop: Double?,
    val probabilityNeither: Double?,
    val horizonProbs: List<HorizonProb>,
    val reliabilityAr: String?,
    val probabilityMethod: String,
    val calibrationSamples: Int,
    val modelVersion: String,
    val estimatedCost: Double?,
    val rewardRisk: Double?,
    val marketRegime: String?,
    val supporting: List<EvidenceItem>,
    val contrary: List<EvidenceItem>,
    val invalidation: List<String>,
    val missingData: List<String>,
    val quoteAgeSeconds: Double?,
    val isFresh: Boolean,
    val dataQuality: String,
    val warningAr: String?,
    val waitForAr: String?,
    val waitForPrice: Double?,
    val reasonShortAr: String?,
    val alternativeEntryPrice: Double?,
    val alternativeEntryNoteAr: String?,
    val volRegime: String?,
    val uncertaintyOverall: String?,
    val expectedNetReturn: Double?,
    val court: List<Judgement>,
    val budgetUsed: Double?,
    val budgetLimit: Double?,
    val auditHash: String?,
    val trend: Trend?,
    val levels: Levels?,
    val quoteChange: Double?,
    val quoteChangePct: Double?,
    val reevaluateAr: List<String>,
    val outlooks: List<Outlook> = emptyList(),
    val reasonShort: Reason? = null,
    val waitFor: Reason? = null,
    val warning: Reason? = null,
    val invalidationRefs: List<Reason> = emptyList(),
    val missingRefs: List<Reason> = emptyList(),
    val alternativeEntryNote: Reason? = null,
    val reevaluateRefs: List<Reason> = emptyList(),
    val marketClosed: Boolean = false,
) {
    val isDemo: Boolean get() = mode == "DEMO"

    /** Probability is shown ONLY when it is genuinely calibrated out-of-sample on real data. */
    val displayableProbability: Double?
        get() = if (!isDemo && probability != null && calibrationSamples >= 300) probability else null

    /** All three outcome probabilities, only under the same conditions as [displayableProbability]. */
    val displayableOutcomes: Triple<Double, Double, Double>?
        get() = if (displayableProbability != null && probabilityStop != null && probabilityNeither != null)
            Triple(probability!!, probabilityStop, probabilityNeither) else null

    fun isExpired(now: Instant): Boolean = validUntil?.let { now.isAfter(it) } ?: false
}

class ParseException(msg: String) : Exception(msg)

object DecisionParser {
    private const val SUPPORTED_MAJOR = "1"

    fun parse(raw: String): Decision {
        val o = try { JSONObject(raw) } catch (e: Exception) { throw ParseException("invalid JSON") }
        val version = o.req("schema_version")
        if (version.substringBefore('.') != SUPPORTED_MAJOR) throw ParseException("unsupported contract version: $version")
        val action = try { Action.valueOf(o.req("action")) } catch (e: IllegalArgumentException) {
            throw ParseException("unknown action value")
        }
        val fresh = o.optJSONObject("data_freshness") ?: throw ParseException("data_freshness missing")
        val d = Decision(
            schemaVersion = version,
            decisionId = o.req("decision_id"),
            mode = o.req("mode").also { if (it != "DEMO" && it != "LIVE") throw ParseException("unknown mode") },
            action = action,
            spotOrProxy = o.req("spot_or_proxy"),
            provider = o.req("provider"),
            quote = o.dbl("quote"),
            quoteTime = o.time("quote_timestamp_utc"),
            analyzedAt = o.time("analyzed_at_utc") ?: throw ParseException("analyzed_at_utc missing"),
            entryMin = o.dbl("entry_min"), entryMax = o.dbl("entry_max"), stopLoss = o.dbl("stop_loss"),
            tp1 = o.dbl("tp1"), tp2 = o.dbl("tp2"), tp3 = o.dbl("tp3"),
            horizonMinutes = if (o.isNull("horizon_minutes")) null else o.optInt("horizon_minutes"),
            validUntil = o.time("valid_until_utc"),
            probability = o.dbl("probability_target_before_stop"),
            probabilityStop = o.dbl("probability_stop_before_target"),
            probabilityNeither = o.dbl("probability_neither"),
            horizonProbs = o.horizons("probabilities_by_horizon"),
            reliabilityAr = o.str("probability_reliability_ar"),
            probabilityMethod = o.optString("probability_method", "none"),
            calibrationSamples = o.optInt("calibration_sample_count", 0),
            modelVersion = o.req("model_version"),
            estimatedCost = o.dbl("estimated_cost"),
            rewardRisk = o.dbl("reward_risk"),
            marketRegime = o.str("market_regime"),
            supporting = o.evidence("supporting_evidence"),
            contrary = o.evidence("contrary_evidence"),
            invalidation = o.strings("invalidation_ar"),
            missingData = o.strings("missing_data"),
            quoteAgeSeconds = fresh.dbl("quote_age_seconds"),
            isFresh = fresh.optBoolean("is_fresh", false),
            dataQuality = o.req("data_quality"),
            warningAr = o.str("warning_ar"),
            waitForAr = o.str("wait_for_ar"),
            waitForPrice = o.dbl("wait_for_price"),
            reasonShortAr = o.str("reason_short_ar"),
            alternativeEntryPrice = o.dbl("alternative_entry_price"),
            alternativeEntryNoteAr = o.str("alternative_entry_note_ar"),
            volRegime = o.str("vol_regime"),
            uncertaintyOverall = o.optJSONObject("uncertainty")?.str("overall"),
            expectedNetReturn = o.dbl("expected_net_return"),
            court = o.court("court"),
            budgetUsed = o.optJSONObject("uncertainty")?.dbl("budget_used"),
            budgetLimit = o.optJSONObject("uncertainty")?.dbl("budget_limit"),
            auditHash = o.str("audit_hash"),
            trend = o.optJSONObject("market_trend")?.let { t ->
                val per = t.optJSONObject("per_timeframe")
                parseTrend(t)
            },
            levels = o.optJSONObject("levels")?.let { parseLevels(it) },
            quoteChange = o.dbl("quote_change"),
            quoteChangePct = o.dbl("quote_change_pct"),
            reevaluateAr = o.strings("reevaluate_ar"),
            outlooks = o.outlooks("outlooks"),
            marketClosed = o.optBoolean("market_closed", false),
            reasonShort = o.reason("reason_short_ref"), waitFor = o.reason("wait_for_ref"), warning = o.reason("warning_ref"),
            invalidationRefs = o.reasons("invalidation_refs"), missingRefs = o.reasons("missing_refs"),
            alternativeEntryNote = o.reason("alternative_entry_note_ref"),
            reevaluateRefs = o.reasons("reevaluate_refs"),
        )
        validate(d)
        return d
    }

    private fun parseTrend(t: JSONObject): Trend {
        val per = t.optJSONObject("per_timeframe")
        return Trend(t.getString("direction"), if (t.isNull("strength")) null else t.getInt("strength"),
            t.getString("label_ar"), per?.keys()?.asSequence()?.associateWith { per.getString(it) } ?: emptyMap(),
            if (t.isNull("agreement") || !t.has("agreement")) null else t.getDouble("agreement"))
    }

    private fun parseLevels(lv: JSONObject): Levels =
        Levels(lv.levelList("supports"), lv.levelList("resistances"), lv.getBoolean("validated"), lv.str("validation_ar"))

    private fun validate(d: Decision) {
        if (d.isDemo && d.spotOrProxy != "SYNTHETIC") throw ParseException("demo mode without SYNTHETIC label")
        if (d.action == Action.BUY || d.action == Action.SELL) {
            val em = d.entryMin ?: throw ParseException("entry range missing")
            val ex = d.entryMax ?: throw ParseException("entry range missing")
            val sl = d.stopLoss ?: throw ParseException("stop loss missing")
            val t1 = d.tp1 ?: throw ParseException("first target missing")
            if (d.quote == null || d.quoteTime == null || d.validUntil == null) throw ParseException("quote/validity data missing")
            if (!d.isFresh) throw ParseException("signal on stale data")
            if (d.court.isEmpty() || d.court.any { !it.passed }) throw ParseException("signal did not pass the decision court")
            if (em > ex) throw ParseException("inverted entry range")
            val ok = if (d.action == Action.BUY) sl < em && t1 > ex else sl > ex && t1 < em
            if (!ok) throw ParseException("levels inconsistent with direction")
        }
        listOfNotNull(d.probability, d.probabilityStop, d.probabilityNeither).forEach {
            if (it < 0.0 || it > 1.0) throw ParseException("probability out of range")
        }
        if (d.probability != null && d.probabilityStop != null && d.probabilityNeither != null &&
            Math.abs(d.probability + d.probabilityStop + d.probabilityNeither - 1.0) > 1e-3)
            throw ParseException("probabilities do not sum to 1")
        d.trend?.strength?.let { if (it !in 0..100) throw ParseException("trend strength out of range") }
        d.levels?.let { lv ->
            val all = lv.supports + lv.resistances
            if (!lv.validated && all.any { it.strength != null }) throw ParseException("numeric level strength without validation")
            if (all.any { it.strength != null && it.strength !in 0..100 }) throw ParseException("level strength out of range")
            if (d.quote != null && (lv.supports.any { it.zoneHigh >= d.quote } || lv.resistances.any { it.zoneLow <= d.quote }))
                throw ParseException("levels on the wrong side of price")
        }
        d.outlooks.forEach { ol ->
            if (ol.horizon !in setOf("HOURS", "WEEK", "MONTH")) throw ParseException("unknown horizon: ${ol.horizon}")
            if (ol.hitRate != null && (!ol.validated || ol.samples < 30 || ol.hitRate !in 0.0..1.0 || d.isDemo))
                throw ParseException("historical rate without validation")
            if (ol.horizon != "HOURS" && (ol.action == Action.BUY || ol.action == Action.SELL)) {
                if (!ol.validated) throw ParseException("long-horizon signal without validation")
                val e = ol.entryPrice ?: throw ParseException("horizon entry price missing")
                val sl = ol.stopLoss ?: throw ParseException("horizon stop missing")
                val tg = ol.target ?: throw ParseException("horizon target missing")
                val ok = if (ol.action == Action.BUY) sl < e && tg > e else sl > e && tg < e
                if (!ok) throw ParseException("horizon levels inconsistent")
            }
        }
        if (d.isDemo && (d.probability != null || d.horizonProbs.isNotEmpty()))
            throw ParseException("probabilities in demo mode not allowed")
    }

    private fun JSONObject.req(k: String): String {
        if (!has(k) || isNull(k)) throw ParseException("field $k missing")
        return getString(k)
    }
    private fun JSONObject.str(k: String): String? = if (!has(k) || isNull(k)) null else getString(k)
    private fun JSONObject.dbl(k: String): Double? = if (!has(k) || isNull(k)) null else getDouble(k).also {
        if (it.isNaN() || it.isInfinite()) throw ParseException("invalid number in $k")
    }
    private fun JSONObject.time(k: String): Instant? = str(k)?.let {
        try { Instant.parse(it) } catch (e: Exception) { throw ParseException("invalid time in $k") }
    }
    private fun JSONObject.reason(k: String): Reason? = optJSONObject(k)?.let { toReason(it) }
    private fun JSONObject.reasons(k: String): List<Reason> {
        val a: JSONArray = optJSONArray(k) ?: return emptyList()
        return (0 until a.length()).map { toReason(a.getJSONObject(it)) }
    }
    private fun toReason(e: JSONObject): Reason {
        val a = e.optJSONArray("args")
        val args: List<Any> = if (a == null) emptyList() else (0 until a.length()).map { i ->
            val v = a.get(i)
            if (v is JSONObject) toReason(v) else v.toString()
        }
        return Reason(e.getString("code"), args, e.optString("text_ar", ""))
    }
    private fun JSONObject.strings(k: String): List<String> {
        val a: JSONArray = optJSONArray(k) ?: return emptyList()
        return (0 until a.length()).map { a.getString(it) }
    }
    private fun JSONObject.levelList(k: String): List<Level> {
        val a: JSONArray = optJSONArray(k) ?: return emptyList()
        return (0 until a.length()).map {
            val e = a.getJSONObject(it)
            Level(e.getString("name"), e.getDouble("price"), e.getDouble("zone_low"), e.getDouble("zone_high"),
                if (e.isNull("strength")) null else e.getInt("strength"), e.getString("strength_label_ar"),
                e.optInt("tests", 0), e.strings("timeframes"), e.optBoolean("broken_recently", false),
                e.time("last_test_utc"), e.optBoolean("role_flip", false), e.dbl("distance_atr"))
        }
    }
    private fun JSONObject.court(k: String): List<Judgement> {
        val a: JSONArray = optJSONArray(k) ?: return emptyList()
        return (0 until a.length()).map {
            val e = a.getJSONObject(it)
            Judgement(e.getString("judge"), e.getBoolean("passed"), e.strings("reasons_ar"), e.reasons("reasons_ref"))
        }
    }
    private fun JSONObject.outlooks(k: String): List<Outlook> {
        val a: JSONArray = optJSONArray(k) ?: return emptyList()
        return (0 until a.length()).map {
            val e = a.getJSONObject(it)
            val act = try { Action.valueOf(e.req("action")) } catch (x: IllegalArgumentException) {
                throw ParseException("unknown action value in horizon")
            }
            Outlook(e.req("horizon"), e.req("label_ar"), act, e.optInt("tilt", 0), e.req("stance_ar"),
                e.optString("reason_ar", ""), e.optBoolean("validated", false), e.str("validation_ar"),
                e.dbl("hit_rate"), e.dbl("base_rate"), e.optInt("samples", 0),
                if (e.isNull("horizon_days")) null else e.optInt("horizon_days"), e.dbl("entry_price"),
                e.dbl("stop_loss"), e.dbl("target"), e.dbl("wait_for_price"), e.strings("warnings_ar"),
                e.reason("stance_ref"), e.reason("reason_ref"), e.reason("validation_ref"), e.reason("method_ref"),
                e.reasons("warnings_ref"), e.reasons("facts_ref"),
                e.optJSONObject("levels")?.let { parseLevels(it) }, e.optJSONObject("trend")?.let { parseTrend(it) },
                e.optInt("live_resolved", 0).coerceAtLeast(0), e.optInt("live_hits", 0).coerceAtLeast(0),
                e.optJSONObject("plan")?.let { parsePlan(it) }, e.perfList("performance"))
        }
    }
    private fun parsePlan(p: JSONObject): Plan? {
        val setup = p.str("setup") ?: return null
        if (setup !in setOf("BUY_NOW", "SELL_NOW", "WAIT_TO_BUY", "WAIT_TO_SELL", "WAIT", "UNAVAILABLE")) return null
        val now = setup == "BUY_NOW" || setup == "SELL_NOW"
        val plan = Plan(setup, p.optBoolean("recommendation", false) && now, p.str("side"), p.dbl("entry_low"),
            p.dbl("entry_high"), p.dbl("watch_price"), if (now) p.dbl("stop_loss") else null, if (now) p.dbl("target") else null,
            p.dbl("reward_risk"), if (p.isNull("expected_minutes")) null else p.optInt("expected_minutes"),
            if (p.isNull("expected_days")) null else p.optInt("expected_days"), p.time("valid_until_utc"),
            p.reasons("invalidation_refs"))
        val rec = p.optBoolean("recommendation", false)
        val cond = setup == "WAIT_TO_BUY" || setup == "WAIT_TO_SELL"
        val full = plan.copy(
            recommendation = rec && (now || cond),
            stop = if (now || (cond && rec)) p.dbl("stop_loss") else null,
            target = if (now || (cond && rec)) p.dbl("target") else null,
            // probabilities only ever accompany a qualified recommendation (the server enforces calibration)
            pTarget = if (rec) p.dbl("p_target_first") else null, pStop = if (rec) p.dbl("p_stop_first") else null,
            pTimeout = if (rec) p.dbl("p_timeout") else null, pFill = if (rec) p.dbl("p_fill") else null,
            evPct = if (rec) p.dbl("expected_net_return_pct") else null,
            medianDaysToTarget = if (rec) p.dbl("median_days_to_target") else null,
            fillDays = if (p.isNull("fill_days")) null else p.optInt("fill_days"))
        if ((now || (cond && rec)) && (full.entryLow == null || full.stop == null || full.target == null)) return null
        return full
    }

    private fun JSONObject.perfList(k: String): List<Perf> {
        val a: JSONArray = optJSONArray(k) ?: return emptyList()
        return (0 until a.length()).mapNotNull { i ->
            val e = a.optJSONObject(i) ?: return@mapNotNull null
            Perf(e.optString("source"), e.optString("unit"), e.optInt("trades", 0).coerceAtLeast(0),
                e.optInt("hits", 0).coerceAtLeast(0), e.optInt("pending", 0), e.optInt("not_filled", 0),
                e.dbl("avg_win"), e.dbl("avg_loss"), e.dbl("expectancy"), e.dbl("max_drawdown"), e.str("period"),
                e.dbl("direction_accuracy"), e.dbl("direction_baseline"), e.dbl("baseline_expectancy"),
                if (e.has("qualified") && !e.isNull("qualified")) e.optBoolean("qualified") else null)
        }
    }

    private fun JSONObject.horizons(k: String): List<HorizonProb> {
        val a: JSONArray = optJSONArray(k) ?: return emptyList()
        return (0 until a.length()).map {
            val e = a.getJSONObject(it)
            HorizonProb(e.getInt("horizon_minutes"), e.getDouble("p_target_first"), e.getDouble("p_stop_first"),
                e.getDouble("p_neither"), e.getBoolean("qualified"))
        }
    }
    private fun JSONObject.evidence(k: String): List<EvidenceItem> {
        val a: JSONArray = optJSONArray(k) ?: return emptyList()
        return (0 until a.length()).map {
            val e = a.getJSONObject(it)
            EvidenceItem(e.getString("engine"), e.getString("text_ar"), e.getDouble("weight"), e.reason("text_ref"))
        }
    }
}
