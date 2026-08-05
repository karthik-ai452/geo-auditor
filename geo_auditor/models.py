"""Core data models for the GEO Auditor.

Every piece of data flows through these dataclasses:
  URL → Crawler → PageData → Analyzers → Findings → Scores → AuditResult → Report
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    """How bad a finding is — drives color and ordering in the report."""

    CRITICAL = "critical"  # red — blocks AI visibility entirely
    WARNING = "warning"  # amber — hurts visibility, fixable
    INFO = "info"  # blue — minor or contextual
    POSITIVE = "positive"  # green — already good


class Pillar(str, Enum):
    """The four audit pillars. Used as scoring categories."""

    CRAWLABILITY = "crawlability"  # Pillar 1 (20%)
    ANSWERABILITY = "answerability"  # Pillar 2 (25%)
    STRUCTURE = "structure"  # Pillar 3 (20%)
    BRAND_RECALL = "brand_recall"  # Pillar 4 (35%)


# ---------------------------------------------------------------------------
# Crawl data
# ---------------------------------------------------------------------------


@dataclass
class PageData:
    """Everything the crawler extracts from a single page."""

    url: str
    status_code: int | None = None
    load_time_ms: float | None = None
    html: str | None = None  # raw HTML for deep parsing
    text: str = ""  # extracted visible text
    title: str = ""
    meta_description: str = ""
    meta_robots: str = ""
    canonical: str = ""
    og_title: str = ""
    og_description: str = ""
    json_ld_blocks: list[dict[str, Any]] = field(default_factory=list)
    h1_tags: list[str] = field(default_factory=list)
    h2_tags: list[str] = field(default_factory=list)
    word_count: int = 0
    has_faq_schema: bool = False
    # content signals (filled by answerability analyzer)
    stats_count: int = 0
    has_definition: bool = False
    has_citations: bool = False
    paragraph_count: int = 0
    error: str | None = None  # if fetch failed

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300 and self.error is None


@dataclass
class RobotsData:
    """Parsed robots.txt result."""

    raw: str = ""
    fetch_ok: bool = False
    status_code: int | None = None
    # per-bot: True = allowed, False = blocked, None = not mentioned (allowed by default)
    bot_rules: dict[str, bool | None] = field(default_factory=dict)
    sitemap_urls: list[str] = field(default_factory=list)


@dataclass
class SitemapData:
    """Parsed sitemap.xml result."""

    fetch_ok: bool = False
    status_code: int | None = None
    url_count: int = 0
    urls: list[str] = field(default_factory=list)
    is_index: bool = False  # points to other sitemaps
    child_sitemap_count: int = 0


@dataclass
class CrawlResult:
    """Aggregated crawl data for a whole site."""

    base_url: str = ""
    robots: RobotsData = field(default_factory=RobotsData)
    sitemap: SitemapData = field(default_factory=SitemapData)
    pages: list[PageData] = field(default_factory=list)
    homepage: PageData | None = None

    @property
    def page_count(self) -> int:
        return len(self.pages)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A single audit finding — the atomic unit of the report.

    Every finding carries:
      - evidence: what was found (real data, not vague claims)
      - fix: a copy-pasteable fix when possible
      - impact/effort: for the Monday-morning action plan
    """

    id: str
    title: str
    pillar: Pillar
    severity: Severity
    page: str = ""  # exact URL where the issue was found
    evidence: str = ""  # what was found (concrete)
    should_be: str = ""  # what it should be
    fix: str = ""  # copy-pasteable fix
    impact: int = 50  # 0-100, how much this affects AI visibility
    effort: int = 50  # 0-100, how hard to fix (100 = very hard)

    @property
    def priority(self) -> float:
        """Priority score for action plan ordering. Higher = do first."""
        return self.impact * (1 - self.effort / 100)

    @property
    def severity_rank(self) -> int:
        """Sort rank by severity (critical first)."""
        return {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2, Severity.POSITIVE: 3}[
            self.severity
        ]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class ScoreComponent:
    """A single line in the score breakdown — shows the math.

    e.g. {label: "GPTBot allowed", points: 20, max: 20, detail: "GPTBot is not blocked in robots.txt"}
    """

    label: str
    points: float
    max: float
    detail: str = ""

    @property
    def pct(self) -> float:
        return (self.points / self.max * 100) if self.max > 0 else 0.0


@dataclass
class PillarScore:
    """Score for one pillar, with full breakdown."""

    pillar: Pillar
    score: float  # 0-100
    weight: float  # e.g. 0.25
    max: float = 100.0
    components: list[ScoreComponent] = field(default_factory=list)

    @property
    def pct(self) -> float:
        return self.score


@dataclass
class OverallScore:
    """The top-level score with full transparency."""

    total: float  # 0-100
    pillar_scores: list[PillarScore] = field(default_factory=list)

    @property
    def grade(self) -> str:
        if self.total >= 80:
            return "Strong"
        if self.total >= 60:
            return "Moderate"
        if self.total >= 40:
            return "Weak"
        return "Critical"

    @property
    def verdict(self) -> str:
        if self.total >= 80:
            return "Your site is well-optimized for AI search engines. Focus on the remaining details."
        if self.total >= 60:
            return "Your site has a foundation but key gaps are holding back AI visibility."
        if self.total >= 40:
            return "Your site is likely invisible or poorly represented in most AI search answers."
        return "Your site is almost certainly invisible in AI search. Start with the critical fixes."


# ---------------------------------------------------------------------------
# Final result
# ---------------------------------------------------------------------------


@dataclass
class AuditResult:
    """The complete audit output — everything the report needs."""

    url: str
    domain: str
    audited_at: str  # ISO timestamp
    score: OverallScore
    findings: list[Finding]
    crawl: CrawlResult
    action_plan: list[Finding] = field(default_factory=list)  # findings sorted by priority

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON export."""
        return {
            "url": self.url,
            "domain": self.domain,
            "audited_at": self.audited_at,
            "score": {
                "total": self.score.total,
                "grade": self.score.grade,
                "verdict": self.score.verdict,
                "pillars": [
                    {
                        "pillar": ps.pillar.value,
                        "score": ps.score,
                        "weight": ps.weight,
                        "components": [
                            {
                                "label": c.label,
                                "points": c.points,
                                "max": c.max,
                                "detail": c.detail,
                            }
                            for c in ps.components
                        ],
                    }
                    for ps in self.score.pillar_scores
                ],
            },
            "findings": [
                {
                    "id": f.id,
                    "title": f.title,
                    "pillar": f.pillar.value,
                    "severity": f.severity.value,
                    "page": f.page,
                    "evidence": f.evidence,
                    "should_be": f.should_be,
                    "fix": f.fix,
                    "impact": f.impact,
                    "effort": f.effort,
                    "priority": round(f.priority, 1),
                }
                for f in self.findings
            ],
            "action_plan": [
                {
                    "id": f.id,
                    "title": f.title,
                    "severity": f.severity.value,
                    "impact": f.impact,
                    "effort": f.effort,
                    "priority": round(f.priority, 1),
                    "fix": f.fix,
                }
                for f in self.action_plan
            ],
        }
