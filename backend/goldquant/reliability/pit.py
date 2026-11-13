"""Point-in-Time Intelligence (V4 #1): a per-decision ledger proving every input was available at as_of."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd


@dataclass
class PITLedger:
    as_of: datetime
    entries: list = field(default_factory=list)

    def add(self, name: str, available_at, source: str = "") -> None:
        if available_at is None:
            return
        t = pd.Timestamp(available_at)
        t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
        self.entries.append({"input": name, "available_at": t.isoformat(), "source": source})

    def violations(self) -> list[dict]:
        a = pd.Timestamp(self.as_of)
        return [e for e in self.entries if pd.Timestamp(e["available_at"]) > a]

    def summary(self) -> dict:
        v = self.violations()
        return {"as_of": pd.Timestamp(self.as_of).isoformat(), "inputs": len(self.entries), "violations": v,
                "passed": not v, "latest_input": max((e["available_at"] for e in self.entries), default=None)}
