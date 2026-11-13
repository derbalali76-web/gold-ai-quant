package com.goldaiquant.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder

/** Enforces ADR-003: https anywhere; plain http only to private/LAN/loopback addresses. */
object UrlPolicy {
    fun check(base: String): String? {
        val uri = try { URI(base.trim()) } catch (e: Exception) { return "عنوان غير صالح" }
        val host = uri.host ?: return "عنوان غير صالح"
        return when (uri.scheme?.lowercase()) {
            "https" -> null
            "http" -> if (isPrivateHost(host)) null else "HTTP غير المشفر مسموح فقط لعناوين الشبكة المحلية"
            else -> "يجب أن يبدأ العنوان بـ http:// أو https://"
        }
    }

    fun isPrivateHost(host: String): Boolean {
        if (host == "localhost") return true
        val p = host.split('.').map { it.toIntOrNull() ?: return false }
        if (p.size != 4 || p.any { it !in 0..255 }) return false
        return p[0] == 10 || p[0] == 127 ||
            (p[0] == 172 && p[1] in 16..31) ||
            (p[0] == 192 && p[1] == 168)
    }
}

class ApiException(val userMessageAr: String) : Exception(userMessageAr)

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
                throw ApiException("الخادم السحابي يستيقظ من السكون — أعد المحاولة بعد دقيقة.")
            } catch (e: Exception) {
                throw ApiException("تعذر الاتصال بخادم التحليل. تحقق من الإنترنت ومن عنوان الخادم في الإعدادات.")
            }
            if (code == 401) throw ApiException("الرمز السري غير صحيح أو مفقود (الإعدادات)")
            if (code == 502 || code == 503) throw ApiException("الخادم السحابي يبدأ التشغيل — أعد المحاولة بعد دقيقة.")
            if (code != 200) throw ApiException("الخادم أعاد خطأ ($code)")
            val body = conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            if (body.length > 512_000) throw ApiException("استجابة كبيرة بشكل غير طبيعي — رُفضت")
            try { Fetched(body, DecisionParser.parse(body)) } catch (e: ParseException) {
                throw ApiException("استجابة غير صالحة من الخادم: ${e.message}")
            }
        } finally {
            conn.disconnect()
        }
    }
}
