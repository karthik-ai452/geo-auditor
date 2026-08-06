"""Pillar 5 — AI Visibility & Competitive Intelligence.

This is the most important pillar. If the AI can't find you, describes you
wrong, or your competitor has better coverage — everything else is wasted effort.

Five sub-checks, each worth 20 points:

1. PLATFORM COVERAGE — Does the target brand exist on the 7 platforms
   that AI search engines actually search?

2. COMPETITIVE COVERAGE GAP — Where do competitors have presence that
   the target brand doesn't? If a competitor is on YouTube and G2 but
   you're only on G2, they win that surface.

3. AI POSITIONING ACCURACY — Does the AI describe you the way you
   describe yourself? If you sell "premium soaps" but the AI says
   "affordable soaps", it will recommend you for the wrong queries.

4. SHARE OF VOICE — Across category/comparison queries, does the target
   brand appear more or less often than competitors?

5. VECTOR SEARCH INCLUSION — Will AI vector search (semantic retrieval)
   actually surface your content? Measures embedding similarity between
   homepage content and typical user queries.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

import httpx

from geo_auditor.models import (
    CrawlResult,
    Finding,
    PageData,
    Pillar,
    ScoreComponent,
    Severity,
)

logger = logging.getLogger(__name__)

CHECK_TIMEOUT = 10.0
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

SUB_CHECK_MAX = 20.0  # Each sub-check worth 20 points

PLATFORMS = [
    ("wikipedia", "Wikipedia", "Gemini, Google AI Overviews"),
    ("github", "GitHub", "ChatGPT, Perplexity, Claude"),
    ("youtube", "YouTube", "Gemini"),
    ("reddit", "Reddit", "Gemini, Google AI Overviews"),
    ("crunchbase", "Crunchbase", "ChatGPT, Perplexity"),
    ("g2", "G2 (reviews)", "ChatGPT, Perplexity"),
    ("linkedin", "LinkedIn", "ChatGPT, Perplexity, Google AI Overviews"),
]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def analyze(
    crawl: CrawlResult,
    brand_recall_data: dict[str, Any] | None = None,
) -> tuple[list[Finding], list[ScoreComponent], dict[str, Any]]:
    """Run the full AI Visibility & Competitive Intelligence analysis.

    Args:
        crawl: Crawl results with homepage data.
        brand_recall_data: Data from Pillar 4 (brand recall), used for
            share of voice and positioning accuracy. If None, those
            sub-checks will attempt to run independently.

    Returns (findings, score_components, raw_data).
    """
    homepage = crawl.homepage or (crawl.pages[0] if crawl.pages else None)
    if not homepage:
        return _no_data_result("No homepage to analyze")

    # Infer brand name
    brand_name, domain = _infer_brand(homepage, crawl.base_url)
    if not brand_name:
        return _no_data_result("Could not determine brand name")

    # Get competitors and category from brand_recall_data if available
    br_data = brand_recall_data or {}
    competitors = br_data.get("competitors", [])
    category = br_data.get("category", "")
    brand_aliases = br_data.get("brand_aliases", [])

    raw_data: dict[str, Any] = {
        "brand_name": brand_name,
        "domain": domain,
        "competitors": competitors,
        "category": category,
    }

    findings: list[Finding] = []
    components: list[ScoreComponent] = []

    # Run all 5 sub-checks
    print("     → 1/5 Platform coverage...")
    s1_f, s1_c, s1_d = _check_platform_coverage(brand_name, domain, homepage)
    findings.extend(s1_f)
    components.extend(s1_c)
    raw_data["platform_coverage"] = s1_d

    print("     → 2/5 Competitive coverage gap...")
    s2_f, s2_c, s2_d = _check_competitive_gap(brand_name, domain, competitors, s1_d)
    findings.extend(s2_f)
    components.extend(s2_c)
    raw_data["competitive_gap"] = s2_d

    print("     → 3/5 AI positioning accuracy...")
    s3_f, s3_c, s3_d = _check_positioning_accuracy(brand_name, homepage, br_data)
    findings.extend(s3_f)
    components.extend(s3_c)
    raw_data["positioning_accuracy"] = s3_d

    print("     → 4/5 Share of voice...")
    s4_f, s4_c, s4_d = _check_share_of_voice(brand_name, competitors, br_data)
    findings.extend(s4_f)
    components.extend(s4_c)
    raw_data["share_of_voice"] = s4_d

    print("     → 5/5 Vector search inclusion...")
    s5_f, s5_c, s5_d = _check_vector_search(brand_name, homepage, category)
    findings.extend(s5_f)
    components.extend(s5_c)
    raw_data["vector_search"] = s5_d

    return findings, components, raw_data


def _no_data_result(msg: str):
    components = [ScoreComponent(label=msg, points=0, max=100, detail="")]
    return [], components, {}


# ---------------------------------------------------------------------------
# Sub-check 1: Platform Coverage (refined existing checks)
# ---------------------------------------------------------------------------


def _check_platform_coverage(
    brand: str, domain: str, homepage: PageData
) -> tuple[list[Finding], list[ScoreComponent], dict]:
    results = _run_platform_checks(brand, domain)
    found_count = sum(1 for r in results if r["found"])

    components = []
    for r in results:
        pts = SUB_CHECK_MAX / 7 if r["found"] else 0
        icon = "✓" if r["found"] else "✗"
        components.append(ScoreComponent(
            label=f"{icon} {r['display_name']}",
            points=pts,
            max=SUB_CHECK_MAX / 7,
            detail=r["evidence"] + (f" (searched by: {r['searched_by']})" if r["found"] else "")
        ))

    findings = []
    if found_count == 0:
        findings.append(Finding(
            id="no-platform-presence",
            title=f"'{brand}' not found on ANY source platform",
            pillar=Pillar.SOURCE_PRESENCE,
            severity=Severity.CRITICAL,
            page=homepage.url,
            evidence=_evidence_detail(results),
            should_be="At least 3-4 platforms.",
            fix=_platform_fix(brand, results),
            impact=90, effort=40,
        ))
    elif found_count <= 2:
        findings.append(Finding(
            id="low-platform-presence",
            title=f"'{brand}' on only {found_count}/7 platforms",
            pillar=Pillar.SOURCE_PRESENCE,
            severity=Severity.WARNING,
            page=homepage.url,
            evidence=_evidence_detail(results),
            should_be="4-5+ platforms.",
            fix=_platform_fix(brand, results),
            impact=65, effort=35,
        ))

    return findings, components, {"platform_results": results, "found_count": found_count}


# ---------------------------------------------------------------------------
# Sub-check 2: Competitive Coverage Gap
# ---------------------------------------------------------------------------


def _check_competitive_gap(
    brand: str, domain: str, competitors: list[str], target_platform_data: dict
) -> tuple[list[Finding], list[ScoreComponent], dict]:
    """Check where competitors have platform presence that target doesn't."""
    if not competitors:
        return [], [ScoreComponent(
            label="No competitors identified for coverage comparison",
            points=SUB_CHECK_MAX, max=SUB_CHECK_MAX,
            detail="Could not identify competitors. Run brand recall first."
        )], {"competitor_results": {}, "gap_count": 0}

    target_platforms = target_platform_data.get("platform_results", [])
    target_found = {r["platform"]: r["found"] for r in target_platforms}

    # Check top 2 competitors on all platforms
    comp_to_check = competitors[:3]
    comp_results: dict[str, list[dict]] = {}

    for comp in comp_to_check:
        results = _run_platform_checks(comp, "")
        comp_results[comp] = results

    # Build coverage map
    coverage_map = []
    gap_count = 0
    advantage_count = 0

    for platform_id, display, searched_by in PLATFORMS:
        target_on = target_found.get(platform_id, False)

        for comp in comp_to_check:
            comp_platforms = {r["platform"]: r["found"] for r in comp_results.get(comp, [])}
            comp_on = comp_platforms.get(platform_id, False)

            if comp_on and not target_on:
                gap_count += 1
                coverage_map.append({
                    "platform": display,
                    "platform_id": platform_id,
                    "target": False,
                    "competitor": comp,
                    "competitor_present": True,
                    "status": "gap",
                    "detail": f"{comp} is on {display} but {brand} is not — they win this surface",
                })
            elif not comp_on and target_on:
                advantage_count += 1
                coverage_map.append({
                    "platform": display,
                    "platform_id": platform_id,
                    "target": True,
                    "competitor": comp,
                    "competitor_present": False,
                    "status": "advantage",
                    "detail": f"{brand} is on {display} but {comp} is not — you win this surface",
                })

    # Score: advantage ratio — if you have more advantages than gaps, high score
    if gap_count + advantage_count > 0:
        pts = SUB_CHECK_MAX * (advantage_count / (gap_count + advantage_count))
    else:
        # No differences found — neutral
        pts = SUB_CHECK_MAX * 0.5

    components = [ScoreComponent(
        label=f"Coverage vs competitors: {gap_count} gaps, {advantage_count} advantages",
        points=pts, max=SUB_CHECK_MAX,
        detail="; ".join([m["detail"] for m in coverage_map[:5]])
    )]

    findings = []
    if gap_count > advantage_count and gap_count > 0:
        findings.append(Finding(
            id="competitive-coverage-gap",
            title=f"Competitors have platform coverage advantage ({gap_count} gaps vs {advantage_count} advantages)",
            pillar=Pillar.SOURCE_PRESENCE,
            severity=Severity.WARNING,
            page="",
            evidence="; ".join([m["detail"] for m in coverage_map if m["status"] == "gap"][:5]),
            should_be="At least match competitors on every platform they're on.",
            fix=_competitive_gap_fix(brand, coverage_map),
            impact=70, effort=40,
        ))
    elif gap_count == 0 and advantage_count > 0:
        findings.append(Finding(
            id="competitive-coverage-advantage",
            title=f"You have platform coverage advantage over competitors ({advantage_count} surfaces)",
            pillar=Pillar.SOURCE_PRESENCE,
            severity=Severity.POSITIVE,
            page="",
            evidence="; ".join([m["detail"] for m in coverage_map if m["status"] == "advantage"][:5]),
            should_be="", fix="",
            impact=0, effort=0,
        ))

    return findings, components, {
        "coverage_map": coverage_map,
        "gap_count": gap_count,
        "advantage_count": advantage_count,
        "competitor_results": comp_results,
    }


# ---------------------------------------------------------------------------
# Sub-check 3: AI Positioning Accuracy
# ---------------------------------------------------------------------------


def _check_positioning_accuracy(
    brand: str, homepage: PageData, br_data: dict
) -> tuple[list[Finding], list[ScoreComponent], dict]:
    """Does the AI describe the brand the way the brand describes itself?"""
    from geo_auditor import llm as llm_client

    self_description = homepage.text[:2000] if homepage.text else ""
    if not self_description:
        return [], [ScoreComponent(
            label="No homepage content for positioning analysis",
            points=0, max=SUB_CHECK_MAX,
            detail="Could not extract self-description."
        )], {}

    # Get AI description from brand recall queries
    ai_descriptions = []
    for qr in br_data.get("query_results", []):
        if qr.get("mention", {}).get("mentioned"):
            response = qr.get("response", "")
            if response:
                ai_descriptions.append(response)

    if not ai_descriptions:
        return [], [ScoreComponent(
            label="No AI responses to compare positioning",
            points=0, max=SUB_CHECK_MAX,
            detail="Brand was not mentioned in any AI queries — no description to compare."
        )], {}

    ai_description = " ".join(ai_descriptions)[:2000]

    try:
        result = llm_client.check_positioning_accuracy(brand, self_description, ai_description)
    except Exception as e:
        return [], [ScoreComponent(
            label="Positioning accuracy check failed",
            points=0, max=SUB_CHECK_MAX,
            detail=f"Error: {type(e).__name__}"
        )], {"error": str(e)}

    accuracy = result.get("accuracy_score", 50)
    mismatches = result.get("mismatches", [])
    summary = result.get("summary", "")

    # Build mismatch detail
    mismatch_details = []
    for m in mismatches:
        mismatch_details.append(
            f"[{m.get('severity', '?').upper()}] {m.get('category', '?')}: "
            f"You say '{m.get('self_description', '')[:60]}' vs "
            f"AI says '{m.get('ai_description', '')[:60]}'"
        )

    components = [ScoreComponent(
        label=f"AI positioning accuracy: {accuracy:.0f}/100",
        points=SUB_CHECK_MAX * (accuracy / 100), max=SUB_CHECK_MAX,
        detail=summary + ("\nMismatches: " + " | ".join(mismatch_details) if mismatch_details else "")
    )]

    findings = []
    critical_mismatches = [m for m in mismatches if m.get("severity") == "critical"]
    moderate_mismatches = [m for m in mismatches if m.get("severity") == "moderate"]

    if critical_mismatches:
        findings.append(Finding(
            id="critical-positioning-mismatch",
            title=f"Critical AI positioning mismatch for '{brand}'",
            pillar=Pillar.SOURCE_PRESENCE,
            severity=Severity.CRITICAL,
            page=homepage.url,
            evidence="The AI describes your business differently from how you position yourself: " +
                     " | ".join(mismatch_details),
            should_be="The AI should describe you using your own positioning language.",
            fix=_positioning_fix(brand, mismatches),
            impact=80, effort=50,
        ))
    elif moderate_mismatches:
        findings.append(Finding(
            id="moderate-positioning-mismatch",
            title=f"Moderate positioning mismatch for '{brand}'",
            pillar=Pillar.SOURCE_PRESENCE,
            severity=Severity.WARNING,
            page=homepage.url,
            evidence=" | ".join(mismatch_details),
            should_be="AI description should match your self-positioning.",
            fix=_positioning_fix(brand, mismatches),
            impact=50, effort=40,
        ))
    elif accuracy >= 80:
        findings.append(Finding(
            id="accurate-positioning",
            title=f"AI accurately describes '{brand}'",
            pillar=Pillar.SOURCE_PRESENCE,
            severity=Severity.POSITIVE,
            page=homepage.url,
            evidence=summary,
            should_be="", fix="",
            impact=0, effort=0,
        ))

    return findings, components, result


# ---------------------------------------------------------------------------
# Sub-check 4: Share of Voice
# ---------------------------------------------------------------------------


def _check_share_of_voice(
    brand: str, competitors: list[str], br_data: dict
) -> tuple[list[Finding], list[ScoreComponent], dict]:
    """Across AI queries, who appears more — target or competitors?"""
    from geo_auditor import llm as llm_client

    query_results = br_data.get("query_results", [])
    if not query_results:
        return [], [ScoreComponent(
            label="No AI query results for share of voice analysis",
            points=0, max=SUB_CHECK_MAX,
            detail="Brand recall queries not available."
        )], {}

    # Analyze each query response for all brands
    all_analyses = []
    target_mentions = 0
    competitor_mentions: dict[str, int] = {c: 0 for c in competitors}

    for qr in query_results:
        response = qr.get("response", "")
        if not response:
            continue

        analysis = llm_client.analyze_competitor_mentions(response, brand, competitors)
        all_analyses.append({
            "query": qr.get("query", "")[:80],
            "analysis": analysis,
        })

        for b in analysis.get("brands", []):
            if b.get("mentioned"):
                if b["name"].lower() == brand.lower():
                    target_mentions += 1
                elif b["name"] in competitor_mentions:
                    competitor_mentions[b["name"]] += 1

    total_mentions = target_mentions + sum(competitor_mentions.values())
    if total_mentions == 0:
        return [], [ScoreComponent(
            label="No brand mentions detected across queries",
            points=0, max=SUB_CHECK_MAX,
            detail="Neither target nor competitors were mentioned."
        )], {"target_mentions": 0, "competitor_mentions": competitor_mentions}

    target_sov = target_mentions / total_mentions

    # Score: if you have >50% share of voice, full points. Scales down.
    pts = SUB_CHECK_MAX * min(1.0, target_sov * 2)  # 50% SOV = full points

    # Build detail
    detail_parts = [f"Target '{brand}': {target_mentions} mentions ({target_sov:.0%} share of voice)"]
    for comp, count in sorted(competitor_mentions.items(), key=lambda x: x[1], reverse=True):
        pct = count / total_mentions if total_mentions else 0
        detail_parts.append(f"Competitor '{comp}': {count} mentions ({pct:.0%})")

    components = [ScoreComponent(
        label=f"Share of voice: {target_sov:.0%} ({target_mentions} of {total_mentions} total mentions)",
        points=pts, max=SUB_CHECK_MAX,
        detail=" | ".join(detail_parts)
    )]

    findings = []
    if target_sov < 0.25 and total_mentions > 0:
        findings.append(Finding(
            id="low-share-of-voice",
            title=f"'{brand}' has low share of voice ({target_sov:.0%}) vs competitors",
            pillar=Pillar.SOURCE_PRESENCE,
            severity=Severity.WARNING,
            page="",
            evidence=" | ".join(detail_parts),
            should_be="You should appear in at least 40-50% of brand mentions in your category.",
            fix=(
                f"Increase content that AI engines cite for category queries. "
                f"Get listed on more review sites and directories. "
                f"Build topical authority through consistent content publishing. "
                f"Competitors currently dominate: " +
                ", ".join([f"{c} ({n} mentions)" for c, n in
                          sorted(competitor_mentions.items(), key=lambda x: x[1], reverse=True) if n > 0])
            ),
            impact=65, effort=50,
        ))
    elif target_sov >= 0.50:
        findings.append(Finding(
            id="high-share-of-voice",
            title=f"'{brand}' dominates share of voice ({target_sov:.0%})",
            pillar=Pillar.SOURCE_PRESENCE,
            severity=Severity.POSITIVE,
            page="",
            evidence=" | ".join(detail_parts),
            should_be="", fix="",
            impact=0, effort=0,
        ))

    return findings, components, {
        "target_mentions": target_mentions,
        "competitor_mentions": competitor_mentions,
        "target_sov": target_sov,
        "per_query_analysis": all_analyses,
    }


# ---------------------------------------------------------------------------
# Sub-check 5: Vector Search Inclusion
# ---------------------------------------------------------------------------


def _check_vector_search(
    brand: str, homepage: PageData, category: str
) -> tuple[list[Finding], list[ScoreComponent], dict]:
    """Will AI vector search (semantic retrieval) surface your content?"""
    from geo_auditor import llm as llm_client

    content = homepage.text[:4000] if homepage.text else ""
    if not content:
        return [], [ScoreComponent(
            label="No content for vector search analysis",
            points=0, max=SUB_CHECK_MAX,
            detail="Could not extract homepage content."
        )], {}

    if not category:
        category = "software"  # generic fallback

    try:
        result = llm_client.compute_vector_search_inclusion(content, category, brand)
    except Exception as e:
        return [], [ScoreComponent(
            label="Vector search inclusion check failed",
            points=0, max=SUB_CHECK_MAX,
            detail=f"Error: {type(e).__name__}"
        )], {"error": str(e)}

    sim_score = result.get("similarity_score", 0)
    verdict = result.get("will_be_retrieved", "unknown")

    components = [ScoreComponent(
        label=f"Vector search inclusion: {sim_score:.1%} similarity",
        points=SUB_CHECK_MAX * min(1.0, sim_score), max=SUB_CHECK_MAX,
        detail=result.get("detail", str(verdict))
    )]

    findings = []
    if "very low" in verdict:
        findings.append(Finding(
            id="vector-search-excluded",
            title=f"'{brand}' content has very low vector similarity to category queries",
            pillar=Pillar.SOURCE_PRESENCE,
            severity=Severity.CRITICAL,
            page=homepage.url,
            evidence=result.get("detail", ""),
            should_be="Content should semantically match what users search for.",
            fix=(
                "Rewrite homepage content to include natural language matching how "
                f"users search for {category}. Use the exact phrases people type when "
                "asking AI assistants. Add FAQ-style content with question-format headings. "
                "Ensure key category terms appear prominently in headings, not just body text. "
                "The AI's vector search uses semantic similarity — your content must "
                "conceptually overlap with user queries."
            ),
            impact=75, effort=45,
        ))
    elif "low" in verdict:
        findings.append(Finding(
            id="vector-search-weak",
            title=f"'{brand}' has weak vector search presence",
            pillar=Pillar.SOURCE_PRESENCE,
            severity=Severity.WARNING,
            page=homepage.url,
            evidence=result.get("detail", ""),
            should_be="Higher semantic similarity to category queries.",
            fix=(
                f"Add content addressing '{category}' in natural, query-like language. "
                "Include FAQ sections, comparison pages, and topic-cluster content."
            ),
            impact=50, effort=40,
        ))

    return findings, components, result


# ===========================================================================
# Platform check functions (sync — used by thread pool)
# ===========================================================================


def _run_platform_checks(brand: str, domain: str) -> list[dict[str, Any]]:
    """Run all 7 platform checks in parallel."""
    results: list[dict[str, Any]] = []
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=CHECK_TIMEOUT,
    ) as client:
        with ThreadPoolExecutor(max_workers=7) as pool:
            futures = {}
            for pid, display, searched_by in PLATFORMS:
                check_fn = PLATFORM_CHECKS_SYNC[pid]
                future = pool.submit(
                    _safe_check_sync, check_fn, client, brand, domain, pid, display, searched_by
                )
                futures[future] = display
            for future in as_completed(futures):
                results.append(future.result())
    return results


def _safe_check_sync(check_fn, client, brand, domain, pid, display, searched_by) -> dict[str, Any]:
    try:
        found, evidence = check_fn(client, brand, domain)
        return {"platform": pid, "display_name": display, "searched_by": searched_by,
                "found": found, "evidence": evidence}
    except Exception as e:
        return {"platform": pid, "display_name": display, "searched_by": searched_by,
                "found": False, "evidence": f"Check failed: {type(e).__name__}"}


def _check_wikipedia_sync(client, brand, domain) -> tuple[bool, str]:
    try:
        resp = client.get("https://en.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": brand, "srlimit": 3, "format": "json"})
        if resp.status_code == 200:
            results = resp.json().get("query", {}).get("search", [])
            for r in results:
                if brand.lower() in r.get("title", "").lower():
                    return True, f"Wikipedia page: '{r.get('title')}'"
            if results:
                return False, f"Related: {', '.join(r.get('title','') for r in results[:3])}"
        return False, "No Wikipedia page found"
    except Exception as e:
        return False, f"Check failed: {type(e).__name__}"


def _check_github_sync(client, brand, domain) -> tuple[bool, str]:
    slug = _slug(brand)
    try:
        resp = client.get(f"https://github.com/{slug}")
        if resp.status_code == 200 and "Page not found" not in resp.text[:2000]:
            return True, f"GitHub org: github.com/{slug}"
        return False, f"No GitHub org (HTTP {resp.status_code})"
    except Exception as e:
        return False, f"Check failed: {type(e).__name__}"


def _check_youtube_sync(client, brand, domain) -> tuple[bool, str]:
    slug = _slug(brand)
    try:
        resp = client.get(f"https://www.youtube.com/@{slug}")
        if resp.status_code == 200:
            text = resp.text[:10000]
            if brand.lower() in text.lower() and ('"channelId"' in text or '@' + slug in text):
                return True, f"YouTube channel: youtube.com/@{slug}"
        return False, f"No YouTube channel for '{brand}'"
    except Exception as e:
        return False, f"Check failed: {type(e).__name__}"


def _check_reddit_sync(client, brand, domain) -> tuple[bool, str]:
    try:
        resp = client.get("https://www.reddit.com/search.json",
            params={"q": brand, "sort": "relevance", "limit": 5, "type": "link"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        if resp.status_code == 200:
            children = resp.json().get("data", {}).get("children", [])
            relevant = [c for c in children if brand.lower() in c.get("data", {}).get("title", "").lower()]
            if relevant:
                sub = relevant[0].get("data", {}).get("subreddit", "")
                return True, f"Reddit: r/{sub}"
        elif resp.status_code == 403:
            return False, "Reddit API blocked (403)"
        return False, "No Reddit discussions found"
    except Exception as e:
        return False, f"Check failed: {type(e).__name__}"


def _check_crunchbase_sync(client, brand, domain) -> tuple[bool, str]:
    slug = _slug(brand)
    try:
        resp = client.get(f"https://www.crunchbase.com/organization/{slug}")
        if resp.status_code == 200 and "Page Not Found" not in resp.text[:2000]:
            return True, f"Crunchbase: crunchbase.com/organization/{slug}"
        return False, f"No Crunchbase profile (HTTP {resp.status_code})"
    except Exception as e:
        return False, f"Check failed: {type(e).__name__}"


def _check_g2_sync(client, brand, domain) -> tuple[bool, str]:
    slug = _slug(brand).replace("-", "_")
    try:
        resp = client.get(f"https://www.g2.com/products/{slug}/reviews")
        if resp.status_code == 200 and "Page Not Found" not in resp.text[:2000]:
            return True, f"G2: g2.com/products/{slug}"
        elif resp.status_code == 403:
            return False, "G2 blocked (403)"
        return False, f"No G2 page"
    except Exception as e:
        return False, f"Check failed: {type(e).__name__}"


def _check_linkedin_sync(client, brand, domain) -> tuple[bool, str]:
    slug = _slug(brand)
    try:
        resp = client.get(f"https://www.linkedin.com/company/{slug}")
        if resp.status_code == 200:
            text = resp.text[:5000]
            if f"content=\"{brand}" in text or f"company/{slug}" in text:
                return True, f"LinkedIn: linkedin.com/company/{slug}"
        return False, f"No LinkedIn company page confirmed"
    except Exception as e:
        return False, f"Check failed: {type(e).__name__}"


PLATFORM_CHECKS_SYNC = {
    "wikipedia": _check_wikipedia_sync,
    "github": _check_github_sync,
    "youtube": _check_youtube_sync,
    "reddit": _check_reddit_sync,
    "crunchbase": _check_crunchbase_sync,
    "g2": _check_g2_sync,
    "linkedin": _check_linkedin_sync,
}


# ===========================================================================
# Fix generators
# ===========================================================================


def _platform_fix(brand: str, results: list[dict]) -> str:
    missing = [r["display_name"] for r in results if not r["found"]]
    if not missing:
        return "All platforms covered — excellent."
    fix_map = {
        "Wikipedia": f"Create a Wikipedia article for {brand} if it meets notability criteria.",
        "GitHub": f"Create a GitHub organization at github.com/{_slug(brand)}.",
        "YouTube": f"Create a YouTube channel at youtube.com/@{_slug(brand)}.",
        "Reddit": "Encourage community discussion on Reddit in relevant subreddits.",
        "Crunchbase": f"Create a Crunchbase profile at crunchbase.com/organization/{_slug(brand)}.",
        "G2 (reviews)": f"Claim your G2 page at g2.com/products/{_slug(brand).replace('-','_')} and get reviews.",
        "LinkedIn": f"Ensure LinkedIn company page at linkedin.com/company/{_slug(brand)} is complete.",
    }
    parts = [f"Missing from: {', '.join(missing)}.\n"]
    for name in missing:
        if name in fix_map:
            parts.append(f"• {fix_map[name]}\n")
    return "".join(parts)


def _competitive_gap_fix(brand: str, coverage_map: list[dict]) -> str:
    gaps = [m for m in coverage_map if m["status"] == "gap"]
    if not gaps:
        return "No competitive gaps — you match or exceed competitors on all platforms."
    parts = [f"'{brand}' is missing from platforms where competitors are present:\n"]
    for g in gaps[:5]:
        parts.append(f"• {g['detail']}\n")
    parts.append("\nGet on these platforms immediately — competitors are winning AI visibility there.")
    return "".join(parts)


def _positioning_fix(brand: str, mismatches: list[dict]) -> str:
    parts = ["The AI describes your business differently than you intend. Fix this:\n"]
    for m in mismatches[:5]:
        parts.append(
            f"• [{m.get('category', '?')}] You say: '{m.get('self_description', '')[:80]}'. "
            f"AI says: '{m.get('ai_description', '')[:80]}'. "
            f"Action: Use your intended positioning language consistently across your site, "
            f"meta tags, and external profiles so AI engines learn the correct description.\n"
        )
    return "".join(parts)


# ===========================================================================
# Helpers
# ===========================================================================


def _slug(text: str) -> str:
    text = re.sub(r'\b(inc|llc|corp|ltd|co|company|technologies|software)\b\.?$', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'[^a-z0-9]+', '-', text.lower())
    return text.strip('-')


def _infer_brand(page: PageData, base_url: str) -> tuple[str, str]:
    domain = urlparse(base_url).netloc.replace("www.", "")
    domain_core = domain.split(".")[0]
    brand_name = domain_core.capitalize()
    for block in page.json_ld_blocks:
        if isinstance(block.get("@type"), str) and block["@type"] in ("Organization", "Corporation", "LocalBusiness"):
            name = block.get("name", "")
            if name:
                brand_name = name
                break
        elif isinstance(block.get("@type"), list):
            for t in block["@type"]:
                if t in ("Organization", "Corporation", "LocalBusiness"):
                    name = block.get("name", "")
                    if name:
                        brand_name = name
                        break
    if brand_name == domain_core.capitalize() and page.title:
        title_clean = page.title.split("|")[0].split("—")[0].split("–")[0].split("-")[0].strip()
        if title_clean and len(title_clean) < 30 and not title_clean.lower().startswith("welcome"):
            brand_name = title_clean
    return brand_name, domain


def _evidence_detail(results: list[dict]) -> str:
    parts = []
    for r in results:
        status = "✓ FOUND" if r["found"] else "✗ MISSING"
        parts.append(f"{r['display_name']}: {status} — {r['evidence']}")
    return " | ".join(parts)
