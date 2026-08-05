"""Pillar 2 — Content Answerability Analyzer (LLM-as-judge).

This pillar answers: **Does your content answer questions the way AI search
engines extract and cite?**

The GEO research benchmark (Aggarwal et al., 2023) showed that citation
rates in AI engines improve significantly with specific content-level
strategies:
  - Adding statistics and quantitative data (+40%)
  - Citing sources and quotations (+30%)
  - Writing direct, definitional answers (+30%)
  - Using FAQ-style formats

We use an LLM to judge content the same way an AI engine would assess it —
using an LLM to assess LLM-readiness. This is both defensible and practical.

Checks (LLM-scored, 0-100 each):
1. Direct answers — does the content directly answer questions?
2. Statistical richness — does it use data and numbers?
3. Citation quality — does it cite sources?
4. Structure clarity — is it well-organized with headings?
5. Conversational match — does it use language people actually ask in?

Plus rule-based signals that contribute to the score:
- Statistic density, definition patterns, citation patterns, FAQ schema

If the LLM is unavailable, falls back to rule-based scoring only.
"""

from __future__ import annotations

import logging
from typing import Any

from geo_auditor.models import (
    CrawlResult,
    Finding,
    PageData,
    Pillar,
    ScoreComponent,
    Severity,
)

logger = logging.getLogger(__name__)

# LLM dimension weights (must sum to 1.0)
LLM_DIMENSION_WEIGHTS = {
    "direct_answers": 0.30,
    "statistical_richness": 0.25,
    "citation_quality": 0.15,
    "structure_clarity": 0.15,
    "conversational_match": 0.15,
}


def analyze(crawl: CrawlResult) -> tuple[list[Finding], list[ScoreComponent], dict[str, Any]]:
    """Run content answerability analysis.

    Returns (findings, score_components, llm_raw_data).
    llm_raw_data is included for the report's evidence section.
    """
    findings: list[Finding] = []
    components: list[ScoreComponent] = []
    llm_data: dict[str, Any] = {}

    homepage = crawl.homepage or (crawl.pages[0] if crawl.pages else None)
    if not homepage or not homepage.ok:
        components.append(ScoreComponent(
            label="No analyzable content",
            points=0, max=100,
            detail="Could not fetch the homepage to analyze content."
        ))
        return findings, components, llm_data

    # --- Rule-based signal extraction (always runs) ---
    signal_findings, signal_components = _check_content_signals(homepage)
    findings.extend(signal_findings)

    # --- LLM-as-judge (may fail gracefully) ---
    llm_findings, llm_components, llm_data = _run_llm_judge(homepage)
    findings.extend(llm_findings)
    components.extend(llm_components)

    # If LLM didn't run, use signal-based scoring
    if not llm_components:
        components.extend(signal_components)

    return findings, components, llm_data


def _run_llm_judge(
    page: PageData,
) -> tuple[list[Finding], list[ScoreComponent], dict[str, Any]]:
    """Run the LLM judge and convert results to findings + score components."""
    findings = []
    components = []
    llm_data: dict[str, Any] = {}

    try:
        from geo_auditor import llm as llm_client

        result = llm_client.judge_content(
            url=page.url,
            title=page.title,
            content=page.text,
            stats_count=page.stats_count,
            has_definition=page.has_definition,
            has_citations=page.has_citations,
            word_count=page.word_count,
            has_faq_schema=page.has_faq_schema,
            h2_count=len(page.h2_tags),
        )
        llm_data = result

        # Convert LLM dimensions to score components
        total_weighted = 0.0
        for dim, weight in LLM_DIMENSION_WEIGHTS.items():
            dim_data = result.get(dim, {})
            score = dim_data.get("score", 50)
            reasoning = dim_data.get("reasoning", "")
            example = dim_data.get("example", "")

            # Scale to points: dim score * weight * 100 (pillar max is 100)
            points = score * weight
            total_weighted += points

            components.append(ScoreComponent(
                label=f"{dim.replace('_', ' ').title()}: {score}/100",
                points=round(points, 1),
                max=round(weight * 100, 1),
                detail=f"{reasoning}" + (f" Example: \"{example}\"" if example else "")
            ))

        # Create findings from low-scoring dimensions
        for dim, weight in LLM_DIMENSION_WEIGHTS.items():
            dim_data = result.get(dim, {})
            score = dim_data.get("score", 50)
            reasoning = dim_data.get("reasoning", "")
            example = dim_data.get("example", "")

            if score < 50:
                dim_label = dim.replace("_", " ").title()
                findings.append(Finding(
                    id=f"answerability-{dim}",
                    title=f"Content scores low on {dim_label} ({score}/100)",
                    pillar=Pillar.ANSWERABILITY,
                    severity=Severity.WARNING if score >= 30 else Severity.CRITICAL,
                    page=page.url,
                    evidence=f"LLM assessment: {reasoning}" +
                             (f" Example from your content: \"{example}\"" if example else ""),
                    should_be=f"{dim_label} should score 70+ for good AI search visibility.",
                    fix=_dimension_fix(dim, result.get("top_suggestion", "")),
                    impact=min(100, int((100 - score) * 0.8)),
                    effort=_dimension_effort(dim),
                ))
            elif score >= 75:
                dim_label = dim.replace("_", " ").title()
                findings.append(Finding(
                    id=f"answerability-{dim}-good",
                    title=f"Strong {dim_label} ({score}/100)",
                    pillar=Pillar.ANSWERABILITY,
                    severity=Severity.POSITIVE,
                    page=page.url,
                    evidence=f"LLM assessment: {reasoning}",
                    should_be="", fix="",
                    impact=0, effort=0,
                ))

        # Top suggestion as a finding
        top_suggestion = result.get("top_suggestion", "")
        if top_suggestion:
            findings.append(Finding(
                id="answerability-top-suggestion",
                title="AI's #1 recommendation for your content",
                pillar=Pillar.ANSWERABILITY,
                severity=Severity.INFO,
                page=page.url,
                evidence=f"Overall assessment: {result.get('overall_assessment', '')}",
                should_be=top_suggestion,
                fix=top_suggestion,
                impact=60,
                effort=40,
            ))

    except RuntimeError as e:
        logger.warning(f"LLM judge unavailable, falling back to rule-based: {e}")
        llm_data = {"error": str(e), "fallback": True}
    except Exception as e:
        logger.warning(f"LLM judge unexpected error: {e}")
        llm_data = {"error": str(e), "fallback": True}

    return findings, components, llm_data


def _dimension_fix(dim: str, top_suggestion: str) -> str:
    """Generate a fix recommendation for a low-scoring dimension."""
    fixes = {
        "direct_answers": (
            "Add clear, direct answer paragraphs at the top of your content. "
            "Format: '[Topic] is [definition/explanation].' — one or two sentences "
            "that directly answer the most likely question a person would ask.\n\n"
            "Example: 'Customer relationship management (CRM) software is a tool "
            "that helps businesses track interactions with customers and prospects.'"
        ),
        "statistical_richness": (
            "Add specific numbers, percentages, and data points to your content. "
            "AI engines disproportionately cite content with statistics.\n\n"
            "Instead of 'many businesses use CRM', write '73% of businesses use "
            "CRM software (Source: Salesforce, 2024)'."
        ),
        "citation_quality": (
            "Cite your sources. Use phrases like 'according to [study]', "
            "'research from [organization] shows', or link to primary sources. "
            "AI engines prefer content that itself cites evidence."
        ),
        "structure_clarity": (
            "Structure your content with clear headings (H2, H3), short paragraphs, "
            "and logical sections. Use bullet points for lists. Each section should "
            "answer one question or cover one topic."
        ),
        "conversational_match": (
            "Write in the language your audience actually uses to ask questions. "
            "Instead of 'Our platform provides enterprise-grade solutions', write "
            "'Our platform helps large teams manage projects.' Use natural, "
            "conversational phrasing."
        ),
    }
    if top_suggestion:
        return fixes.get(dim, top_suggestion) + f"\n\nAI's specific suggestion: {top_suggestion}"
    return fixes.get(dim, "Improve this aspect of your content.")


def _dimension_effort(dim: str) -> int:
    """Estimated effort for fixing each dimension."""
    return {
        "direct_answers": 20,
        "statistical_richness": 40,
        "citation_quality": 30,
        "structure_clarity": 25,
        "conversational_match": 35,
    }.get(dim, 30)


def _check_content_signals(page: PageData) -> tuple[list[Finding], list[ScoreComponent]]:
    """Rule-based content signal checks (fallback when LLM unavailable).

    These are the same signals the GEO benchmark identified as impactful.
    Used as a scoring fallback, and always surface as findings.
    """
    findings = []
    components = []

    # --- Statistic density (25 pts) ---
    # Good: 1 stat per 500 words; excellent: 1 per 200 words
    if page.word_count > 0:
        stats_per_1k = (page.stats_count / page.word_count) * 1000
    else:
        stats_per_1k = 0

    if stats_per_1k >= 5:
        stat_pts = 25
    elif stats_per_1k >= 2:
        stat_pts = 18
    elif stats_per_1k >= 1:
        stat_pts = 12
    elif stats_per_1k > 0:
        stat_pts = 6
    else:
        stat_pts = 0

    components.append(ScoreComponent(
        label=f"Statistics: {page.stats_count} found ({stats_per_1k:.1f} per 1000 words)",
        points=stat_pts, max=25,
        detail=f"{page.stats_count} statistic-like patterns detected in {page.word_count} words."
    ))

    if stats_per_1k < 2 and page.word_count > 100:
        findings.append(Finding(
            id="signal-low-stats",
            title="Low statistical content density",
            pillar=Pillar.ANSWERABILITY,
            severity=Severity.WARNING,
            page=page.url,
            evidence=f"Only {page.stats_count} statistic-like patterns found in "
                     f"{page.word_count} words ({stats_per_1k:.1f} per 1000 words). "
                     f"Research shows AI engines cite statistical content 30-40% more often.",
            should_be="At least 2-5 statistics per 1000 words.",
            fix="Add specific numbers, percentages, and data points. "
                "Cite the source for each statistic.",
            impact=55,
            effort=40,
        ))

    # --- Direct answers / definitions (25 pts) ---
    if page.has_definition:
        def_pts = 20
    else:
        def_pts = 5

    components.append(ScoreComponent(
        label=f"Direct answers: {'present' if page.has_definition else 'weak'}",
        points=def_pts, max=25,
        detail="Checked for definitional phrasing ('X is...', 'X means...')."
    ))

    if not page.has_definition:
        findings.append(Finding(
            id="signal-no-definitions",
            title="No direct definitional answers detected",
            pillar=Pillar.ANSWERABILITY,
            severity=Severity.WARNING,
            page=page.url,
            evidence="No definitional statements ('X is a...', 'X means...') found "
                     "in the first 2000 characters. AI engines extract definitional "
                     "answers to fill their responses.",
            should_be="Clear, direct definitions at the top of key pages.",
            fix="Add a 1-2 sentence direct answer at the top of your page that defines "
                "your main topic in plain language.",
            impact=50,
            effort=15,
        ))

    # --- Citations (25 pts) ---
    if page.has_citations:
        cite_pts = 22
    else:
        cite_pts = 5

    components.append(ScoreComponent(
        label=f"Citations: {'present' if page.has_citations else 'absent'}",
        points=cite_pts, max=25,
        detail="Checked for citation patterns ('according to', 'source:', 'study by')."
    ))

    if not page.has_citations:
        findings.append(Finding(
            id="signal-no-citations",
            title="No source citations detected",
            pillar=Pillar.ANSWERABILITY,
            severity=Severity.INFO,
            page=page.url,
            evidence="No citation patterns ('according to', 'source:', 'study by') found. "
                     "Content with citations is more likely to be cited by AI engines.",
            should_be="Cite sources for claims and data.",
            fix="When you make a claim or cite a statistic, link to or name the source. "
                "E.g., 'According to a 2024 Gartner study...'",
            impact=35,
            effort=30,
        ))

    # --- FAQ schema (25 pts) ---
    if page.has_faq_schema:
        faq_pts = 25
        findings.append(Finding(
            id="signal-faq-good",
            title="FAQ structured data detected",
            pillar=Pillar.ANSWERABILITY,
            severity=Severity.POSITIVE,
            page=page.url,
            evidence="FAQPage schema.org markup found. This is excellent for AI "
                     "search visibility — AI engines frequently extract FAQ content.",
            should_be="", fix="",
            impact=0, effort=0,
        ))
    else:
        faq_pts = 0
        findings.append(Finding(
            id="signal-no-faq",
            title="No FAQ structured data",
            pillar=Pillar.ANSWERABILITY,
            severity=Severity.WARNING,
            page=page.url,
            evidence="No FAQPage schema.org markup found. FAQ content in structured "
                     "format is one of the most cited content types by AI engines.",
            should_be="FAQPage schema markup for common questions.",
            fix="Add FAQ schema to key pages. Example:\n\n"
                '<script type="application/ld+json">\n'
                "{\n"
                '  "@context": "https://schema.org",\n'
                '  "@type": "FAQPage",\n'
                '  "mainEntity": [{\n'
                '    "@type": "Question",\n'
                '    "name": "What does your business do?",\n'
                '    "acceptedAnswer": {\n'
                '      "@type": "Answer",\n'
                '      "text": "Clear, concise answer here."\n'
                "    }\n"
                "  }]\n"
                "}\n"
                "</script>",
            impact=60,
            effort=25,
        ))

    components.append(ScoreComponent(
        label=f"FAQ schema: {'present' if page.has_faq_schema else 'missing'}",
        points=faq_pts, max=25,
        detail="Checked for FAQPage JSON-LD markup."
    ))

    return findings, components
