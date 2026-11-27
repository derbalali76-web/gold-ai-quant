package com.goldaiquant.app

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/** Keeps the server's copy of this phone's alerts in sync (anonymous token only; nothing personal). */
object Push {
    private const val OK_AT = "push_ok_at"
    private const val FRESH_MS = 60 * 60 * 1000L

    /** True while the server confirmed it can push: the background worker then leaves alerts to the server. */
    fun active(ctx: Context): Boolean {
        val p = ctx.getSharedPreferences("gold_ai_quant", Context.MODE_PRIVATE)
        return System.currentTimeMillis() - p.getLong(OK_AT, 0L) < FRESH_MS
    }

    /** [trades]: open automatic test buys; their targets go to the server as alerts keyed «jt|id», so the server
     *  (which also looks at the highest price since its last check) can say «time to sell» within minutes. */
    fun body(token: String, assets: Set<String>, alerts: List<PriceAlert>, lang: String,
             trades: List<Journal.Trade> = emptyList()): String =
        JSONObject().put("token", token).put("lang", lang).put("assets", JSONArray(assets.toList()))
            .put("alerts", JSONArray(alerts.map {
                JSONObject().put("asset", it.asset).put("dir", it.dir).put("price", it.price).put("label", it.label).put("key", it.key)
            } + trades.takeLast(20).map {
                JSONObject().put("asset", it.asset).put("dir", "ABOVE").put("price", Journal.target(it)).put("label", "jt")
                    .put("key", "jt|" + it.id)
            })).toString()

    suspend fun sync(ctx: Context, fcmToken: String? = null) = withContext(Dispatchers.IO) {
        val p = ctx.getSharedPreferences("gold_ai_quant", Context.MODE_PRIVATE)
        val url = p.getString("server_url", null) ?: return@withContext
        val api = ApiClient(url, p.getString("token", "") ?: "")
        val tok = fcmToken ?: try {
            com.google.android.gms.tasks.Tasks.await(com.google.firebase.messaging.FirebaseMessaging.getInstance().token)
        } catch (e: Exception) { null } ?: return@withContext
        val lang = LanguageStore.resolve(ctx).tag
        if (!p.getBoolean("notify", false)) {
            api.pushRegister(JSONObject().put("token", tok).toString(), unregister = true)
            p.edit().remove(OK_AT).apply()
            return@withContext
        }
        val ok = api.pushRegister(body(tok, SignalWorker.alertAssets(p) + Journal.load(p).filter { it.auto && it.open }.map { it.asset },
            PriceAlerts.load(p), lang, Journal.load(p).filter { it.auto && it.open }))
        if (ok) p.edit().putLong(OK_AT, System.currentTimeMillis()).apply() else p.edit().remove(OK_AT).apply()
    }
}
