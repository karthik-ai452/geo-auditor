"""Unit tests for the crawler module — robots.txt, sitemap, text extraction."""

import pytest
from geo_auditor.crawler import (
    parse_robots_txt,
    parse_sitemap,
    extract_page_data,
    normalize_url,
    get_base_url,
    _bot_allowed,
    _evaluate_rules,
    AI_BOTS,
)
from geo_auditor.models import RobotsData


class TestNormalizeUrl:
    def test_adds_https(self):
        assert normalize_url("example.com") == "https://example.com/"

    def test_preserves_https(self):
        assert normalize_url("https://example.com") == "https://example.com/"

    def test_strips_trailing_slash(self):
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_preserves_path(self):
        assert normalize_url("https://example.com/blog/post") == "https://example.com/blog/post"


class TestGetBaseUrl:
    def test_simple(self):
        assert get_base_url("https://example.com/blog/post") == "https://example.com"

    def test_with_port(self):
        assert get_base_url("http://localhost:8000/page") == "http://localhost:8000"


class TestParseRobotsTxt:
    def test_all_allowed_default(self):
        """Empty robots.txt means everything is allowed."""
        robots = parse_robots_txt("")
        assert robots.fetch_ok
        for bot in AI_BOTS:
            assert robots.bot_rules[bot] is None  # not mentioned = allowed

    def test_block_all(self):
        """User-agent: * Disallow: / blocks everyone."""
        robots = parse_robots_txt("User-agent: *\nDisallow: /")
        for bot in AI_BOTS:
            assert robots.bot_rules[bot] is False

    def test_block_specific_bot(self):
        """Block only GPTBot."""
        robots = parse_robots_txt("User-agent: GPTBot\nDisallow: /")
        assert robots.bot_rules["GPTBot"] is False
        # Other bots should be allowed
        assert robots.bot_rules["ClaudeBot"] is None

    def test_allow_specific_bot(self):
        """Explicitly allow GPTBot."""
        robots = parse_robots_txt("User-agent: GPTBot\nAllow: /")
        assert robots.bot_rules["GPTBot"] is True

    def test_mixed_rules(self):
        """Block GPTBot, allow others."""
        txt = """User-agent: GPTBot
Disallow: /

User-agent: *
Allow: /"""
        robots = parse_robots_txt(txt)
        assert robots.bot_rules["GPTBot"] is False
        assert robots.bot_rules["ClaudeBot"] is True

    def test_sitemap_extraction(self):
        """Extract sitemap declarations."""
        txt = """User-agent: *
Allow: /

Sitemap: https://example.com/sitemap.xml
Sitemap: https://example.com/sitemap-2.xml"""
        robots = parse_robots_txt(txt)
        assert len(robots.sitemap_urls) == 2
        assert "https://example.com/sitemap.xml" in robots.sitemap_urls

    def test_comments_ignored(self):
        """Comments (#) are ignored."""
        txt = """# This is a comment
User-agent: *  # inline comment
Allow: /
# Another comment"""
        robots = parse_robots_txt(txt)
        for bot in AI_BOTS:
            assert robots.bot_rules[bot] is True


class TestParseSitemap:
    def test_url_set(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/about</loc></url>
  <url><loc>https://example.com/blog</loc></url>
</urlset>"""
        result = parse_sitemap(xml)
        assert result.fetch_ok
        assert result.url_count == 3
        assert not result.is_index
        assert "https://example.com/" in result.urls

    def test_sitemap_index(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-1.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap-2.xml</loc></sitemap>
</sitemapindex>"""
        result = parse_sitemap(xml)
        assert result.is_index
        assert result.child_sitemap_count == 2
        assert result.url_count == 2

    def test_empty_sitemap(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>"""
        result = parse_sitemap(xml)
        assert result.url_count == 0


class TestExtractPageData:
    def test_basic_extraction(self):
        html = """<!DOCTYPE html>
<html><head>
<title>Test Page</title>
<meta name="description" content="A test page">
<meta name="robots" content="index, follow">
<link rel="canonical" href="https://example.com/page">
</head><body>
<h1>Main Heading</h1>
<h2>Subheading</h2>
<p>This is a paragraph with some text content.</p>
<p>Another paragraph with 50% more data.</p>
</body></html>"""
        page = extract_page_data(html, "https://example.com/page", 200, 150.0)
        assert page.title == "Test Page"
        assert page.meta_description == "A test page"
        assert page.meta_robots == "index, follow"
        assert page.canonical == "https://example.com/page"
        assert len(page.h1_tags) == 1
        assert "Main Heading" in page.h1_tags
        assert len(page.h2_tags) == 1
        assert page.word_count > 0
        assert page.stats_count > 0  # "50%" should be detected

    def test_json_ld_extraction(self):
        html = """<!DOCTYPE html>
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Organization", "name": "Test Co"}
</script>
</head><body><h1>Test</h1><p>Content</p></body></html>"""
        page = extract_page_data(html, "https://example.com", 200, 100.0)
        assert len(page.json_ld_blocks) == 1
        assert page.json_ld_blocks[0]["@type"] == "Organization"
        assert page.json_ld_blocks[0]["name"] == "Test Co"

    def test_json_ld_graph(self):
        html = """<!DOCTYPE html>
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [
  {"@type": "Organization", "name": "Test Co"},
  {"@type": "WebSite", "name": "Test Site"}
]}
</script>
</head><body><h1>Test</h1></body></html>"""
        page = extract_page_data(html, "https://example.com", 200, 100.0)
        assert len(page.json_ld_blocks) == 2
        types = [b["@type"] for b in page.json_ld_blocks]
        assert "Organization" in types
        assert "WebSite" in types

    def test_malformed_json_ld(self):
        html = """<!DOCTYPE html>
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Organization", "name": "Broken
</script>
</head><body><h1>Test</h1></body></html>"""
        page = extract_page_data(html, "https://example.com", 200, 100.0)
        assert len(page.json_ld_blocks) == 1
        assert page.json_ld_blocks[0].get("_malformed") is True

    def test_faq_schema_detection(self):
        html = """<!DOCTYPE html>
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": []}
</script>
</head><body><h1>FAQ</h1></body></html>"""
        page = extract_page_data(html, "https://example.com", 200, 100.0)
        assert page.has_faq_schema is True

    def test_definition_detection(self):
        html = """<!DOCTYPE html>
<html><head><title>CRM</title></head>
<body><h1>CRM</h1><p>CRM is a tool for managing customer relationships.</p></body></html>"""
        page = extract_page_data(html, "https://example.com", 200, 100.0)
        assert page.has_definition is True

    def test_open_graph_extraction(self):
        html = """<!DOCTYPE html>
<html><head>
<meta property="og:title" content="OG Title">
<meta property="og:description" content="OG Description">
</head><body><h1>Test</h1></body></html>"""
        page = extract_page_data(html, "https://example.com", 200, 100.0)
        assert page.og_title == "OG Title"
        assert page.og_description == "OG Description"

    def test_noindex_detection(self):
        html = """<!DOCTYPE html>
<html><head>
<meta name="robots" content="noindex, nofollow">
</head><body><h1>Hidden</h1></body></html>"""
        page = extract_page_data(html, "https://example.com", 200, 100.0)
        assert "noindex" in page.meta_robots.lower()
