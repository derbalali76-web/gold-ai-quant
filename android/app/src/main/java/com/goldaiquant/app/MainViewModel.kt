package com.goldaiquant.app

import android.app.Application
import android.content.Context
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.Instant

data class UiState(
    val serverUrl: String = "https://gold-ai-quant.onrender.com",
    val token: String = "",
    val liveMode: Boolean = false,
    val demoStep: Int = 0,
    val loading: Boolean = false,
    val decision: Decision? = null,
    val decisionFromCache: Boolean = false,
    val receivedAt: Instant? = null,
    val error: ApiException? = null,
    val selectedHorizon: String = "HOURS",
    val notify: Boolean = false,
    val te: TeState? = null,          // experimental live paper trades (public ledger)
    val teNotify: Boolean = false,
    val track: List<TrackItem> = emptyList(),
    val trustAll: Map<String, Trust> = emptyMap(),
    val briefs: List<BriefRow> = emptyList(),
    val rangeTracks: Map<String, Map<String, RangeTrack>> = emptyMap(),
    val rangeRows: List<RangeRow> = emptyList(),
    val range: RangeInfo? = null,
    val asset: String = "XAU",  // XAU | BTC | ETH | SOL
    val positions: Map<String, String> = emptyMap(),  // asset -> CASH | HOLD (stored on the phone only)
    val alertAssets: Set<String> = setOf("XAU"),  // alerts only for the assets this trader follows
    val priceAlerts: List<PriceAlert> = emptyList(),  // one-tap "Alert me" alerts (phone only)
    val candles: Map<String, Candles> = emptyMap(),  // "ASSET/TF" -> closed candles for the chart
    val calendar: CalendarInfo? = null,
    val touch: TouchInfo? = null,
    val touchLoading: Boolean = false,
    val touchFailed: Boolean = false,
    val live: Map<String, LiveTick> = emptyMap(),  // crypto live price (Binance public ticker), display only
    val onboarded: Boolean = true,
) {
    val trust: Trust? get() = trustAll[asset]
    val position: String get() = positions[asset] ?: "CASH"
}

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("gold_ai_quant", Context.MODE_PRIVATE)
    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state

    private fun key(asset: String) = if (asset == "XAU") "last_decision" else "last_decision_$asset"

    private fun cachedFor(asset: String): Decision? = prefs.getString(key(asset), null)?.let {
        try { DecisionParser.parse(it) } catch (e: Exception) { null }
    }

    /** Switch the analysed asset: show its last saved analysis at once, then refresh it. */
    fun setAsset(a: String) {
        if (a == _state.value.asset) return
        prefs.edit().putString("asset", a).apply()
        val cached = cachedFor(a)
        _state.update { it.copy(asset = a, decision = cached, decisionFromCache = cached != null, error = null,
            selectedHorizon = HorizonModel.resolve(it.selectedHorizon, cached)) }
        ask()
    }

    /** How the analysis is phrased for this asset: the user has cash, or already holds it. Display only. */
    fun setPosition(p: String) {
        val a = _state.value.asset
        prefs.edit().putString("position_$a", p).apply()
        _state.update { it.copy(positions = it.positions + (a to p)) }
    }

    init {
        val asset0 = prefs.getString("asset", "XAU") ?: "XAU"
        val cached = prefs.getString(if (asset0 == "XAU") "last_decision" else "last_decision_$asset0", null)?.let {
            try { DecisionParser.parse(it) } catch (e: Exception) { null }
        }
        _state.update {
            it.copy(
                serverUrl = prefs.getString("server_url", it.serverUrl) ?: it.serverUrl,
                token = prefs.getString("token", "") ?: "",
                liveMode = prefs.getBoolean("live_mode", false),
                notify = prefs.getBoolean("notify", false),
                te = TradeOpp.parse(prefs.getString("te_state", null)),
                teNotify = prefs.getBoolean("te_notify", false),
                decision = cached,
                selectedHorizon = HorizonModel.resolve(prefs.getString("horizon", null), cached),
                decisionFromCache = cached != null,
                receivedAt = prefs.getLong("last_received", 0L).takeIf { v -> v > 0 }?.let(Instant::ofEpochMilli),
                trustAll = TrustParser.parseAll(prefs.getString("trust", null)),
                briefs = Record.parse(prefs.getString("trust", null)),
                rangeTracks = Record.rangeTracks(prefs.getString("trust", null)),
                rangeRows = Record.rangeRows(prefs.getString("trust", null)),
                asset = asset0,
                alertAssets = SignalWorker.alertAssets(prefs),
                priceAlerts = PriceAlerts.load(prefs),
                onboarded = prefs.getBoolean("onboarded", false),
                positions = listOf("XAU", "BTC", "ETH", "SOL").associateWith { a -> prefs.getString("position_$a", "CASH") ?: "CASH" },
            )
        }
        startPrefetchLoop()
        loadTrust()
        syncPush()
    }

    /** Silent background refresh: the server keeps a fresh decision ready, so a later tap shows it at once. */
    private fun startPrefetchLoop() {
        viewModelScope.launch {
            while (true) {
                val s = _state.value
                if (s.liveMode && !s.loading) {
                    try {
                        val f = ApiClient(s.serverUrl, s.token).decision("LIVE", 0, s.asset)
                        val now = Instant.now()
                        _state.update {
                            if (!it.liveMode || it.loading || it.asset != s.asset) it
                            else it.copy(decision = f.decision, decisionFromCache = false, receivedAt = now, error = null,
                                selectedHorizon = HorizonModel.resolve(it.selectedHorizon, f.decision))
                        }
                        prefs.edit().putString(key(s.asset), f.raw).putLong("last_received", now.toEpochMilli()).apply()
                        if (_state.value.track.isEmpty()) loadTrack()
                    } catch (e: Exception) { /* silent: the tap path reports errors */ }
                }
                kotlinx.coroutines.delay(if (_state.value.decision == null) 20_000L else 240_000L)
            }
        }
    }

    /** The selected horizon is remembered across launches; the next decision keeps it when still offered. */
    fun selectHorizon(h: String) {
        _state.update { it.copy(selectedHorizon = h) }
        prefs.edit().putString("horizon", h).apply()
    }

    fun setServerUrl(v: String) {
        _state.update { it.copy(serverUrl = v.trim()) }
        prefs.edit().putString("server_url", v.trim()).apply()
    }

    fun setToken(v: String) {
        _state.update { it.copy(token = v.trim()) }
        prefs.edit().putString("token", v.trim()).apply()
    }

    private var trustAt = 0L

    /** Public ledger stats: works in every mode (no server, no token); refreshed at most every 20 minutes. */
    fun loadTrust() {
        val now = System.currentTimeMillis()
        if (now - trustAt < 20 * 60_000L && _state.value.trustAll.isNotEmpty()) return
        trustAt = now
        viewModelScope.launch {
            TrustLedger.fetch(TradeOpp.URL)?.let { b ->
                TradeOpp.parse(b)?.let { t -> prefs.edit().putString("te_state", b).apply(); _state.update { it.copy(te = t) } }
            }
        }
        viewModelScope.launch {
            val body = TrustLedger.fetch() ?: return@launch
            val t = TrustParser.parseAll(body).takeIf { it.isNotEmpty() } ?: return@launch
            prefs.edit().putString("trust", body).apply()
            _state.update { it.copy(trustAll = t, briefs = Record.parse(body), rangeTracks = Record.rangeTracks(body),
                rangeRows = Record.rangeRows(body)) }
        }
    }

    private fun loadTrack() {
        val s = _state.value
        if (!s.liveMode) return
        viewModelScope.launch {
            val t = ApiClient(s.serverUrl, s.token).track()
            if (t.isNotEmpty()) _state.update { it.copy(track = t) }
        }
    }

    /** Background alerts for validated signals (needs live mode on the server side; checks every 15 min). */
    fun setNotify(v: Boolean) {
        _state.update { it.copy(notify = v) }
        prefs.edit().putBoolean("notify", v).apply()
        SignalWorker.schedule(getApplication(), v || _state.value.teNotify)
        syncPush()
    }

    /** Alert when a new experimental trade appears (checked by the background worker every 15 min). */
    fun setTeNotify(v: Boolean) {
        _state.update { it.copy(teNotify = v) }
        prefs.edit().putBoolean("te_notify", v).apply()
        // a trade already on screen is not announced again
        if (v) _state.value.te?.active?.let { prefs.edit().putInt("te_notified", maxOf(prefs.getInt("te_notified", 0), it.seq)).apply() }
        SignalWorker.schedule(getApplication(), v || _state.value.notify)
    }

    fun finishOnboarding() {
        prefs.edit().putBoolean("onboarded", true).apply()
        _state.update { it.copy(onboarded = true) }
    }

    /** Closed candles for the chart / sparkline; silent on failure (the chart then says so). */
    fun loadBars(asset: String, tf: String) {
        val s = _state.value
        viewModelScope.launch {
            val c = MarketClient(s.serverUrl, s.token).bars(asset, tf) ?: return@launch
            _state.update { it.copy(candles = it.candles + ("$asset/$tf" to c)) }
        }
    }

    private var rangeKey = ""

    /** Experimental closing range for the strip under the price; refreshed at most every 10 minutes per asset. */
    fun loadRange(asset: String) {
        val s = _state.value
        val key = asset + "|" + (System.currentTimeMillis() / 600_000L)
        if (key == rangeKey && s.range?.asset == asset) return
        rangeKey = key
        viewModelScope.launch {
            val r = MarketClient(s.serverUrl, s.token).range(asset)
            _state.update { st -> if (st.asset != asset) st else st.copy(range = r) }
        }
    }

    fun loadTouch(asset: String, prices: List<Double>) {
        val s = _state.value
        _state.update { it.copy(touchLoading = true) }
        viewModelScope.launch {
            val t = MarketClient(s.serverUrl, s.token).touch(asset, prices.distinct())
            // a failed request (server asleep, updating or old) is not "not available": the dialog says which
            _state.update { it.copy(touch = t ?: it.touch, touchLoading = false, touchFailed = t == null) }
        }
    }

    fun loadCalendar() {
        val s = _state.value
        viewModelScope.launch {
            val c = MarketClient(s.serverUrl, s.token).calendar() ?: return@launch
            _state.update { it.copy(calendar = c) }
        }
    }

    /** One live-price poll for the current crypto asset (called every few seconds while the screen is visible). */
    suspend fun pollLive() {
        val a = _state.value.asset
        if (a == "XAU") return
        val p = MarketClient.livePrice(a) ?: return
        _state.update { it.copy(live = it.live + (a to LiveTick(p, System.currentTimeMillis()))) }
    }

    /** Keep the server's copy of this phone's alerts current (Firebase push); silent, best effort. */
    fun syncPush() {
        viewModelScope.launch { try { Push.sync(getApplication()) } catch (e: Exception) { } }
    }

    /** "Alert me": add or remove a one-shot price alert; alerts need notifications on (asked by the screen). */
    fun togglePriceAlert(a: PriceAlert) {
        val next = PriceAlerts.toggle(_state.value.priceAlerts, a)
        PriceAlerts.save(prefs, next)
        _state.update { it.copy(priceAlerts = next) }
        syncPush()
    }

    /** Which assets may send alerts (each trader follows only the markets they trade). */
    fun toggleAlertAsset(a: String) {
        val cur = _state.value.alertAssets
        val next = if (a in cur) cur - a else cur + a
        prefs.edit().putString("alert_assets", next.joinToString(",")).apply()
        _state.update { it.copy(alertAssets = next) }
        syncPush()
    }

    fun setLiveMode(v: Boolean) {
        _state.update { it.copy(liveMode = v, decision = null, error = null) }
        prefs.edit().putBoolean("live_mode", v).apply()
    }

    fun nextDemoMoment() {
        _state.update { it.copy(demoStep = (it.demoStep + 1) % 40) }
        ask()
    }

    fun ask() {
        val s = _state.value
        if (s.loading) return
        _state.update { it.copy(loading = true, error = null) }
        loadTrust()
        viewModelScope.launch {
            try {
                val f = ApiClient(s.serverUrl, s.token).decision(if (s.liveMode) "LIVE" else "DEMO", s.demoStep, s.asset)
                val now = Instant.now()
                _state.update {
                    if (it.asset != s.asset) it.copy(loading = false)  // the user switched asset meanwhile
                    else it.copy(loading = false, decision = f.decision, decisionFromCache = false, receivedAt = now,
                        selectedHorizon = HorizonModel.resolve(it.selectedHorizon, f.decision))
                }
                prefs.edit().putString(key(s.asset), f.raw).putLong("last_received", now.toEpochMilli()).apply()
                loadTrack()
                loadBars(s.asset, "H1")
                PriceWidget.refresh(getApplication())
            } catch (e: ApiException) {
                _state.update { it.copy(loading = false, error = e) }
            } catch (e: Exception) {
                _state.update { it.copy(loading = false, error = ApiException(ErrorKind.UNEXPECTED, e.javaClass.simpleName)) }
            }
        }
    }
}
