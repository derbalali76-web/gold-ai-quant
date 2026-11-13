package com.goldaiquant.app

import java.net.URI

/** Why a request failed. The UI maps each kind to a localized message (no text lives in this layer). */
enum class ErrorKind {
    INVALID_URL, HTTP_NOT_LOCAL, BAD_SCHEME, TIMEOUT_WAKING, NO_CONNECTION, BAD_TOKEN, SERVER_STARTING,
    SERVER_ERROR, TOO_LARGE, INVALID_RESPONSE, UNEXPECTED,
}

/** Enforces ADR-003: https anywhere; plain http only to private/LAN/loopback addresses. null = allowed. */
object UrlPolicy {
    fun check(base: String): ErrorKind? {
        val uri = try { URI(base.trim()) } catch (e: Exception) { return ErrorKind.INVALID_URL }
        val host = uri.host ?: return ErrorKind.INVALID_URL
        return when (uri.scheme?.lowercase()) {
            "https" -> null
            "http" -> if (isPrivateHost(host)) null else ErrorKind.HTTP_NOT_LOCAL
            else -> ErrorKind.BAD_SCHEME
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
