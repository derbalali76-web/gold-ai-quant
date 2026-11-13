package com.goldaiquant.app

import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant

/** Mirror of schema/decision.schema.json (v1). Parsed and validated strictly; anything off -> ParseException. */
enum class Action { BUY, SELL, WAIT, UNAVAILABLE }

data class EvidenceItem(val engine: String, val textAr: String, val weight: Double)

data class Trend(val direction: String, val strength: Int?, val labelAr: String, val perTimeframe: Map<String, String>)

data class Level(val name: String, val price: Double, val zoneLow: Double, val zoneHigh: Double, val strength: Int?,
                 val labelAr: String, val tests: Int, val timeframes: List<String>, val brokenRecently: Boolean)

data class Levels(val supports: List<Level>, val resistances: List<Level>, val validated: Boolean, val validationAr: String?)

data class Judgement(val judge: String, val passed: Boolean, val reasonsAr: List<String>)

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
        val o = try { JSONObject(raw) } catch (e: Exception) { throw ParseException("JSON غير صالح") }
        val version = o.req("schema_version")
        if (version.substringBefore('.') != SUPPORTED_MAJOR) throw ParseException("إصدار عقد غير مدعوم: $version")
        val action = try { Action.valueOf(o.req("action")) } catch (e: IllegalArgumentException) {
            throw ParseException("قيمة action غير معروفة")
        }
        val fresh = o.optJSONObject("data_freshness") ?: throw ParseException("data_freshness مفقود")
        val d = Decision(
            schemaVersion = version,
            decisionId = o.req("decision_id"),
            mode = o.req("mode").also { if (it != "DEMO" && it != "LIVE") throw ParseException("mode غير معروف") },
            action = action,
            spotOrProxy = o.req("spot_or_proxy"),
            provider = o.req("provider"),
            quote = o.dbl("quote"),
            quoteTime = o.time("quote_timestamp_utc"),
            analyzedAt = o.time("analyzed_at_utc") ?: throw ParseException("analyzed_at_utc مفقود"),
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
                Trend(t.getString("direction"), if (t.isNull("strength")) null else t.getInt("strength"),
                    t.getString("label_ar"), per?.keys()?.asSequence()?.associateWith { per.getString(it) } ?: emptyMap())
            },
            levels = o.optJSONObject("levels")?.let { lv ->
                Levels(lv.levelList("supports"), lv.levelList("resistances"), lv.getBoolean("validated"), lv.str("validation_ar"))
            },
            quoteChange = o.dbl("quote_change"),
            quoteChangePct = o.dbl("quote_change_pct"),
            reevaluateAr = o.strings("reevaluate_ar"),
        )
        validate(d)
        return d
    }

    private fun validate(d: Decision) {
        if (d.isDemo && d.spotOrProxy != "SYNTHETIC") throw ParseException("وضع تجريبي بدون وسم SYNTHETIC")
        if (d.action == Action.BUY || d.action == Action.SELL) {
            val em = d.entryMin ?: throw ParseException("نطاق الدخول مفقود")
            val ex = d.entryMax ?: throw ParseException("نطاق الدخول مفقود")
            val sl = d.stopLoss ?: throw ParseException("وقف الخسارة مفقود")
            val t1 = d.tp1 ?: throw ParseException("الهدف الأول مفقود")
            if (d.quote == null || d.quoteTime == null || d.validUntil == null) throw ParseException("بيانات السعر/الصلاحية مفقودة")
            if (!d.isFresh) throw ParseException("إشارة على بيانات قديمة")
            if (d.court.isEmpty() || d.court.any { !it.passed }) throw ParseException("إشارة لم تجتز محكمة القرار")
            if (em > ex) throw ParseException("نطاق دخول مقلوب")
            val ok = if (d.action == Action.BUY) sl < em && t1 > ex else sl > ex && t1 < em
            if (!ok) throw ParseException("مستويات غير متسقة مع الاتجاه")
        }
        listOfNotNull(d.probability, d.probabilityStop, d.probabilityNeither).forEach {
            if (it < 0.0 || it > 1.0) throw ParseException("احتمال خارج النطاق")
        }
        if (d.probability != null && d.probabilityStop != null && d.probabilityNeither != null &&
            Math.abs(d.probability + d.probabilityStop + d.probabilityNeither - 1.0) > 1e-3)
            throw ParseException("مجموع الاحتمالات لا يساوي 1")
        d.trend?.strength?.let { if (it !in 0..100) throw ParseException("قوة اتجاه خارج النطاق") }
        d.levels?.let { lv ->
            val all = lv.supports + lv.resistances
            if (!lv.validated && all.any { it.strength != null }) throw ParseException("قوة مستويات رقمية دون تحقق")
            if (all.any { it.strength != null && it.strength !in 0..100 }) throw ParseException("قوة مستوى خارج النطاق")
            if (d.quote != null && (lv.supports.any { it.zoneHigh >= d.quote } || lv.resistances.any { it.zoneLow <= d.quote }))
                throw ParseException("مستويات في الجهة الخاطئة من السعر")
        }
        if (d.isDemo && (d.probability != null || d.horizonProbs.isNotEmpty()))
            throw ParseException("احتمالات في الوضع التجريبي غير مسموحة")
    }

    private fun JSONObject.req(k: String): String {
        if (!has(k) || isNull(k)) throw ParseException("الحقل $k مفقود")
        return getString(k)
    }
    private fun JSONObject.str(k: String): String? = if (!has(k) || isNull(k)) null else getString(k)
    private fun JSONObject.dbl(k: String): Double? = if (!has(k) || isNull(k)) null else getDouble(k).also {
        if (it.isNaN() || it.isInfinite()) throw ParseException("قيمة عددية غير صالحة في $k")
    }
    private fun JSONObject.time(k: String): Instant? = str(k)?.let {
        try { Instant.parse(it) } catch (e: Exception) { throw ParseException("وقت غير صالح في $k") }
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
                e.optInt("tests", 0), e.strings("timeframes"), e.optBoolean("broken_recently", false))
        }
    }
    private fun JSONObject.court(k: String): List<Judgement> {
        val a: JSONArray = optJSONArray(k) ?: return emptyList()
        return (0 until a.length()).map {
            val e = a.getJSONObject(it)
            Judgement(e.getString("judge"), e.getBoolean("passed"), e.strings("reasons_ar"))
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
            EvidenceItem(e.getString("engine"), e.getString("text_ar"), e.getDouble("weight"))
        }
    }
}
