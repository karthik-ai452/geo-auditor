"""Unit tests for the brand recall analyzer and LLM functions."""

import pytest
from unittest.mock import patch, MagicMock
from geo_auditor.models import (
    CrawlResult, PageData, Pillar, RobotsData, SitemapData,
    Finding, Severity,
)
from geo_auditor.analyzers import brand_recall
from geo_auditor import llm as llm_client


class TestInferBrandAndCategory:
    def test_infer_from_domain(self):
        """Brand name inferred from domain."""
        page = PageData(
            url="https://stripe.com",
            status_code=200,
            title="Stripe | Financial Infrastructure",
            meta_description="Online payment processing",
            text="Stripe is a payment processing platform",
        )
        crawl = CrawlResult(base_url="https://stripe.com", pages=[page], homepage=page)
        brand, aliases, category, competitors = brand_recall._infer_brand_and_category(page, "https://stripe.com")
        assert brand is not None
        assert len(brand) > 0
        assert category is not None

    def test_infer_from_jsonld(self):
        """Brand name from JSON-LD Organization."""
        page = PageData(
            url="https://example.com",
            status_code=200,
            title="Example Company",
            json_ld_blocks=[{"@type": "Organization", "name": "Example Corp"}],
            text="We build software",
        )
        brand, aliases, category, competitors = brand_recall._infer_brand_and_category(page, "https://example.com")
        assert brand == "Example Corp"

    def test_category_inference(self):
        """Category inferred from content."""
        page = PageData(
            url="https://notes.com",
            status_code=200,
            title="Notes App",
            meta_description="The best note-taking app",
            text="note-taking app for teams",
        )
        brand, aliases, category, competitors = brand_recall._infer_brand_and_category(page, "https://notes.com")
        assert category == "note-taking"

    def test_competitors_known(self):
        """Known competitors returned for common categories."""
        page = PageData(
            url="https://pay.com",
            status_code=200,
            title="Pay App",
            meta_description="Payment processing made easy",
            text="payment processing platform",
        )
        brand, aliases, category, competitors = brand_recall._infer_brand_and_category(page, "https://pay.com")
        assert category == "payment processing"
        assert len(competitors) > 0
        assert "Stripe" in competitors


class TestGenerateQueries:
    def test_generates_queries(self):
        queries = llm_client.generate_brand_recall_queries(
            brand="Stripe", category="payment processing",
            competitors=["PayPal", "Square"]
        )
        assert len(queries) >= 3
        # Should have category queries
        category = [q for q in queries if q["type"] == "category_unprompted"]
        assert len(category) >= 2
        assert all("payment processing" in q["query"] for q in category)

    def test_no_direct_brand_query(self):
        """Direct brand queries ('What is X?') are excluded — testing training
        data memorization is not actionable and probability is very low."""
        queries = llm_client.generate_brand_recall_queries(
            brand="Stripe", category="payment processing", competitors=[]
        )
        direct = [q for q in queries if q["type"] == "direct_brand"]
        assert len(direct) == 0

    def test_generates_without_competitors(self):
        queries = llm_client.generate_brand_recall_queries(
            brand="Acme", category="software", competitors=None
        )
        assert len(queries) >= 3

    def test_category_queries(self):
        queries = llm_client.generate_brand_recall_queries(
            brand="Stripe", category="payment processing", competitors=[]
        )
        cat_queries = [q for q in queries if q["type"] == "category_unprompted"]
        assert len(cat_queries) >= 2
        assert all("payment processing" in q["query"] for q in cat_queries)


class TestCheckBrandMention:
    def test_text_mention_detected(self):
        """Simple text match finds the brand."""
        response = "Stripe is a great payment processing platform. It's used by many businesses."
        result = llm_client.check_brand_mention("Stripe", ["stripe.com"], response)
        assert result["mentioned"] is True

    def test_no_mention_detected(self):
        """Text without the brand returns not mentioned."""
        response = "PayPal and Square are both popular payment processing platforms for businesses."
        # Use text match fallback by mocking the LLM
        with patch.object(llm_client, "_get_client", side_effect=RuntimeError("no LLM")):
            result = llm_client.check_brand_mention("Stripe", ["stripe.com"], response)
            assert result["mentioned"] is False

    def test_alias_mention_detected(self):
        """Brand alias is detected."""
        response = "SFDC is a popular CRM tool used by enterprises."
        result = llm_client.check_brand_mention("Salesforce", ["SFDC", "sfdc"], response)
        assert result["mentioned"] is True


class TestBrandRecallAnalyzer:
    def test_no_homepage(self):
        """Analyzer handles missing homepage gracefully."""
        crawl = CrawlResult(base_url="https://example.com", pages=[])
        findings, components, data = brand_recall.analyze(crawl)
        assert len(components) == 1
        assert components[0].points == 0

    def test_brand_recall_data_structure(self):
        """Analyzer returns proper data structure (mocked LLM calls)."""
        page = PageData(
            url="https://stripe.com",
            status_code=200,
            title="Stripe | Financial Infrastructure",
            meta_description="Online payment processing",
            text="Stripe is a payment processing platform for businesses",
        )
        crawl = CrawlResult(base_url="https://stripe.com", pages=[page], homepage=page)

        # Mock the LLM functions
        with patch.object(llm_client, "query_brand_recall", return_value="Stripe is a great payment platform. It's very popular."):
            with patch.object(llm_client, "check_brand_mention", return_value={
                "mentioned": True,
                "how_mentioned": "Stripe is mentioned as a payment platform",
                "context": "positive",
                "position": "first_quarter",
            }):
                findings, components, data = brand_recall.analyze(crawl)
                assert data["brand_name"] is not None
                assert data["category"] is not None
                assert data["mention_count"] > 0
                assert data["total_queries"] > 0
                # Should have positive finding for full recall
                positive = [f for f in findings if f.severity == Severity.POSITIVE]
                assert len(positive) >= 1


class TestPillarWeight:
    def test_brand_recall_weight(self):
        """Brand recall has the highest weight."""
        from geo_auditor.scoring import PILLAR_WEIGHTS
        assert PILLAR_WEIGHTS[Pillar.BRAND_RECALL] == 0.35
        assert PILLAR_WEIGHTS[Pillar.BRAND_RECALL] == max(PILLAR_WEIGHTS.values())
