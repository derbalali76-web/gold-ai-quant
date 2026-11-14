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
    val track: List<TrackItem> = emptyList(),
    val trust: Trust? = null,
)

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("gold_ai_quant", Context.MODE_PRIVATE)
    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state

    init {
        val cached = prefs.getString("last_decision", null)?.let {
            try { DecisionParser.parse(it) } catch (e: Exception) { null }
        }
        _state.update {
            it.copy(
                serverUrl = prefs.getString("server_url", it.serverUrl) ?: it.serverUrl,
                token = prefs.getString("token", "") ?: "",
                liveMode = prefs.getBoolean("live_mode", false),
                notify = prefs.getBoolean("notify", false),
                decision = cached,
                selectedHorizon = HorizonModel.resolve(prefs.getString("horizon", null), cached),
                decisionFromCache = cached != null,
                receivedAt = prefs.getLong("last_received", 0L).takeIf { v -> v > 0 }?.let(Instant::ofEpochMilli),
                trust = TrustParser.parse(prefs.getString("trust", null)),
            )
        }
        startPrefetchLoop()
        loadTrust()
    }

    /** Silent background refresh: the server keeps a fresh decision ready, so a later tap shows it at once. */
    private fun startPrefetchLoop() {
        viewModelScope.launch {
            while (true) {
                val s = _state.value
                if (s.liveMode && !s.loading) {
                    try {
                        val f = ApiClient(s.serverUrl, s.token).decision("LIVE", 0)
                        val now = Instant.now()
                        _state.update {
                            if (!it.liveMode || it.loading) it
                            else it.copy(decision = f.decision, decisionFromCache = false, receivedAt = now, error = null,
                                selectedHorizon = HorizonModel.resolve(it.selectedHorizon, f.decision))
                        }
                        prefs.edit().putString("last_decision", f.raw).putLong("last_received", now.toEpochMilli()).apply()
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
        if (now - trustAt < 20 * 60_000L && _state.value.trust != null) return
        trustAt = now
        viewModelScope.launch {
            val body = TrustLedger.fetch() ?: return@launch
            val t = TrustParser.parse(body) ?: return@launch
            prefs.edit().putString("trust", body).apply()
            _state.update { it.copy(trust = t) }
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
        SignalWorker.schedule(getApplication(), v)
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
                val f = ApiClient(s.serverUrl, s.token).decision(if (s.liveMode) "LIVE" else "DEMO", s.demoStep)
                val now = Instant.now()
                _state.update {
                    it.copy(loading = false, decision = f.decision, decisionFromCache = false, receivedAt = now,
                        selectedHorizon = HorizonModel.resolve(it.selectedHorizon, f.decision))
                }
                prefs.edit().putString("last_decision", f.raw).putLong("last_received", now.toEpochMilli()).apply()
                loadTrack()
            } catch (e: ApiException) {
                _state.update { it.copy(loading = false, error = e) }
            } catch (e: Exception) {
                _state.update { it.copy(loading = false, error = ApiException(ErrorKind.UNEXPECTED, e.javaClass.simpleName)) }
            }
        }
    }
}
