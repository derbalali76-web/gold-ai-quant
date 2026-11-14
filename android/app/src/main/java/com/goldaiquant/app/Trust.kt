package com.goldaiquant.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URI

/** Public trust ledger (hash-chained, recorded before outcomes). Read-only and public: no token is sent. */
object TrustLedger {
    const val REPO_URL = "https://github.com/derbalali76-web/ai-quant-ledger"
    const val STATS_URL = "https://raw.githubusercontent.com/derbalali76-web/ai-quant-ledger/main/stats.json"

    suspend fun fetch(url: String = STATS_URL): String? = withContext(Dispatchers.IO) {
        try {
            val conn = (URI(url).toURL().openConnection() as HttpURLConnection).apply {
                connectTimeout = 15_000; readTimeout = 20_000
                setRequestProperty("Accept", "application/json")
            }
            try {
                if (conn.responseCode != 200) null
                else conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }.take(512_000)
            } finally { conn.disconnect() }
        } catch (e: Exception) { null }
    }
}

