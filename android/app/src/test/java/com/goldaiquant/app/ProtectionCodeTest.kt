package com.goldaiquant.app

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.util.Random

class ProtectionCodeTest {
    @Test fun codeFormatHasNoPersonalData() {
        val r = Random(1)
        repeat(200) {
            val c = InstallCode.make(r)
            assertTrue(c, InstallCode.isValid(c))
        }
        assertFalse(InstallCode.isValid("ali@gmail.com"))
        assertFalse(InstallCode.isValid("AQ-0O1I-LLLL"))
    }

    /** Guard: recommendation texts must not become selectable / copyable, and no copy-to-clipboard feature exists. */
    @Test fun noCopyOrSelectionInTheUi() {
        val src = File("src/main/java").walkTopDown().filter { it.extension == "kt" }.joinToString("\n") { it.readText() }
        for (bad in listOf("SelectionContainer", "LocalClipboardManager", "LocalClipboard.current", "setPrimaryClip",
                "ClipboardManager")) assertFalse("found $bad", src.contains(bad))
        assertTrue(src.contains("FLAG_SECURE") && src.contains("SecureFlagPolicy.SecureOn"))
    }
}
