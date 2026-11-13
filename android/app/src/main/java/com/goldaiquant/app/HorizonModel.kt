package com.goldaiquant.app

/** What the probabilities card can honestly say for the selected horizon. */
enum class ProbState { AVAILABLE, NOT_CALIBRATED, DEMO, HORIZON_UNSUPPORTED, NONE }

data class Outcomes(val target: Double, val stop: Double, val neither: Double, val samples: Int)

/** Everything the main card, levels, trend, probabilities and details need for ONE horizon. */
data class HorizonCard(
    val horizon: String,
    val action: Action,
    val tilt: Int,
    val stance: Reason?,
    val entryLow: Double?,
    val entryHigh: Double?,
    val stop: Double?,
    val target: Double?,
    val durationMinutes: Int?,
    val durationDays: Int?,
    val waitForPrice: Double?,
    val reason: Reason?,
    val warnings: List<Reason>,
    val facts: List<Reason>,
    val levels: Levels?,
    val trend: Trend?,
    val probState: ProbState,
    val outcomes: Outcomes?,
    val validated: Boolean,
    val hitRate: Double?,
    val baseRate: Double?,
    val samples: Int,
    val validation: Reason?,
    val method: Reason?,
) {
    val entryMid: Double? get() = if (entryLow != null && entryHigh != null) (entryLow + entryHigh) / 2 else entryLow ?: entryHigh
    val isTrade: Boolean get() = action == Action.BUY || action == Action.SELL
}

/** How a level relates to the current recommendation of the selected horizon. */
enum class LevelRelation { OBSTACLE_BEFORE_TARGET, PROTECTS_STOP, STOP_INSIDE_ZONE, NOT_IN_PATH, NO_TRADE_CONTEXT }

object HorizonModel {
    val ORDER = listOf("HOURS", "WEEK", "MONTH")

    /** The saved selection if the decision still offers it, otherwise the first available horizon (HOURS by default). */
    fun resolve(saved: String?, d: Decision?): String {
        val available = available(d)
        return if (saved != null && saved in available) saved else available.firstOrNull() ?: "HOURS"
    }

    fun available(d: Decision?): List<String> {
        if (d == null) return ORDER
        val have = d.outlooks.map { it.horizon }.toSet()
        return ORDER.filter { it == "HOURS" || it in have }
    }

    fun card(d: Decision, horizon: String): HorizonCard {
        val o = d.outlooks.firstOrNull { it.horizon == horizon }
        if (horizon == "HOURS") return hours(d, o)
        if (o == null) return unavailable(horizon)
        return HorizonCard(
            horizon = horizon, action = o.action, tilt = o.tilt, stance = o.stance,
            entryLow = o.entryPrice, entryHigh = o.entryPrice, stop = o.stopLoss, target = o.target,
            durationMinutes = null, durationDays = o.horizonDays, waitForPrice = o.waitForPrice,
            reason = o.reason ?: Reason("raw", emptyList(), o.reasonAr), warnings = o.warnings, facts = o.facts,
            levels = o.levels, trend = o.trend, probState = ProbState.HORIZON_UNSUPPORTED, outcomes = null,
            validated = o.validated, hitRate = o.hitRate, baseRate = o.baseRate, samples = o.samples,
            validation = o.validation, method = o.method,
        )
    }

    private fun hours(d: Decision, o: Outlook?): HorizonCard {
        val trade = d.action == Action.BUY || d.action == Action.SELL
        val state = when {
            d.action == Action.UNAVAILABLE -> ProbState.NONE
            d.isDemo -> ProbState.DEMO
            d.displayableOutcomes == null -> ProbState.NOT_CALIBRATED
            else -> ProbState.AVAILABLE
        }
        val oc = d.displayableOutcomes?.let { Outcomes(it.first, it.second, it.third, d.calibrationSamples) }
        return HorizonCard(
            horizon = "HOURS", action = d.action, tilt = o?.tilt ?: 0, stance = o?.stance,
            entryLow = if (trade) d.entryMin else null, entryHigh = if (trade) d.entryMax else null,
            stop = if (trade) d.stopLoss else null, target = if (trade) d.tp1 else null,
            durationMinutes = if (trade) d.horizonMinutes else null, durationDays = null,
            waitForPrice = if (d.action == Action.WAIT) d.waitForPrice ?: d.alternativeEntryPrice else null,
            reason = d.reasonShort ?: d.reasonShortAr?.let { Reason("raw", emptyList(), it) },
            warnings = listOfNotNull(d.warning ?: d.warningAr?.let { Reason("raw", emptyList(), it) }),
            facts = emptyList(), levels = d.levels, trend = d.trend, probState = state, outcomes = oc,
            validated = o?.validated ?: false, hitRate = null, baseRate = null, samples = 0,
            validation = o?.validation, method = o?.method,
        )
    }

    private fun unavailable(h: String) = HorizonCard(
        h, Action.UNAVAILABLE, 0, null, null, null, null, null, null, null, null, null, emptyList(), emptyList(),
        null, null, ProbState.HORIZON_UNSUPPORTED, null, false, null, null, 0, null, null,
    )

    /** Relation of [l] to the card's recommendation. Levels never create a trade; they only explain this one. */
    fun relation(l: Level, isSupport: Boolean, c: HorizonCard): LevelRelation {
        val entry = c.entryMid
        val stop = c.stop
        val target = c.target
        if (!c.isTrade || entry == null || stop == null || target == null) return LevelRelation.NO_TRADE_CONTEXT
        val buy = c.action == Action.BUY
        if (stop in l.zoneLow..l.zoneHigh) return LevelRelation.STOP_INSIDE_ZONE
        return if (buy) {
            when {
                !isSupport && l.zoneLow > entry && l.zoneLow < target -> LevelRelation.OBSTACLE_BEFORE_TARGET
                isSupport && l.zoneHigh < entry && l.zoneLow > stop -> LevelRelation.PROTECTS_STOP
                else -> LevelRelation.NOT_IN_PATH
            }
        } else {
            when {
                isSupport && l.zoneHigh < entry && l.zoneHigh > target -> LevelRelation.OBSTACLE_BEFORE_TARGET
                !isSupport && l.zoneLow > entry && l.zoneHigh < stop -> LevelRelation.PROTECTS_STOP
                else -> LevelRelation.NOT_IN_PATH
            }
        }
    }
}
