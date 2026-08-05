"""Unit tests for analyzers — crawlability, structure, answerability."""

import pytest
from geo_auditor.models import (
    CrawlResult, PageData, RobotsData, SitemapData,
    Finding, Pillar, Severity, ScoreComponent,
)
from geo_auditor.analyzers import crawlability, structure, answerability


class TestCrawlabilityAnalyzer:
    def test_all_bots_allowed(self):
        """Site with no bot blocks scores well on crawlability."""
        crawl = CrawlResult(
            base_url="https://example.com",
            robots=RobotsData(fetch_ok=True, status_code=200, bot_rules={
                bot: None for bot in ["GPTBot", "ClaudeBot", "PerplexityBot"]
            }),
            sitemap=SitemapData(fetch_ok=True, status_code=200, url_count=50),
            pages=[PageData(url="https://example.com", status_code=200, meta_robots="index, follow")],
        )
        findings, components = crawlability.analyze(crawl)
        # Should have positive findings
        positive_findings = [f for f in findings if f.severity == Severity.POSITIVE]
        assert len(positive_findings) >= 1
        # Should score reasonably high
        total_pts = sum(c.points for c in components)
        total_max = sum(c.max for c in components)
        assert total_pts / total_max > 0.7

    def test_blocked_bot_critical_finding(self):
        """Blocked bot produces a critical finding with copy-pasteable fix."""
        crawl = CrawlResult(
            base_url="https://example.com",
            robots=RobotsData(fetch_ok=True, status_code=200, bot_rules={
                "GPTBot": False,  # blocked
                "ClaudeBot": None,
                "PerplexityBot": None,
            }),
            sitemap=SitemapData(fetch_ok=True, status_code=200, url_count=10),
            pages=[PageData(url="https://example.com", status_code=200)],
        )
        findings, components = crawlability.analyze(crawl)
        critical = [f for f in findings if f.severity == Severity.CRITICAL]
        assert len(critical) >= 1
        # Check the fix is copy-pasteable
        gptbot_finding = [f for f in findings if "GPTBot" in f.title]
        assert len(gptbot_finding) >= 1
        assert "User-agent: GPTBot" in gptbot_finding[0].fix
        assert "Allow: /" in gptbot_finding[0].fix

    def test_no_robots_txt_warning(self):
        """Missing robots.txt produces a warning."""
        crawl = CrawlResult(
            base_url="https://example.com",
            robots=RobotsData(fetch_ok=False, status_code=404),
            sitemap=SitemapData(fetch_ok=False, status_code=404),
            pages=[PageData(url="https://example.com", status_code=200)],
        )
        findings, components = crawlability.analyze(crawl)
        # Should have warnings about missing robots.txt and sitemap
        warnings = [f for f in findings if f.severity == Severity.WARNING]
        assert len(warnings) >= 2  # robots.txt + sitemap missing

    def test_noindex_finding(self):
        """noindex produces a critical finding."""
        crawl = CrawlResult(
            base_url="https://example.com",
            robots=RobotsData(fetch_ok=True, status_code=200),
            sitemap=SitemapData(fetch_ok=True, status_code=200, url_count=5),
            pages=[PageData(url="https://example.com/hidden", status_code=200,
                            meta_robots="noindex")],
        )
        findings, components = crawlability.analyze(crawl)
        noindex_findings = [f for f in findings if "noindex" in f.id]
        assert len(noindex_findings) >= 1
        assert noindex_findings[0].severity == Severity.CRITICAL


class TestStructureAnalyzer:
    def test_full_structure(self):
        """Page with good structure scores well."""
        import json
        homepage = PageData(
            url="https://example.com",
            status_code=200,
            title="Example Company — We Build Great Products",
            meta_description="A great company that builds things for you.",
            canonical="https://example.com",
            og_title="Example Company",
            og_description="A great company",
            h1_tags=["Welcome to Example"],
            h2_tags=["Products", "About Us", "Contact"],
            word_count=500,
            paragraph_count=8,
            json_ld_blocks=[
                {"@type": "Organization", "name": "Example Co"},
                {"@type": "WebSite", "name": "Example"},
            ],
        )
        crawl = CrawlResult(base_url="https://example.com", pages=[homepage], homepage=homepage)
        findings, components = structure.analyze(crawl)
        total_pts = sum(c.points for c in components)
        total_max = sum(c.max for c in components)
        assert total_pts / total_max > 0.8

    def test_missing_everything(self):
        """Bare HTML page with no structure."""
        homepage = PageData(
            url="https://example.com",
            status_code=200,
            title="",
            meta_description="",
            canonical="",
            og_title="",
            og_description="",
            h1_tags=[],
            h2_tags=[],
            word_count=10,
            paragraph_count=0,
            json_ld_blocks=[],
        )
        crawl = CrawlResult(base_url="https://example.com", pages=[homepage], homepage=homepage)
        findings, components = structure.analyze(crawl)
        # Should have critical/warning findings
        criticals = [f for f in findings if f.severity == Severity.CRITICAL]
        warnings = [f for f in findings if f.severity == Severity.WARNING]
        assert len(criticals) >= 1  # no JSON-LD
        assert len(warnings) >= 2  # no title/meta/h1

        # Should score very low
        total_pts = sum(c.points for c in components)
        total_max = sum(c.max for c in components)
        assert total_pts / total_max < 0.2

    def test_jsonld_fix_is_copy_pasteable(self):
        """JSON-LD fix should include a usable code block."""
        homepage = PageData(
            url="https://example.com",
            status_code=200,
            title="Example",
            json_ld_blocks=[],
            h1_tags=["H1"],
            h2_tags=["H2"],
            word_count=100,
            paragraph_count=5,
        )
        crawl = CrawlResult(base_url="https://example.com", pages=[homepage], homepage=homepage)
        findings, components = structure.analyze(crawl)
        jsonld_finding = [f for f in findings if "no-jsonld" in f.id]
        assert len(jsonld_finding) >= 1
        fix = jsonld_finding[0].fix
        assert "application/ld+json" in fix
        assert "Organization" in fix
        assert "@context" in fix


class TestAnswerabilityFallback:
    """Test the rule-based fallback when LLM is unavailable."""

    def test_signals_with_good_content(self):
        """Content with stats, definitions, citations, and FAQ scores reasonably."""
        homepage = PageData(
            url="https://example.com",
            status_code=200,
            text="Some content with 50% stats and definitions",
            word_count=500,
            stats_count=10,
            has_definition=True,
            has_citations=True,
            has_faq_schema=True,
            h2_tags=["Section 1", "Section 2"],
        )
        crawl = CrawlResult(base_url="https://example.com", pages=[homepage], homepage=homepage)
        findings, components, llm_data = answerability.analyze(crawl)
        # Rule-based fallback should kick in (no LLM key in test env)
        # Positive findings for good content
        positives = [f for f in findings if f.severity == Severity.POSITIVE]
        assert len(positives) >= 1

    def test_signals_with_poor_content(self):
        """Bare content triggers warnings."""
        homepage = PageData(
            url="https://example.com",
            status_code=200,
            text="Bare text without any value.",
            word_count=20,
            stats_count=0,
            has_definition=False,
            has_citations=False,
            has_faq_schema=False,
            h2_tags=[],
        )
        crawl = CrawlResult(base_url="https://example.com", pages=[homepage], homepage=homepage)
        findings, components, llm_data = answerability.analyze(crawl)
        # Should have warnings for missing content quality
        warnings = [f for f in findings if f.severity == Severity.WARNING]
        assert len(warnings) >= 2

    def test_faq_fix_is_copy_pasteable(self):
        """FAQ fix should include a usable schema block."""
        homepage = PageData(
            url="https://example.com",
            status_code=200,
            text="Content",
            word_count=100,
            stats_count=0,
            has_definition=False,
            has_citations=False,
            has_faq_schema=False,
        )
        crawl = CrawlResult(base_url="https://example.com", pages=[homepage], homepage=homepage)
        findings, components, llm_data = answerability.analyze(crawl)
        faq_finding = [f for f in findings if "signal-no-faq" in f.id]
        assert len(faq_finding) >= 1
        fix = faq_finding[0].fix
        assert "FAQPage" in fix
        assert "application/ld+json" in fix
