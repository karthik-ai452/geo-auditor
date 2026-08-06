"""Main audit orchestrator — ties crawler, analyzers, scoring, and report together."""

from __future__ import annotations

import asyncio
import datetime
import logging
from urllib.parse import urlparse

from geo_auditor.analyzers import answerability, brand_recall, crawlability, source_presence, structure
from geo_auditor.crawler import crawl_site
from geo_auditor.models import AuditResult, OverallScore, Pillar, PillarScore
from geo_auditor.report import save_report
from geo_auditor.scoring import build_action_plan, compute_overall_score, compute_pillar_score

logger = logging.getLogger(__name__)


async def run_audit(url: str, output_dir=None) -> AuditResult:
    """Run a full GEO audit on the given URL.

    1. Crawls the site (robots.txt, sitemap, key pages)
    2. Runs all five analyzers
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
    answer_findings, answer_components, answer_llm_data = answerability.analyze(crawl)
    if answer_llm_data.get("error"):
        print(f"   ⚠ LLM judge unavailable — using rule-based scoring. ({answer_llm_data['error'][:60]})")

    # Pillar 4: Brand Recall (LLM-based)
    print("   → AI brand recall (testing real AI knowledge)...")
    brand_findings, brand_components, brand_data = brand_recall.analyze(crawl)
    if brand_data.get("llm_error"):
        print(f"   ⚠ Brand recall LLM unavailable — scoring 0 for this pillar.")
    else:
        mention_count = brand_data.get("mention_count", 0)
        total_q = brand_data.get("total_queries", 0)
        print(f"   → Brand recall: {brand_data.get('brand_name', '?')} mentioned in {mention_count}/{total_q} AI queries")

    # Pillar 5: AI Visibility & Competitive Intelligence
    print("   → AI visibility & competitive intelligence...")
    presence_findings, presence_components, presence_data = source_presence.analyze(crawl, brand_data)
    found_count = sum(1 for r in presence_data.get("platform_coverage", {}).get("platform_results", []) if r.get("found"))
    total_platforms = len(presence_data.get("platform_coverage", {}).get("platform_results", []))
    print(f"   → Platform coverage: {found_count}/{total_platforms} platforms")
    sov = presence_data.get("share_of_voice", {})
    if sov.get("target_sov") is not None:
        print(f"   → Share of voice: {sov['target_sov']:.0%}")
    pos = presence_data.get("positioning_accuracy", {})
    if pos.get("accuracy_score"):
        print(f"   → Positioning accuracy: {pos['accuracy_score']:.0f}/100")

    all_findings = crawl_findings + answer_findings + struct_findings + brand_findings + presence_findings

    # --- 3. Score ---
    print("\n📊 Computing scores...")
    pillar_scores = [
        compute_pillar_score(Pillar.CRAWLABILITY, crawl_components),
        compute_pillar_score(Pillar.ANSWERABILITY, answer_components),
        compute_pillar_score(Pillar.STRUCTURE, struct_components),
        compute_pillar_score(Pillar.BRAND_RECALL, brand_components),
        compute_pillar_score(Pillar.SOURCE_PRESENCE, presence_components),
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
        combined_llm_data = {**(answer_llm_data if "answer_llm_data" in dir() else {})}
        if brand_data:
            combined_llm_data["brand_recall"] = brand_data
        if presence_data:
            combined_llm_data["source_presence"] = presence_data
        html_path, json_path = save_report(result, output_dir, combined_llm_data)
        print(f"\n💾 Report saved:")
        print(f"   HTML: {html_path}")
        print(f"   JSON: {json_path}")

    print(f"\n{'='*60}")
    print(f"  Audit complete — {len(all_findings)} findings, score {overall.total}/100")
    print(f"{'='*60}\n")

    return result
