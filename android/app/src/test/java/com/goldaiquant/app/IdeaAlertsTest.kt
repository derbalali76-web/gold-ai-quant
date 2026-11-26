package com.goldaiquant.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class IdeaAlertsTest {
    private val H = 3600_000L
    private fun idea(k: SimpleAdvice.Kind, buy: Double? = null, sell: Double? = null, inv: Double? = null) =
        SimpleAdvice.Idea(k, buy, sell, inv, 0.3)
    private fun now(i: SimpleAdvice.Idea, trend: String? = "UP", up: Double? = 3660.0, tested: Boolean? = null) =
        IdeaAlerts.Now(i, up, tested, trend)

    @Test fun buyNowIsSentOnceThenTarget() {
        val n = now(idea(SimpleAdvice.Kind.BUY_NOW, 3611.0, 3640.0, 3590.0))
        val s1 = IdeaAlerts.step(null, 0, n, 3611.0, 0)
        assertEquals(IdeaAlerts.Msg.NEW, s1.msg)
        assertEquals(3590.0, s1.state!!.stop!!, 0.0)
        val s2 = IdeaAlerts.step(s1.state, s1.coolUntil, n, 3620.0, H)
        assertNull(s2.msg)
        val s3 = IdeaAlerts.step(s2.state, s2.coolUntil, now(idea(SimpleAdvice.Kind.WAIT_DIP, 3611.0, 3660.0, 3590.0)), 3641.0, 2 * H)
        assertEquals(IdeaAlerts.Msg.TARGET, s3.msg)
        assertNull(s3.state)
        // cool-down: no new idea for an hour
        assertNull(IdeaAlerts.step(null, s3.coolUntil, n, 3641.0, 2 * H + 10).msg)
        assertEquals(IdeaAlerts.Msg.NEW, IdeaAlerts.step(null, s3.coolUntil, n, 3641.0, 3 * H + 1).msg)
    }

    @Test fun buyNowFailsAtStopOrTurn() {
        val n = now(idea(SimpleAdvice.Kind.BUY_NOW, 3611.0, 3640.0, 3590.0))
        val a = IdeaAlerts.step(null, 0, n, 3611.0, 0).state
        assertEquals(IdeaAlerts.Msg.FAILED_STOP, IdeaAlerts.step(a, 0, n, 3589.0, H).msg)
        assertEquals(IdeaAlerts.Msg.FAILED_TURN, IdeaAlerts.step(a, 0, now(idea(SimpleAdvice.Kind.CONFLICT)), 3605.0, H).msg)
        assertEquals(IdeaAlerts.Msg.FAILED_TURN, IdeaAlerts.step(a, 0, now(idea(SimpleAdvice.Kind.WAIT), "DOWN"), 3605.0, H).msg)
        assertEquals(IdeaAlerts.Msg.EXPIRED, IdeaAlerts.step(a, 0, n, 3605.0, 25 * H).msg)
    }

    @Test fun sellRebuyTargetIsTheBuyBackAndStopIsAbove() {
        val n = now(idea(SimpleAdvice.Kind.SELL_REBUY, 3611.0, 3640.0), trend = "DOWN")
        val a = IdeaAlerts.step(null, 0, n, 3640.0, 0)
        assertEquals(IdeaAlerts.Msg.NEW, a.msg)
        assertEquals(3660.0, a.state!!.stop!!, 0.0)
        assertEquals(IdeaAlerts.Msg.TARGET, IdeaAlerts.step(a.state, 0, n, 3610.0, H).msg)
        assertEquals(IdeaAlerts.Msg.FAILED_STOP, IdeaAlerts.step(a.state, 0, n, 3661.0, H).msg)
    }

    @Test fun watchIdeaIsReplacedOnlyByADifferentIdea() {
        val w = now(idea(SimpleAdvice.Kind.WAIT, 3500.0, null, 3480.0), "DOWN")
        val a = IdeaAlerts.step(null, 0, w, 3550.0, 0)
        assertEquals(IdeaAlerts.Msg.NEW, a.msg)
        assertNull(IdeaAlerts.step(a.state, 0, w, 3540.0, H).msg)
        val b = IdeaAlerts.step(a.state, 0, now(idea(SimpleAdvice.Kind.BUY_NOW, 3505.0, 3550.0, 3480.0)), 3505.0, 2 * H)
        assertEquals(IdeaAlerts.Msg.NEW, b.msg)
        assertEquals(SimpleAdvice.Kind.BUY_NOW, b.state!!.kind)
    }

    @Test fun noIdeaNoMessageAndStateRoundTrips() {
        assertNull(IdeaAlerts.step(null, 0, now(idea(SimpleAdvice.Kind.CONFLICT)), 3600.0, 0).msg)
        val a = IdeaAlerts.Active(SimpleAdvice.Kind.HOLD_SELL_ABOVE, 3600.0, null, 3640.0, 3590.0, 123L)
        assertEquals(a, IdeaAlerts.decode(IdeaAlerts.encode(a)))
        assertNull(IdeaAlerts.decode(""))
    }
}

class IdeaAlertsUpdateTest {
    private val H = 3600_000L
    private fun now(sell: Double, inv: Double = 67.2) =
        IdeaAlerts.Now(SimpleAdvice.Idea(SimpleAdvice.Kind.BUY_NOW, 71.0, sell, inv, 0.3), 80.0, null, "UP")

    @Test fun targetMoveIsAnnouncedOncePerHour() {
        val a = IdeaAlerts.step(null, 0, now(79.68), 71.0, 0).state!!
        val u = IdeaAlerts.step(a, 0, now(78.57), 71.2, H)
        assertEquals(IdeaAlerts.Msg.UPDATED, u.msg)
        assertEquals(78.57, u.state!!.sellAt!!, 0.0)
        assertEquals(79.68, u.before!!.sellAt!!, 0.0)
        assertEquals(67.2, u.state!!.stop!!, 0.0)
        // moved again 10 minutes later: wait for the hour
        assertNull(IdeaAlerts.step(u.state, 0, now(76.80), 71.2, H + 600_000).msg)
        val u2 = IdeaAlerts.step(u.state, 0, now(76.80), 71.2, 2 * H + 1)
        assertEquals(IdeaAlerts.Msg.UPDATED, u2.msg)
        assertEquals(76.80, u2.state!!.sellAt!!, 0.0)
    }

    @Test fun tinyMoveIsIgnoredAndNewTargetCanBeReached() {
        val a = IdeaAlerts.step(null, 0, now(76.80), 71.0, 0).state!!
        assertNull(IdeaAlerts.step(a, 0, now(76.85), 71.0, 2 * H).msg)
        assertEquals(IdeaAlerts.Msg.TARGET, IdeaAlerts.step(a, 0, now(76.80), 76.9, 3 * H).msg)
    }
}

class IdeaAlertsWithdrawnTest {
    private val H = 3600_000L
    private fun idea(k: SimpleAdvice.Kind) = SimpleAdvice.Idea(k, 68.52, 76.80, 67.20, 0.3)

    @Test fun buyNowWithdrawnOnceThenStillFollowed() {
        val buy = IdeaAlerts.Now(idea(SimpleAdvice.Kind.BUY_NOW), 80.0, null, "UP")
        val wait = IdeaAlerts.Now(idea(SimpleAdvice.Kind.WAIT), 80.0, null, "SIDEWAYS")
        val a = IdeaAlerts.step(null, 0, buy, 70.8, 0).state!!
        val w = IdeaAlerts.step(a, 0, wait, 70.8, H)
        assertEquals(IdeaAlerts.Msg.WITHDRAWN, w.msg)
        assertNull(IdeaAlerts.step(w.state, 0, wait, 70.8, 2 * H).msg)          // said once
        assertEquals(IdeaAlerts.Msg.TARGET, IdeaAlerts.step(w.state, 0, wait, 76.9, 3 * H).msg)  // target still followed
        assertEquals(w.state, IdeaAlerts.decode(IdeaAlerts.encode(w.state)))
    }
}
