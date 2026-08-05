"""Main audit orchestrator — ties crawler, analyzers, scoring, and report together."""

from __future__ import annotations

import asyncio
import datetime
import logging
from urllib.parse import urlparse

from geo_auditor.analyzers import answerability, crawlability, structure
from geo_auditor.crawler import crawl_site
from geo_auditor.models import AuditResult, OverallScore, Pillar, PillarScore
from geo_auditor.report import save_report
from geo_auditor.scoring import build_action_plan, compute_overall_score, compute_pillar_score

logger = logging.getLogger(__name__)


async def run_audit(url: str, output_dir=None) -> AuditResult:
    """Run a full GEO audit on the given URL.

    1. Crawls the site (robots.txt, sitemap, key pages)
    2. Runs all three analyzers
    3. Computes scores
    4. Builds the action plan
    5. Returns the AuditResult
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    print(f"\n{'='*60}")
    print(f"  GEO Auditor — Auditing {url}")
    print(f"{'='*60}\n")

    # --- 1. Crawl ---
    print("📡 Crawling site (robots.txt, sitemap, pages)...")
    crawl = await crawl_site(url)
    print(f"   ✓ Robots.txt: {'found' if crawl.robots.fetch_ok else 'not found'}")
    print(f"   ✓ Sitemap: {crawl.sitemap.url_count} URLs" +
          (f" (index of {crawl.sitemap.child_sitemap_count} sitemaps)" if crawl.sitemap.is_index else ""))
    print(f"   ✓ Pages crawled: {crawl.page_count}")

    # --- 2. Analyze ---
    print("\n🔍 Running analyzers...")

    # Pillar 1: Crawlability
    print("   → Crawlability (robots.txt, sitemap, meta robots)...")
    crawl_findings, crawl_components = crawlability.analyze(crawl)

    # Pillar 3: Structure
    print("   → Structured data (JSON-LD, meta tags, semantic HTML)...")
    struct_findings, struct_components = structure.analyze(crawl)

    # Pillar 2: Answerability (LLM-as-judge)
    print("   → Content answerability (LLM-as-judge)...")
    answer_findings, answer_components, llm_data = answerability.analyze(crawl)
    if llm_data.get("error"):
        print(f"   ⚠ LLM judge unavailable — using rule-based scoring. ({llm_data['error'][:60]})")

    all_findings = crawl_findings + answer_findings + struct_findings

    # --- 3. Score ---
    print("\n📊 Computing scores...")
    pillar_scores = [
        compute_pillar_score(Pillar.CRAWLABILITY, crawl_components),
        compute_pillar_score(Pillar.ANSWERABILITY, answer_components),
        compute_pillar_score(Pillar.STRUCTURE, struct_components),
    ]
    overall = compute_overall_score(pillar_scores)

    for ps in pillar_scores:
        print(f"   {ps.pillar.value.title():<20} {ps.score:>5.1f}/100 (weight: {ps.weight*100:.0f}%)")
    print(f"   {'OVERALL':<20} {overall.total:>5.1f}/100 — {overall.grade}")

    # --- 4. Action plan ---
    action_plan = build_action_plan(all_findings)
    print(f"\n📋 Action plan: {len(action_plan)} prioritized fixes")

    # --- 5. Build result ---
    domain = urlparse(crawl.base_url).netloc
    result = AuditResult(
        url=crawl.base_url,
        domain=domain,
        audited_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        score=overall,
        findings=all_findings,
        crawl=crawl,
        action_plan=action_plan,
    )

    # --- 6. Save report ---
    if output_dir is not None:
        html_path, json_path = save_report(result, output_dir, llm_data)
        print(f"\n💾 Report saved:")
        print(f"   HTML: {html_path}")
        print(f"   JSON: {json_path}")

    print(f"\n{'='*60}")
    print(f"  Audit complete — {len(all_findings)} findings, score {overall.total}/100")
    print(f"{'='*60}\n")

    return result
