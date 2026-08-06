"""Tests for the AI Visibility & Competitive Intelligence analyzer (Pillar 5)."""

from unittest.mock import MagicMock, patch

import pytest

from geo_auditor.analyzers import source_presence
from geo_auditor.models import (
    CrawlResult,
    Finding,
    PageData,
    Pillar,
    ScoreComponent,
    Severity,
)


@pytest.fixture
def fake_homepage():
    return PageData(
        url="https://stripe.com",
        title="Stripe | Payment Processing",
        meta_description="Online payment processing for businesses",
        text="Stripe is a technology company that builds economic infrastructure for the internet.",
        json_ld_blocks=[{"@type": "Organization", "name": "Stripe"}],
    )


@pytest.fixture
def fake_crawl(fake_homepage):
    return CrawlResult(base_url="https://stripe.com", homepage=fake_homepage, pages=[fake_homepage])


@pytest.fixture
def fake_brand_recall_data():
    return {
        "brand_name": "Stripe",
        "brand_aliases": ["stripe inc"],
        "category": "payment processing",
        "competitors": ["PayPal", "Square", "Adyen"],
        "query_results": [
            {
                "query": "What are the best payment processing platforms?",
                "response": "Stripe and PayPal are top payment processing platforms.",
                "mention": {"mentioned": True, "citation_rank": 1},
            },
            {
                "query": "Compare payment processing platforms",
                "response": "Stripe is developer-friendly. PayPal is more mainstream. Square is for small business.",
                "mention": {"mentioned": True, "citation_rank": 1},
            },
        ],
    }


@pytest.fixture
def empty_crawl():
    return CrawlResult(base_url="https://example.com")


# ---------------------------------------------------------------------------
# Brand inference and slug
# ---------------------------------------------------------------------------


class TestBrandInference:
    def test_infers_from_jsonld(self, fake_homepage):
        brand, domain = source_presence._infer_brand(fake_homepage, "https://stripe.com")
        assert brand == "Stripe"
        assert domain == "stripe.com"

    def test_falls_back_to_domain(self):
        page = PageData(url="https://notion.so", title="Notion – One tool")
        brand, domain = source_presence._infer_brand(page, "https://notion.so")
        assert brand == "Notion"

    def test_strips_www(self):
        page = PageData(url="https://www.stripe.com", title="Stripe")
        _, domain = source_presence._infer_brand(page, "https://www.stripe.com")
        assert domain == "stripe.com"


class TestSlug:
    def test_simple(self):
        assert source_presence._slug("Stripe") == "stripe"

    def test_multi_word(self):
        assert source_presence._slug("Acme Corp") == "acme"

    def test_suffix_removed(self):
        assert source_presence._slug("Acme Inc") == "acme"


# ---------------------------------------------------------------------------
# Platform check functions
# ---------------------------------------------------------------------------


class TestPlatformChecks:
    def test_wikipedia_found(self):
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"query": {"search": [{"title": "Stripe"}]}}
        client.get = MagicMock(return_value=resp)
        found, evidence = source_presence._check_wikipedia_sync(client, "Stripe", "stripe.com")
        assert found is True

    def test_wikipedia_not_found(self):
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"query": {"search": []}}
        client.get = MagicMock(return_value=resp)
        found, _ = source_presence._check_wikipedia_sync(client, "UnknownBrand", "unknown.com")
        assert found is False

    def test_github_found(self):
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "<html>Stripe</html>"
        client.get = MagicMock(return_value=resp)
        found, evidence = source_presence._check_github_sync(client, "Stripe", "stripe.com")
        assert found is True

    def test_github_not_found(self):
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 404
        resp.text = "Page not found"
        client.get = MagicMock(return_value=resp)
        found, _ = source_presence._check_github_sync(client, "Nonexistent", "nonexistent.com")
        assert found is False


# ---------------------------------------------------------------------------
# Sub-check 1: Platform coverage
# ---------------------------------------------------------------------------


class TestPlatformCoverage:
    @patch("geo_auditor.analyzers.source_presence._run_platform_checks")
    def test_all_found(self, mock_run, fake_crawl):
        mock_run.return_value = [
            {"platform": p[0], "display_name": p[1], "searched_by": p[2], "found": True, "evidence": "found"}
            for p in source_presence.PLATFORMS
        ]
        findings, components, data = source_presence._check_platform_coverage(
            "Stripe", "stripe.com", fake_crawl.homepage
        )
        assert len(components) == 7
        assert all(c.points > 0 for c in components)

    @patch("geo_auditor.analyzers.source_presence._run_platform_checks")
    def test_none_found(self, mock_run):
        mock_run.return_value = [
            {"platform": p[0], "display_name": p[1], "searched_by": p[2], "found": False, "evidence": "missing"}
            for p in source_presence.PLATFORMS
        ]
        findings, components, data = source_presence._check_platform_coverage(
            "Stripe", "stripe.com", fake_homepage_data()
        )
        assert any(f.severity == Severity.CRITICAL for f in findings)


def fake_homepage_data():
    return PageData(url="https://stripe.com", title="Stripe", text="Stripe is a payment platform")


# ---------------------------------------------------------------------------
# Sub-check 2: Competitive coverage gap
# ---------------------------------------------------------------------------


class TestCompetitiveGap:
    @patch("geo_auditor.analyzers.source_presence._run_platform_checks")
    def test_gap_detected(self, mock_run, fake_homepage):
        # Target: on 3 platforms. Competitor: on 5 platforms.
        def mock_checks(brand, domain):
            if brand == "Stripe":
                return [
                    {"platform": p[0], "display_name": p[1], "found": i < 3, "evidence": ""}
                    for i, p in enumerate(source_presence.PLATFORMS)
                ]
            else:  # competitor
                return [
                    {"platform": p[0], "display_name": p[1], "found": i < 5, "evidence": ""}
                    for i, p in enumerate(source_presence.PLATFORMS)
                ]
        mock_run.side_effect = mock_checks

        target_data = {"platform_results": [
            {"platform": p[0], "found": i < 3} for i, p in enumerate(source_presence.PLATFORMS)
        ]}
        findings, components, data = source_presence._check_competitive_gap(
            "Stripe", "stripe.com", ["PayPal"], target_data
        )
        assert data["gap_count"] > 0

    def test_no_competitors(self):
        findings, components, data = source_presence._check_competitive_gap(
            "Stripe", "stripe.com", [], {}
        )
        assert data["gap_count"] == 0


# ---------------------------------------------------------------------------
# Sub-check 3: Positioning accuracy
# ---------------------------------------------------------------------------


class TestPositioningAccuracy:
    @patch("geo_auditor.llm.check_positioning_accuracy")
    def test_accurate(self, mock_pos, fake_crawl, fake_brand_recall_data):
        mock_pos.return_value = {
            "accuracy_score": 90,
            "mismatches": [],
            "summary": "AI accurately describes Stripe.",
        }
        findings, components, data = source_presence._check_positioning_accuracy(
            "Stripe", fake_crawl.homepage, fake_brand_recall_data
        )
        assert components[0].points > 15  # high score
        assert any(f.severity == Severity.POSITIVE for f in findings)

    @patch("geo_auditor.llm.check_positioning_accuracy")
    def test_critical_mismatch(self, mock_pos, fake_crawl, fake_brand_recall_data):
        mock_pos.return_value = {
            "accuracy_score": 30,
            "mismatches": [{
                "category": "price",
                "self_description": "premium payment platform",
                "ai_description": "affordable payment platform",
                "severity": "critical",
            }],
            "summary": "Major positioning mismatch detected.",
        }
        findings, components, data = source_presence._check_positioning_accuracy(
            "Stripe", fake_crawl.homepage, fake_brand_recall_data
        )
        assert any(f.severity == Severity.CRITICAL for f in findings)

    def test_no_ai_responses(self, fake_crawl):
        findings, components, data = source_presence._check_positioning_accuracy(
            "Stripe", fake_crawl.homepage, {}
        )
        assert components[0].points == 0


# ---------------------------------------------------------------------------
# Sub-check 4: Share of voice
# ---------------------------------------------------------------------------


class TestShareOfVoice:
    @patch("geo_auditor.llm.analyze_competitor_mentions")
    def test_target_dominates(self, mock_analyze, fake_brand_recall_data):
        mock_analyze.return_value = {"brands": [
            {"name": "Stripe", "mentioned": True, "favorability": "positive", "citation_rank": 1},
            {"name": "PayPal", "mentioned": True, "favorability": "neutral", "citation_rank": 2},
            {"name": "Square", "mentioned": False, "favorability": "not_mentioned", "citation_rank": 0},
        ]}
        findings, components, data = source_presence._check_share_of_voice(
            "Stripe", ["PayPal", "Square", "Adyen"], fake_brand_recall_data
        )
        assert data["target_sov"] >= 0.4
        assert components[0].points > 10

    @patch("geo_auditor.llm.analyze_competitor_mentions")
    def test_competitors_dominate(self, mock_analyze, fake_brand_recall_data):
        mock_analyze.return_value = {"brands": [
            {"name": "Stripe", "mentioned": False, "favorability": "not_mentioned", "citation_rank": 0},
            {"name": "PayPal", "mentioned": True, "favorability": "positive", "citation_rank": 1},
            {"name": "Square", "mentioned": True, "favorability": "positive", "citation_rank": 2},
        ]}
        findings, components, data = source_presence._check_share_of_voice(
            "Stripe", ["PayPal", "Square", "Adyen"], fake_brand_recall_data
        )
        assert data["target_sov"] < 0.25
        assert any(f.severity == Severity.WARNING for f in findings)

    def test_no_query_results(self):
        findings, components, data = source_presence._check_share_of_voice(
            "Stripe", ["PayPal"], {}
        )
        assert components[0].points == 0


# ---------------------------------------------------------------------------
# Sub-check 5: Vector search inclusion
# ---------------------------------------------------------------------------


class TestVectorSearch:
    @patch("geo_auditor.llm.compute_vector_search_inclusion")
    def test_high_similarity(self, mock_vs, fake_crawl):
        mock_vs.return_value = {
            "similarity_score": 0.85,
            "will_be_retrieved": "high — your content will be retrieved",
            "query_similarities": [{"query": "best payment processing", "similarity": 0.85}],
            "detail": "Average similarity: 85%",
        }
        findings, components, data = source_presence._check_vector_search(
            "Stripe", fake_crawl.homepage, "payment processing"
        )
        assert components[0].points > 15

    @patch("geo_auditor.llm.compute_vector_search_inclusion")
    def test_very_low_similarity(self, mock_vs, fake_crawl):
        mock_vs.return_value = {
            "similarity_score": 0.15,
            "will_be_retrieved": "very low — vector search will not surface your content",
            "query_similarities": [{"query": "best payment processing", "similarity": 0.15}],
            "detail": "Average similarity: 15%",
        }
        findings, components, data = source_presence._check_vector_search(
            "Stripe", fake_crawl.homepage, "payment processing"
        )
        assert any(f.severity == Severity.CRITICAL for f in findings)

    def test_no_content(self):
        page = PageData(url="https://stripe.com", title="Stripe", text="")
        crawl = CrawlResult(base_url="https://stripe.com", homepage=page, pages=[page])
        findings, components, data = source_presence._check_vector_search(
            "Stripe", page, "payment processing"
        )
        assert components[0].points == 0


# ---------------------------------------------------------------------------
# Fix generators
# ---------------------------------------------------------------------------


class TestFixes:
    def test_platform_fix_lists_missing(self):
        results = [{"display_name": "Wikipedia", "found": False}]
        fix = source_presence._platform_fix("TestBrand", results)
        assert "Wikipedia" in fix
        assert "TestBrand" in fix

    def test_competitive_gap_fix(self):
        map_data = [{"status": "gap", "detail": "Competitor is on YouTube but you're not"}]
        fix = source_presence._competitive_gap_fix("TestBrand", map_data)
        assert "YouTube" in fix

    def test_positioning_fix(self):
        mismatches = [{"category": "price", "self_description": "premium", "ai_description": "affordable"}]
        fix = source_presence._positioning_fix("TestBrand", mismatches)
        assert "premium" in fix
        assert "affordable" in fix


# ---------------------------------------------------------------------------
# Full analyze with no homepage
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_homepage(self, empty_crawl):
        findings, components, data = source_presence.analyze(empty_crawl)
        assert len(findings) == 0
        assert components[0].points == 0
