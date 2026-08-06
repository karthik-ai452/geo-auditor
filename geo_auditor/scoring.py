"""Transparent scoring engine.

Every score is computed from visible components. No magic numbers —
the report shows exactly how each point was earned or lost.

Pillar weights (sum to 1.0):
  Crawlability       = 15%  (if you're blocked, nothing else matters)
  Answerability      = 20%  (does content answer questions?)
  Structure          = 15%  (can machines parse the content?)
  Brand Recall       = 25%  (do AI engines actually mention you?)
  Source Presence    = 25%  (are you on the platforms AI searches?)
"""

from __future__ import annotations

from geo_auditor.models import (
    Finding,
    OverallScore,
    Pillar,
    PillarScore,
    ScoreComponent,
    Severity,
)

PILLAR_WEIGHTS = {
    Pillar.CRAWLABILITY: 0.15,
    Pillar.ANSWERABILITY: 0.20,
    Pillar.STRUCTURE: 0.15,
    Pillar.BRAND_RECALL: 0.25,
    Pillar.SOURCE_PRESENCE: 0.25,
}

# Human-readable pillar names for the report
PILLAR_LABELS = {
    Pillar.CRAWLABILITY: "AI Crawlability",
    Pillar.ANSWERABILITY: "Content Answerability",
    Pillar.STRUCTURE: "Structured Data",
    Pillar.BRAND_RECALL: "AI Brand Recall",
    Pillar.SOURCE_PRESENCE: "Source Platform Presence",
}

# Short descriptions for the report
PILLAR_DESCRIPTIONS = {
    Pillar.CRAWLABILITY: "Can AI engines reach your site?",
    Pillar.ANSWERABILITY: "Does your content answer questions AI engines extract and cite?",
    Pillar.STRUCTURE: "Can machines parse and understand your content?",
    Pillar.BRAND_RECALL: "Do AI engines actually know and mention your business?",
    Pillar.SOURCE_PRESENCE: "Does your business exist on platforms AI engines search?",
}


def compute_pillar_score(
    pillar: Pillar,
    components: list[ScoreComponent],
) -> PillarScore:
    """Compute a pillar score from its components.

    Each component has points and a max. The pillar score is the
    sum of points / sum of max * 100.
    """
    total_max = sum(c.max for c in components)
    total_points = sum(c.points for c in components)

    if total_max == 0:
        score = 0.0
    else:
        score = min(100.0, (total_points / total_max) * 100)

    return PillarScore(
        pillar=pillar,
        score=round(score, 1),
        weight=PILLAR_WEIGHTS[pillar],
        components=components,
    )


def compute_overall_score(pillar_scores: list[PillarScore]) -> OverallScore:
    """Compute the overall score as a weighted average of pillars."""
    total = sum(p.score * p.weight for p in pillar_scores)
    return OverallScore(
        total=round(total, 1),
        pillar_scores=pillar_scores,
    )


def build_action_plan(findings: list[Finding]) -> list[Finding]:
    """Build the Monday-morning action plan.

    Sorts findings by priority (impact × ease), filters out positives,
    and groups by pillar for readability.
    """
    actionable = [
        f for f in findings
        if f.severity not in (Severity.POSITIVE,)
        and f.impact > 0
        and f.fix  # must have a fix
    ]
    # Sort by priority descending
    actionable.sort(key=lambda f: f.priority, reverse=True)
    return actionable
