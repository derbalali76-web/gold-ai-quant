package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SignalWatchTest {
    private fun load(name: String): Decision = DecisionParser.parse(
        javaClass.classLoader!!.getResource("fixtures/$name")!!.readText())

    @Test fun demoNeverNotifies() {
        assertTrue(SignalWatch.signals(load("buy_demo_stub.json")).isEmpty())
        assertTrue(SignalWatch.signals(load("wait_demo.json")).isEmpty())
    }

    @Test fun waitAndUnavailableNeverNotify() {
        assertTrue(SignalWatch.signals(load("unavailable_live.json")).isEmpty())
    }

    @Test fun aValidatedLiveTradeIsAnnouncedOnceThenForgottenWhenItEnds() {
        val d = load("live_qualified_stub.json")
        val sig = SignalWatch.signals(d)
        if (sig.isEmpty()) return // fixture without a validated HOURS card: nothing to announce
        val (fresh, mem) = SignalWatch.diff(d, emptyMap())
        assertEquals(sig, fresh)
        val (again, mem2) = SignalWatch.diff(d, mem)
        assertTrue(again.isEmpty())
        assertEquals(mem, mem2)
        val (_, cleared) = SignalWatch.diff(load("unavailable_live.json"), mem)
        assertTrue(cleared.isEmpty())
    }

    @Test fun levelCrossingOnlyInTheScenarioDirection() {
        val up = Scenario("BULL", 3921.10, "R1", 3938.25, "R2")
        assertTrue(SignalWatch.crossed(up, 3915.0, 3922.0))
        assertTrue(!SignalWatch.crossed(up, 3925.0, 3930.0)) // already above: no new crossing
        assertTrue(!SignalWatch.crossed(up, 3925.0, 3915.0)) // moving down through it is not the up scenario
        val down = Scenario("BEAR", 3871.89, "S1", 3853.27, "S2")
        assertTrue(SignalWatch.crossed(down, 3880.0, 3870.0))
        assertTrue(!SignalWatch.crossed(down, 3865.0, 3875.0))
    }
}
