package com.goldaiquant.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder

/** [detail] is a technical diagnostic (HTTP code, parser message) shown in small type; never the main message. */
class ApiException(val kind: ErrorKind, val detail: String? = null) : Exception(kind.name + (detail?.let { ": $it" } ?: ""))

data class Fetched(val raw: String, val decision: Decision)

class ApiClient(private val baseUrl: String, private val token: String = "") {
    suspend fun decision(mode: String, demoStep: Int): Fetched = withContext(Dispatchers.IO) {
        UrlPolicy.check(baseUrl)?.let { throw ApiException(it) }
        val url = URI(baseUrl.trimEnd('/') + "/decision?mode=" + URLEncoder.encode(mode, "UTF-8") +
            "&demo_step=" + demoStep).toURL()
        val conn = (url.openConnection() as HttpURLConnection).apply {
            connectTimeout = 20_000
            readTimeout = 100_000 // a sleeping free cloud service needs ~1 minute to wake up
            requestMethod = "GET"
            setRequestProperty("Accept", "application/json")
            if (token.isNotBlank()) setRequestProperty("X-Goldquant-Token", token.trim())
        }
        try {
            val code = try { conn.responseCode } catch (e: java.net.SocketTimeoutException) {
                throw ApiException(ErrorKind.TIMEOUT_WAKING)
            } catch (e: Exception) {
                throw ApiException(ErrorKind.NO_CONNECTION)
            }
            if (code == 401) throw ApiException(ErrorKind.BAD_TOKEN)
            if (code == 502 || code == 503) throw ApiException(ErrorKind.SERVER_STARTING)
            if (code != 200) throw ApiException(ErrorKind.SERVER_ERROR, code.toString())
            val body = conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            if (body.length > 512_000) throw ApiException(ErrorKind.TOO_LARGE)
            try { Fetched(body, DecisionParser.parse(body)) } catch (e: ParseException) {
                throw ApiException(ErrorKind.INVALID_RESPONSE, e.message)
            }
        } finally {
            conn.disconnect()
        }
    }

    /** Live forward log (WEEK / MONTH). Best effort: any failure returns an empty list. */
    suspend fun track(): List<TrackItem> = withContext(Dispatchers.IO) {
        if (UrlPolicy.check(baseUrl) != null) return@withContext emptyList()
        try {
            val conn = (URI(baseUrl.trimEnd('/') + "/outlooks/track").toURL().openConnection() as HttpURLConnection).apply {
                connectTimeout = 15_000; readTimeout = 30_000
                setRequestProperty("Accept", "application/json")
                if (token.isNotBlank()) setRequestProperty("X-Goldquant-Token", token.trim())
            }
            try {
                if (conn.responseCode != 200) emptyList()
                else TrackParser.parse(conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }.take(512_000))
            } finally { conn.disconnect() }
        } catch (e: Exception) { emptyList() }
    }
}
