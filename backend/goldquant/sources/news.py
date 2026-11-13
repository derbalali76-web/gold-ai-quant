"""News Propagation Engine (V2 #10) + rules-based multilingual event classifier.

Legal sources only: official RSS feeds. Each item keeps source, published_at (from the feed) and fetched_at.
Duplicates across sources are clustered (normalized title + token Jaccard), the first publisher is identified
and the propagation delay to later sources is measured. Nothing is assumed to be real-time.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from defusedxml import ElementTree as ET

from ..providers.http import HttpClient, HttpError, RateLimiter

FEEDS = {
    "federalreserve.gov": ("https://www.federalreserve.gov/feeds/press_all.xml", 1.0),
    "ecb.europa.eu": ("https://www.ecb.europa.eu/rss/press.html", 1.0),
    "bls.gov": ("https://www.bls.gov/feed/bls_latest.xml", 1.0),
}

# keyword -> (event_type, importance 1..3, expected sign for gold; 0 = ambiguous)
RULES = [
    (r"\b(fomc|federal funds|rate decision|monetary policy|interest rates?)\b|الفائدة|السياسة النقدية|taux directeur",
     "MONETARY_POLICY", 3, 0),
    (r"\b(cpi|consumer price|inflation|pce)\b|التضخم|أسعار المستهلك|inflation", "INFLATION", 3, 0),
    (r"\b(payrolls?|employment situation|unemployment|jobs report)\b|الوظائف|البطالة|emploi|chômage", "LABOR", 3, 0),
    (r"\b(war|missile|attack|invasion|sanctions?)\b|حرب|هجوم|عقوبات|guerre", "GEOPOLITICAL", 2, 1),
    (r"\b(gold reserves?|central bank (purchases|buying) of gold)\b|احتياطي الذهب", "CENTRAL_BANK_GOLD", 2, 1),
    (r"\b(speech|testimony|remarks)\b|خطاب|شهادة|discours", "SPEECH", 1, 0),
]


@dataclass
class NewsItem:
    source: str
    title: str
    link: str
    published_at: datetime
    fetched_at: datetime
    credibility: float
    event_type: str = "OTHER"
    importance: int = 0
    expected_sign: int = 0

    @property
    def key(self) -> str:
        return hashlib.sha1(normalize(self.title).encode()).hexdigest()[:16]


@dataclass
class NewsCluster:
    items: list = field(default_factory=list)

    @property
    def first(self) -> NewsItem:
        return min(self.items, key=lambda i: i.published_at)

    def propagation(self) -> list[dict]:
        f = self.first
        return [{"source": i.source, "delay_s": (i.published_at - f.published_at).total_seconds()}
                for i in sorted(self.items, key=lambda i: i.published_at)]


def normalize(t: str) -> str:
    t = re.sub(r"[^\w\s]", " ", t.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


STOP = {"by", "the", "of", "a", "an", "to", "in", "on", "for", "and", "at", "is", "le", "la", "de", "في", "من", "على"}


def _tokens(t: str) -> set:
    out = set()
    for w in normalize(t).split():
        if w in STOP:
            continue
        for suf in ("ed", "es", "s"):
            if len(w) > 4 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.add(w)
    return out


def jaccard(a: str, b: str) -> float:
    sa, sb = _tokens(a), _tokens(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def classify(item: NewsItem) -> NewsItem:
    text = item.title.lower()
    for pattern, et, imp, sign in RULES:
        if re.search(pattern, text, flags=re.I):
            item.event_type, item.importance, item.expected_sign = et, imp, sign
            break
    return item


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_feed(xml_text: str, source: str, credibility: float, fetched_at: datetime) -> list[NewsItem]:
    root = ET.fromstring(xml_text)
    items = []
    ns_atom = "{http://www.w3.org/2005/Atom}"
    for el in list(root.iter("item")) + list(root.iter(f"{ns_atom}entry")):
        title = (el.findtext("title") or el.findtext(f"{ns_atom}title") or "").strip()
        link = (el.findtext("link") or "").strip()
        if not link:
            le = el.find(f"{ns_atom}link")
            link = le.get("href", "") if le is not None else ""
        pub = _parse_date(el.findtext("pubDate") or el.findtext(f"{ns_atom}updated") or el.findtext(f"{ns_atom}published")
                          or el.findtext("{http://purl.org/dc/elements/1.1/}date"))
        if not title or pub is None:
            continue  # an item without a publication time cannot be used safely
        items.append(classify(NewsItem(source, title, link, pub.astimezone(timezone.utc), fetched_at, credibility)))
    return items


def cluster(items: list[NewsItem], threshold: float = 0.6) -> list[NewsCluster]:
    clusters: list[NewsCluster] = []
    for it in sorted(items, key=lambda i: i.published_at):
        for c in clusters:
            if c.first.key == it.key or jaccard(c.first.title, it.title) >= threshold:
                c.items.append(it)
                break
        else:
            clusters.append(NewsCluster([it]))
    return clusters


def recent_high_impact(clusters: list[NewsCluster], as_of: datetime, window_min: int = 30) -> list[NewsItem]:
    """Items published in [as_of - window, as_of] with importance >= 2 (used for the news embargo)."""
    out = []
    for c in clusters:
        f = c.first
        if f.importance >= 2 and 0 <= (as_of - f.published_at).total_seconds() <= window_min * 60:
            out.append(f)
    return out


class NewsSource:
    def __init__(self, http: HttpClient | None = None, feeds: dict | None = None):
        self.http = http or HttpClient(limiter=RateLimiter(calls=10, period=60.0), retries=1)
        self.feeds = feeds or FEEDS
        self.errors: dict = {}
        self.last_ok: datetime | None = None

    def fetch_all(self) -> list[NewsItem]:
        out = []
        now = datetime.now(timezone.utc)
        for src, (url, cred) in self.feeds.items():
            try:
                r = self.http.get(url)
                out.extend(parse_feed(r.text, src, cred, now))
                self.errors.pop(src, None)
                self.last_ok = now
            except (HttpError, ET.ParseError, ValueError) as exc:
                self.errors[src] = str(exc)[:200]
        return out
