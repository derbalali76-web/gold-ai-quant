package com.goldaiquant.app

import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class UrlPolicyTest {
    @Test fun httpsAllowedEverywhere() {
        assertNull(UrlPolicy.check("https://example.org"))
    }

    @Test fun httpOnlyForPrivateHosts() {
        for (ok in listOf("http://192.168.1.10:8000", "http://10.0.2.2:8000", "http://172.20.3.4", "http://127.0.0.1:8000", "http://localhost:8000"))
            assertNull(ok, UrlPolicy.check(ok))
        for (bad in listOf("http://8.8.8.8", "http://example.org", "http://172.32.0.1", "http://192.169.0.1"))
            assertNotNull(bad, UrlPolicy.check(bad))
    }

    @Test fun rejectsOtherSchemesAndGarbage() {
        for (bad in listOf("ftp://192.168.1.1", "file:///etc/passwd", "not a url", ""))
            assertNotNull(bad, UrlPolicy.check(bad))
    }
}
