"""Pillar 1 — AI Crawlability Analyzer.

This pillar answers: **Can AI search engines even reach and read your site?**

If a site blocks GPTBot, ClaudeBot, or PerplexityBot in robots.txt, it is
literally invisible to those engines — no matter how good the content is.
This is the #1 silent killer of AI visibility, and most businesses don't
even know they're doing it (often an overzealous "block all bots" plugin).

Checks:
1. robots.txt — per-bot analysis for AI crawlers
2. sitemap.xml — presence, validity, URL count
3. meta robots — per-page noindex directives
4. HTTP reachability + load time
"""

from __future__ import annotations

from geo_auditor.crawler import AI_BOTS
from geo_auditor.models import (
    CrawlResult,
    Finding,
    PageData,
    Pillar,
    RobotsData,
    ScoreComponent,
    Severity,
)
from geo_auditor.analyzers.base import analyze_robots_fix

# How many points each bot is worth (out of 60 for the bots section)
BOT_WEIGHT = 60 / len(AI_BOTS)


def analyze(crawl: CrawlResult) -> tuple[list[Finding], list[ScoreComponent]]:
    """Run all crawlability checks. Returns findings + score components."""
    findings: list[Finding] = []
    components: list[ScoreComponent] = []

    # --- Check 1: robots.txt per-bot analysis (60 pts) ---
    bot_findings, bot_components = _check_robots_bots(crawl.robots)
    findings.extend(bot_findings)
    components.extend(bot_components)

    # --- Check 2: robots.txt fetch status (10 pts) ---
    fetch_findings, fetch_components = _check_robots_fetch(crawl.robots)
    findings.extend(fetch_findings)
    components.extend(fetch_components)

    # --- Check 3: sitemap.xml (15 pts) ---
    sitemap_findings, sitemap_components = _check_sitemap(crawl.sitemap)
    findings.extend(sitemap_findings)
    components.extend(sitemap_components)

    # --- Check 4: meta robots / noindex (10 pts) ---
    meta_findings, meta_components = _check_meta_robots(crawl.pages)
    findings.extend(meta_findings)
    components.extend(meta_components)

    # --- Check 5: HTTP reachability + load time (5 pts) ---
    perf_findings, perf_components = _check_performance(crawl.pages)
    findings.extend(perf_findings)
    components.extend(perf_components)

    return findings, components


def _check_robots_bots(robots: RobotsData) -> tuple[list[Finding], list[ScoreComponent]]:
    """Check each AI bot against robots.txt."""
    findings = []
    components = []

    if not robots.fetch_ok:
        # handled in _check_robots_fetch
        for bot in AI_BOTS:
            components.append(ScoreComponent(
                label=f"{bot}: robots.txt not found",
                points=0, max=BOT_WEIGHT,
                detail="Cannot determine — robots.txt was not found or returned an error."
            ))
        return findings, components

    blocked_bots = []
    allowed_bots = []

    for bot in AI_BOTS:
        status = robots.bot_rules.get(bot)
        if status is False:
            # Explicitly blocked
            blocked_bots.append(bot)
            components.append(ScoreComponent(
                label=f"{bot}: BLOCKED",
                points=0, max=BOT_WEIGHT,
                detail=f"{bot} is explicitly blocked in robots.txt. "
                       f"Content on this site will not be crawled or cited by this engine."
            ))
            findings.append(Finding(
                id=f"robots-blocked-{bot.lower()}",
                title=f"{bot} is blocked in robots.txt",
                pillar=Pillar.CRAWLABILITY,
                severity=Severity.CRITICAL,
                page="/robots.txt",
                evidence=f"Your robots.txt contains a rule that blocks {bot}. "
                         f"This means the AI engine cannot crawl your site, "
                         f"so your content will never appear in its answers.",
                should_be=f"{bot} should be allowed to crawl your site.",
                fix=analyze_robots_fix(bot),
                impact=95,
                effort=5,
            ))
        elif status is None:
            # Not mentioned → allowed by default (good)
            allowed_bots.append(bot)
            components.append(ScoreComponent(
                label=f"{bot}: allowed (not explicitly mentioned)",
                points=BOT_WEIGHT, max=BOT_WEIGHT,
                detail=f"{bot} is not mentioned in robots.txt, so it is allowed by default."
            ))
        else:
            # Explicitly allowed
            allowed_bots.append(bot)
            components.append(ScoreComponent(
                label=f"{bot}: allowed",
                points=BOT_WEIGHT, max=BOT_WEIGHT,
                detail=f"{bot} is allowed in robots.txt."
            ))

    if blocked_bots:
        findings.append(Finding(
            id="robots-blocked-summary",
            title=f"{len(blocked_bots)} AI crawler(s) blocked in robots.txt",
            pillar=Pillar.CRAWLABILITY,
            severity=Severity.CRITICAL,
            page="/robots.txt",
            evidence=f"Blocked bots: {', '.join(blocked_bots)}. "
                     f"These AI engines cannot access your site at all.",
            should_be="All major AI crawlers should be allowed.",
            fix=f"To unblock, remove the following from your robots.txt:\n\n"
                f"{chr(10).join(f'User-agent: {b}\\nDisallow:' for b in blocked_bots)}",
            impact=95,
            effort=5,
        ))
    elif allowed_bots:
        findings.append(Finding(
            id="robots-allowed-positive",
            title="All checked AI crawlers are allowed in robots.txt",
            pillar=Pillar.CRAWLABILITY,
            severity=Severity.POSITIVE,
            page="/robots.txt",
            evidence=f"All {len(allowed_bots)} checked AI crawlers "
                     f"({', '.join(allowed_bots)}) can access your site.",
            should_be="",
            fix="",
            impact=0,
            effort=0,
        ))

    return findings, components


def _check_robots_fetch(robots: RobotsData) -> tuple[list[Finding], list[ScoreComponent]]:
    """Check if robots.txt exists and is reachable."""
    findings = []
    if robots.fetch_ok and robots.status_code == 200:
        components = [ScoreComponent(
            label="robots.txt exists and is reachable",
            points=10, max=10,
            detail=f"robots.txt returned HTTP {robots.status_code}."
        )]
    elif robots.status_code and robots.status_code != 200:
        components = [ScoreComponent(
            label=f"robots.txt returned HTTP {robots.status_code}",
            points=3, max=10,
            detail=f"robots.txt returned HTTP {robots.status_code} instead of 200. "
                   "This may mean AI bots have no crawl directives, which is "
                   "usually fine (they default to allowed) but means you can't "
                   "control access."
        )]
        findings.append(Finding(
            id="robots-status-error",
            title=f"robots.txt returned HTTP {robots.status_code}",
            pillar=Pillar.CRAWLABILITY,
            severity=Severity.WARNING,
            page="/robots.txt",
            evidence=f"robots.txt returned HTTP {robots.status_code}.",
            should_be="robots.txt should return HTTP 200 with valid directives.",
            fix="Ensure /robots.txt is served correctly. If you don't have one, "
                "create a minimal robots.txt that allows AI bots (see the fix below).",
            impact=30,
            effort=10,
        ))
    else:
        components = [ScoreComponent(
            label="robots.txt not found",
            points=3, max=10,
            detail="robots.txt could not be fetched. Without it, bots default to "
                   "allowed, but you have no control over crawl directives."
        )]
        findings.append(Finding(
            id="robots-missing",
            title="robots.txt not found",
            pillar=Pillar.CRAWLABILITY,
            severity=Severity.WARNING,
            page="/robots.txt",
            evidence="No robots.txt was found at /robots.txt.",
            should_be="A robots.txt file should exist at the site root.",
            fix="Create a /robots.txt file. Minimal version that allows all AI bots:\n\n"
                "User-agent: *\nAllow: /\n\n"
                "Sitemap: https://yoursite.com/sitemap.xml",
            impact=30,
            effort=5,
        ))

    return findings, components


def _check_sitemap(sitemap: "SitemapData") -> tuple[list[Finding], list[ScoreComponent]]:
    """Check sitemap.xml presence and quality."""
    from geo_auditor.models import SitemapData

    findings = []

    if not sitemap.fetch_ok or sitemap.status_code is None or sitemap.status_code != 200:
        components = [ScoreComponent(
            label="sitemap.xml missing or unreachable",
            points=0, max=15,
            detail="No sitemap.xml found. AI engines and traditional search engines "
                   "use sitemaps to discover pages. Without one, deep content may "
                   "go uncrawled."
        )]
        findings.append(Finding(
            id="sitemap-missing",
            title="sitemap.xml is missing or unreachable",
            pillar=Pillar.CRAWLABILITY,
            severity=Severity.WARNING,
            page="/sitemap.xml",
            evidence="No sitemap.xml was found at /sitemap.xml.",
            should_be="A valid sitemap.xml listing your key pages.",
            fix="Create a sitemap.xml at the site root. If you use a CMS (WordPress, "
                "Shopify, Webflow), there's usually a plugin or built-in feature to "
                "generate one. Reference it in robots.txt:\n\n"
                "Sitemap: https://yoursite.com/sitemap.xml",
            impact=50,
            effort=20,
        ))
        return findings, components

    # Sitemap exists — evaluate quality
    if sitemap.url_count == 0 and not sitemap.is_index:
        components = [ScoreComponent(
            label="sitemap.xml exists but contains 0 URLs",
            points=5, max=15,
            detail="sitemap.xml exists but is empty or malformed."
        )]
        findings.append(Finding(
            id="sitemap-empty",
            title="sitemap.xml exists but contains no URLs",
            pillar=Pillar.CRAWLABILITY,
            severity=Severity.WARNING,
            page="/sitemap.xml",
            evidence="sitemap.xml was found but contains 0 <url> entries.",
            should_be="A sitemap with valid <url> entries for your key pages.",
            fix="Regenerate your sitemap to include your pages. Most CMS platforms "
                "and SEO plugins (Yoast, RankMath) can do this automatically.",
            impact=40,
            effort=20,
        ))
    elif sitemap.is_index:
        points = min(15, 5 + sitemap.child_sitemap_count)
        components = [ScoreComponent(
            label=f"sitemap.xml is a valid index with {sitemap.child_sitemap_count} child sitemaps",
            points=points, max=15,
            detail=f"Sitemap index pointing to {sitemap.child_sitemap_count} child sitemaps, "
                   f"containing {sitemap.url_count} URLs total."
        )]
        findings.append(_sitemap_index_finding(sitemap))
    else:
        points = min(15, max(8, sitemap.url_count / 2))
        components = [ScoreComponent(
            label=f"sitemap.xml with {sitemap.url_count} URL(s)",
            points=points, max=15,
            detail=f"Valid sitemap.xml containing {sitemap.url_count} URLs."
        )]
        findings.append(Finding(
            id="sitemap-valid",
            title=f"sitemap.xml is valid with {sitemap.url_count} URL(s)",
            pillar=Pillar.CRAWLABILITY,
            severity=Severity.POSITIVE,
            page="/sitemap.xml",
            evidence=f"sitemap.xml exists and contains {sitemap.url_count} URL entries.",
            should_be="",
            fix="",
            impact=0,
            effort=0,
        ))

    return findings, components


def _sitemap_index_finding(sitemap) -> Finding:
    """Helper to create a sitemap index finding (avoiding naming collision)."""
    return Finding(
        id="sitemap-index-valid",
        title=f"sitemap.xml is a valid index ({sitemap.child_sitemap_count} child sitemaps)",
        pillar=Pillar.CRAWLABILITY,
        severity=Severity.POSITIVE,
        page="/sitemap.xml",
        evidence=f"Sitemap index with {sitemap.child_sitemap_count} child sitemaps, "
                 f"{sitemap.url_count} URLs total.",
        should_be="",
        fix="",
        impact=0,
        effort=0,
    )


def _check_meta_robots(pages: list[PageData]) -> tuple[list[Finding], list[ScoreComponent]]:
    """Check for noindex directives on key pages."""
    findings = []
    noindex_pages = []
    for page in pages:
        if page.error or not page.ok:
            continue
        robots_val = (page.meta_robots or "").lower()
        if "noindex" in robots_val:
            noindex_pages.append(page.url)

    if noindex_pages:
        components = [ScoreComponent(
            label=f"{len(noindex_pages)} page(s) with noindex",
            points=0, max=10,
            detail=f"Pages with noindex: {', '.join(noindex_pages[:3])}"
        )]
        findings.append(Finding(
            id="meta-noindex",
            title=f"{len(noindex_pages)} page(s) blocked from indexing (noindex)",
            pillar=Pillar.CRAWLABILITY,
            severity=Severity.CRITICAL,
            page=noindex_pages[0],
            evidence=f"The following pages have <meta name='robots' content='noindex'>: "
                     f"{', '.join(noindex_pages[:3])}. These pages will not be indexed "
                     f"by any search engine, AI or traditional.",
            should_be="Remove noindex from pages you want visible in AI search.",
            fix="Find and remove the noindex directive. Look for:\n\n"
                "<meta name=\"robots\" content=\"noindex\">\n\n"
                "Change it to:\n\n"
                "<meta name=\"robots\" content=\"index, follow\">",
            impact=80,
            effort=10,
        ))
    else:
        indexable = sum(1 for p in pages if p.ok)
        components = [ScoreComponent(
            label=f"All crawled pages are indexable",
            points=10, max=10,
            detail=f"{indexable} page(s) checked, none have noindex."
        )]
        if indexable > 0:
            findings.append(Finding(
                id="meta-robots-ok",
                title="No noindex directives found on crawled pages",
                pillar=Pillar.CRAWLABILITY,
                severity=Severity.POSITIVE,
                evidence=f"All {indexable} crawled pages are indexable.",
                should_be="", fix="",
                impact=0, effort=0,
            ))

    return findings, components


def _check_performance(pages: list[PageData]) -> tuple[list[Finding], list[ScoreComponent]]:
    """Check HTTP reachability and load time."""
    findings = []
    ok_count = sum(1 for p in pages if p.ok)
    total = len([p for p in pages if not p.error])  # pages we attempted
    if total == 0:
        total = 1

    avg_load = []
    for p in pages:
        if p.ok and p.load_time_ms:
            avg_load.append(p.load_time_ms)

    avg_ms = sum(avg_load) / len(avg_load) if avg_load else 0

    # Reachability score
    reach_pct = ok_count / total if total > 0 else 0
    points = reach_pct * 5

    detail = f"{ok_count}/{total} pages reachable"
    if avg_ms > 0:
        detail += f", avg load {avg_ms:.0f}ms"

    components = [ScoreComponent(
        label=f"Page reachability: {ok_count}/{total}",
        points=points, max=5,
        detail=detail
    )]

    if reach_pct < 1.0 and total > 1:
        unreachable = [p.url for p in pages if not p.ok and not p.error]
        findings.append(Finding(
            id="http-unreachable",
            title=f"{total - ok_count} page(s) returned errors",
            pillar=Pillar.CRAWLABILITY,
            severity=Severity.WARNING,
            page=unreachable[0] if unreachable else "",
            evidence=f"{total - ok_count} of {total} pages returned non-200 status.",
            should_be="All key pages should return HTTP 200.",
            fix="Check server logs for error pages. Common causes: broken links, "
                "redirect loops, or server misconfiguration.",
            impact=50,
            effort=30,
        ))

    if avg_ms > 3000:
        findings.append(Finding(
            id="slow-load",
            title=f"Pages load slowly (avg {avg_ms:.0f}ms)",
            pillar=Pillar.CRAWLABILITY,
            severity=Severity.WARNING,
            evidence=f"Average page load time is {avg_ms:.0f}ms across crawled pages.",
            should_be="Pages should load in under 2500ms for good crawlability.",
            fix="Optimize images, enable compression (gzip/brotli), use a CDN, "
                "and minify CSS/JS. Consider lazy-loading below-the-fold content.",
            impact=30,
            effort=50,
        ))

    return findings, components
