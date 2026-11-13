"""AI Decision Court (V4): BUY/SELL is issued only if three independent judges all approve.

  1. Evidence judge     — data firewall + point-in-time ledger + independent supporting evidence
  2. Statistical judge  — qualified/calibrated model, expected NET value after costs (Anti-Trade rules)
  3. Risk judge         — the Independent Risk Governor
Prediction accuracy is never accepted as a substitute for net profitability: the statistical judge rules on
expected value after costs. Anything missing => WAIT.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MIN_INDEPENDENT_ENGINES = 2


@dataclass
class Judgement:
    judge: str
    passed: bool
    reasons_ar: list = field(default_factory=list)


def evidence_judge(firewall, pit_summary: dict, supporting: list, contrary: list) -> Judgement:
    r = list(firewall.blocking)
    if not pit_summary.get("passed", False):
        r.append(f"مدخلات غير متاحة وقت القرار: {[v['input'] for v in pit_summary.get('violations', [])]}")
    engines = {e.engine for e in supporting}
    if len(engines) < MIN_INDEPENDENT_ENGINES:
        r.append(f"أدلة مستقلة غير كافية ({len(engines)} محرك؛ المطلوب {MIN_INDEPENDENT_ENGINES})")
    s_w, c_w = sum(abs(e.weight) for e in supporting), sum(abs(e.weight) for e in contrary)
    if c_w >= s_w:
        r.append("الأدلة المعاكسة لا تقل عن الأدلة الداعمة")
    return Judgement("evidence", not r, r)


def statistical_judge(anti_trade_reasons: list) -> Judgement:
    return Judgement("statistics", not anti_trade_reasons, list(anti_trade_reasons))


def risk_judge(governor_verdict) -> Judgement:
    return Judgement("risk_governor", governor_verdict.approved, list(governor_verdict.reasons_ar))


def rule(judgements: list[Judgement]) -> tuple[bool, list[str]]:
    reasons = [f"[{j.judge}] {x}" for j in judgements for x in j.reasons_ar]
    return all(j.passed for j in judgements), reasons
