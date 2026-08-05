"""Pillar 4 — AI Brand Recall Analyzer.

This pillar answers: **Do AI search engines actually know and mention
your business?**

The previous three pillars check *preconditions* — can bots reach you,
is your content answerable, is your data parseable. This pillar checks
the *outcome*: we send real questions to an LLM and measure whether it
actually mentions the target business.

This tests the two ways AI engines surface businesses:
  1. Training data knowledge — does the model already know about you?
  2. Category/competitor queries — when asked about your industry, do you
     come up unprompted?

This is the closest proxy to "will ChatGPT/Perplexity/Claude mention me
when a potential customer asks?" — without requiring access to the actual
engines (which don't offer citation APIs).

If the LLM is unavailable, this pillar cannot run and scores 0.
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

# Category inference — maps domain patterns to industry categories
# for generating relevant brand recall queries
CATEGORY_INFERENCE = {
    "payment": "payment processing",
    "pay": "payment processing",
    "bank": "banking",
    "finance": "fintech",
    "crm": "customer relationship management",
    "project management": "project management",
    "task": "task management",
    "design": "design",
    "graphic": "design",
    "note": "note-taking",
    "wiki": "knowledge management",
    "doc": "document management",
    "analytics": "web analytics",
    "track": "analytics",
    "marketing": "marketing",
    "email": "email marketing",
    "sales": "sales",
    "ai": "AI tools",
    "ml": "machine learning",
    "cloud": "cloud computing",
    "dev": "developer tools",
    "code": "developer tools",
    "api": "API platforms",
    "hosting": "web hosting",
    "security": "cybersecurity",
    "vpn": "VPN",
    "shop": "e-commerce",
    "store": "e-commerce",
    "commerce": "e-commerce",
    "hotel": "hospitality",
    "travel": "travel",
    "health": "healthcare",
    "medical": "healthcare",
    "edu": "education",
    "learn": "education",
    "course": "education",
    "food": "food",
    "restaurant": "restaurant",
    "real estate": "real estate",
    "property": "real estate",
    "insurance": "insurance",
    "legal": "legal services",
    "account": "accounting",
}

# Known competitors for common categories (for competitor-anchored queries)
KNOWN_COMPETITORS = {
    "payment processing": ["Stripe", "PayPal", "Square"],
    "fintech": ["Stripe", "Plaid", "Square"],
    "customer relationship management": ["Salesforce", "HubSpot", "Pipedrive"],
    "project management": ["Asana", "Monday.com", "Trello"],
    "note-taking": ["Notion", "Obsidian", "Evernote"],
    "knowledge management": ["Notion", "Confluence", "Obsidian"],
    "design": ["Figma", "Canva", "Adobe"],
    "web analytics": ["Google Analytics", "Mixpanel", "Amplitude"],
    "developer tools": ["GitHub", "GitLab", "Bitbucket"],
    "cloud computing": ["AWS", "Google Cloud", "Azure"],
    "e-commerce": ["Shopify", "WooCommerce", "BigCommerce"],
    "education": ["Coursera", "Udemy", "edX"],
}


def analyze(crawl: CrawlResult) -> tuple[list[Finding], list[ScoreComponent], dict[str, Any]]:
    """Run the AI Brand Recall analysis.

    Returns (findings, score_components, raw_data).
    """
    findings: list[Finding] = []
    components: list[ScoreComponent] = []
    raw_data: dict[str, Any] = {}

    homepage = crawl.homepage or (crawl.pages[0] if crawl.pages else None)
    if not homepage or not homepage.ok:
        components.append(ScoreComponent(
            label="No homepage to analyze",
            points=0, max=100,
            detail="Could not fetch the homepage to infer brand and category."
        ))
        return findings, components, raw_data

    # --- Infer brand name and category from homepage ---
    brand_name, brand_aliases, category, competitors = _infer_brand_and_category(
        homepage, crawl.base_url
    )
    raw_data["brand_name"] = brand_name
    raw_data["brand_aliases"] = brand_aliases
    raw_data["category"] = category
    raw_data["competitors"] = competitors

    if not brand_name:
        components.append(ScoreComponent(
            label="Could not determine brand name",
            points=0, max=100,
            detail="Unable to infer the business name from the homepage."
        ))
        findings.append(Finding(
            id="brand-name-unknown",
            title="Could not determine brand name for recall testing",
            pillar=Pillar.BRAND_RECALL,
            severity=Severity.INFO,
            page=homepage.url,
            evidence="The brand name could not be inferred from the homepage title, "
                     "meta tags, or domain name. Brand recall testing was skipped.",
            should_be="",
            fix="",
            impact=0,
            effort=0,
        ))
        return findings, components, raw_data

    # --- Generate queries ---
    from geo_auditor import llm as llm_client

    queries = llm_client.generate_brand_recall_queries(
        brand=brand_name, category=category, competitors=competitors
    )
    raw_data["queries"] = queries

    # --- Run each query and check for brand mention ---
    query_results = []
    mention_count = 0
    total_queries = len(queries)

    for q in queries:
        result = {
            "query": q["query"],
            "type": q["type"],
            "description": q["description"],
        }
        try:
            ai_response = llm_client.query_brand_recall(q["query"])
            result["response"] = ai_response[:2000]  # truncate for storage
            result["response_length"] = len(ai_response)

            # Check if brand is mentioned
            mention = llm_client.check_brand_mention(
                brand=brand_name,
                brand_aliases=brand_aliases,
                ai_response=ai_response,
            )
            result["mention"] = mention
            if mention.get("mentioned"):
                mention_count += 1

        except RuntimeError as e:
            result["error"] = str(e)
            raw_data["llm_error"] = str(e)

        query_results.append(result)

    raw_data["query_results"] = query_results
    raw_data["mention_count"] = mention_count
    raw_data["total_queries"] = total_queries

    # --- Compute score ---
    # Score is based on:
    # 1. Direct brand query (40 pts) — does the AI know what the company IS?
    # 2. Category unprompted queries (35 pts) — does the brand come up in category questions?
    # 3. Comparison/competitor queries (25 pts) — does it appear in comparisons?

    direct_results = [r for r in query_results if r["type"] == "direct_brand"]
    category_results = [r for r in query_results if r["type"] == "category_unprompted"]
    comparison_results = [r for r in query_results if r["type"] in ("comparison", "competitor_anchored")]

    # Direct brand query scoring
    direct_mentioned = sum(1 for r in direct_results if r.get("mention", {}).get("mentioned"))
    direct_pts = (direct_mentioned / max(len(direct_results), 1)) * 40
    components.append(ScoreComponent(
        label=f"Direct brand query: AI knows '{brand_name}' ({direct_mentioned}/{len(direct_results)})",
        points=direct_pts, max=40,
        detail=_detail_for_queries(direct_results, brand_name)
    ))

    # Category unprompted scoring
    cat_mentioned = sum(1 for r in category_results if r.get("mention", {}).get("mentioned"))
    cat_pts = (cat_mentioned / max(len(category_results), 1)) * 35
    components.append(ScoreComponent(
        label=f"Category queries: mentioned in {cat_mentioned}/{len(category_results)} industry questions",
        points=cat_pts, max=35,
        detail=_detail_for_queries(category_results, brand_name)
    ))

    # Comparison/competitor scoring
    comp_mentioned = sum(1 for r in comparison_results if r.get("mention", {}).get("mentioned"))
    comp_pts = (comp_mentioned / max(len(comparison_results), 1)) * 25
    components.append(ScoreComponent(
        label=f"Comparison queries: mentioned in {comp_mentioned}/{len(comparison_results)} comparisons",
        points=comp_pts, max=25,
        detail=_detail_for_queries(comparison_results, brand_name)
    ))

    # --- Generate findings ---
    if mention_count == 0:
        findings.append(Finding(
            id="brand-not-recalled",
            title=f"AI does not mention '{brand_name}' in any test queries",
            pillar=Pillar.BRAND_RECALL,
            severity=Severity.CRITICAL,
            page=homepage.url,
            evidence=f"Sent {total_queries} questions to an AI model about {category} "
                     f"and '{brand_name}'. The AI did not mention '{brand_name}' in any "
                     f"response. This means the model likely has no strong knowledge of "
                     f"your business in its training data.",
            should_be=f"An AI should be able to describe what {brand_name} is and mention "
                      f"it when asked about {category}.",
            fix=_brand_recall_fix(brand_name, category, "none"),
            impact=95,
            effort=60,
        ))
    elif mention_count < total_queries / 2:
        findings.append(Finding(
            id="brand-low-recall",
            title=f"AI mentions '{brand_name}' in only {mention_count}/{total_queries} queries",
            pillar=Pillar.BRAND_RECALL,
            severity=Severity.WARNING,
            page=homepage.url,
            evidence=f"Sent {total_queries} questions to an AI model. '{brand_name}' was "
                     f"mentioned in {mention_count} responses. "
                     + _evidence_summary(query_results, brand_name),
            should_be=f"'{brand_name}' should appear in most industry-related queries.",
            fix=_brand_recall_fix(brand_name, category, "low"),
            impact=70,
            effort=50,
        ))
    else:
        findings.append(Finding(
            id="brand-good-recall",
            title=f"AI knows '{brand_name}' — mentioned in {mention_count}/{total_queries} queries",
            pillar=Pillar.BRAND_RECALL,
            severity=Severity.POSITIVE,
            page=homepage.url,
            evidence=f"The AI model mentioned '{brand_name}' in {mention_count} of {total_queries} "
                     f"test queries. " + _evidence_summary(query_results, brand_name),
            should_be="",
            fix="",
            impact=0,
            effort=0,
        ))

    # Add per-query findings for missed category queries
    for r in category_results:
        if not r.get("mention", {}).get("mentioned") and not r.get("error"):
            findings.append(Finding(
                id=f"brand-missed-{r['type']}",
                title=f"Not mentioned when asked: \"{r['query'][:60]}...\"",
                pillar=Pillar.BRAND_RECALL,
                severity=Severity.WARNING,
                page=homepage.url,
                evidence=f"When asked \"{r['query']}\", the AI listed competitors but "
                         f"did not mention '{brand_name}'. "
                         + (f"AI mentioned: {_extract_brands_from_response(r.get('response', ''))[:200]}"
                            if r.get("response") else ""),
                should_be=f"'{brand_name}' should be mentioned alongside competitors in this query.",
                fix=f"Build your presence on high-authority sites that AI engines learn from: "
                    f"Wikipedia, Crunchbase, industry publications, and review sites (G2, Capterra). "
                    f"AI models learn from these sources during training.",
                impact=60,
                effort=70,
            ))

    return findings, components, raw_data


def _extract_brands_from_response(text: str) -> str:
    """Extract capitalized words/phrases that look like brand names from an AI response.

    This is a lightweight heuristic for the evidence — it pulls out capitalized
    multi-word phrases and single capitalized words that are likely brand names.
    """
    import re

    # Find capitalized phrases (Brand Name, BrandName, BRAND)
    # Look for sequences of capitalized words
    candidates = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', text)
    # Filter out common non-brand words
    stop_words = {
        "The", "This", "That", "These", "Those", "It", "Its", "Is", "Are",
        "Was", "Were", "Be", "Been", "Being", "Have", "Has", "Had",
        "Do", "Does", "Did", "Will", "Would", "Could", "Should", "May",
        "Might", "Can", "Must", "Shall", "Some", "Many", "Most", "More",
        "When", "Where", "What", "Who", "How", "Why", "Which", "Their",
        "There", "They", "Them", "Then", "Than", "Also", "Both", "Each",
        "For", "And", "But", "Or", "Not", "No", "Yes", "If", "So",
        "In", "On", "At", "To", "Of", "By", "With", "From", "About",
        "Platform", "Service", "Services", "Business", "Businesses",
        "Company", "Companies", "Tool", "Tools", "Software", "Solution",
        "Solutions", "Feature", "Features", "User", "Users", "Price",
        "Pricing", "Plan", "Plans", "Free", "Paid", "Enterprise",
        "Best", "Top", "Good", "Great", "Better", "Best", "Popular",
        "A", "An", "As", "All", "Any",
    }
    brands = [c for c in candidates if c not in stop_words and len(c) > 2]
    # Deduplicate preserving order
    seen = set()
    unique = []
    for b in brands:
        if b not in seen:
            seen.add(b)
            unique.append(b)
    return ", ".join(unique[:10]) if unique else "No specific brands detected"


def _infer_brand_and_category(
    page: PageData, base_url: str
) -> tuple[str, list[str], str, list[str]]:
    """Infer brand name, aliases, industry category, and competitors from the homepage."""
    from urllib.parse import urlparse
    import re

    domain = urlparse(base_url).netloc.replace("www.", "")
    # Extract brand name from domain (e.g. "stripe.com" → "Stripe")
    domain_core = domain.split(".")[0]
    brand_name = domain_core.capitalize()

    # Try to get a better brand name from the title or JSON-LD
    aliases = [domain_core, domain]

    # Check JSON-LD for Organization name
    jsonld_brand = ""
    for block in page.json_ld_blocks:
        if isinstance(block.get("@type"), str) and block["@type"] in ("Organization", "Corporation", "LocalBusiness"):
            name = block.get("name", "")
            if name:
                jsonld_brand = name
                break
        elif isinstance(block.get("@type"), list):
            for t in block["@type"]:
                if t in ("Organization", "Corporation", "LocalBusiness"):
                    name = block.get("name", "")
                    if name:
                        jsonld_brand = name
                        break

    # Prefer JSON-LD Organization name (structured data is explicit)
    # Fall back to title if no JSON-LD name
    if jsonld_brand:
        brand_name = jsonld_brand
    elif page.title:
        title_clean = page.title.split("|")[0].split("—")[0].split("-")[0].strip()
        if title_clean and len(title_clean) < 30 and not title_clean.lower().startswith("welcome"):
            brand_name = title_clean

    # Add brand name aliases (lowercase, without suffixes)
    aliases.append(brand_name.lower())
    # If brand has multiple words, add abbreviation
    words = brand_name.split()
    if len(words) > 1:
        aliases.append("".join(w[0] for w in words).lower())

    # --- Infer category from page content ---
    text_lower = (page.title + " " + page.meta_description + " " + page.text[:3000]).lower()
    category = "software"  # default
    for keyword, cat in CATEGORY_INFERENCE.items():
        if keyword in text_lower:
            category = cat
            break

    # Try to get category from JSON-LD
    for block in page.json_ld_blocks:
        if isinstance(block, dict) and "description" in block:
            desc_lower = block["description"].lower()
            for keyword, cat in CATEGORY_INFERENCE.items():
                if keyword in desc_lower:
                    category = cat
                    break

    competitors = KNOWN_COMPETITORS.get(category, [])

    return brand_name, aliases, category, competitors


def _detail_for_queries(results: list[dict], brand: str) -> str:
    """Generate detail text for score components."""
    if not results:
        return "No queries in this category."

    details = []
    for r in results:
        mention = r.get("mention", {})
        mentioned = mention.get("mentioned", False)
        status = "✓ mentioned" if mentioned else "✗ not mentioned"
        details.append(f'Q: "{r["query"][:60]}..." → {status}')

    return " | ".join(details)


def _evidence_summary(results: list[dict], brand: str) -> str:
    """Generate a human-readable summary of which queries hit/missed."""
    hits = []
    misses = []
    for r in results:
        mention = r.get("mention", {})
        if mention.get("mentioned"):
            how = mention.get("how_mentioned", "")[:80]
            hits.append(f'"{r["query"][:50]}..." → {how}')
        else:
            misses.append(f'"{r["query"][:50]}..."')

    parts = []
    if hits:
        parts.append(f"Mentioned in: {'; '.join(hits[:2])}")
    if misses:
        parts.append(f"Not mentioned in: {'; '.join(misses[:2])}")
    return ". ".join(parts)


def _brand_recall_fix(brand: str, category: str, level: str) -> str:
    """Generate a fix recommendation for low/zero brand recall."""
    if level == "none":
        return (
            f"The AI model has no knowledge of {brand}. To fix this, you need to build "
            f"presence on the sources AI engines learn from during training:\n\n"
            f"1. Create/maintain a Wikipedia page (if notable enough)\n"
            f"2. Ensure a Crunchbase profile with accurate description\n"
            f"3. Get listed on review platforms (G2, Capterra, TrustRadius)\n"
            f"4. Publish on high-authority industry blogs and publications\n"
            f"5. Build backlinks from sites that appear in AI training data\n"
            f"6. Ensure your homepage clearly states what you do in the first sentence\n\n"
            f"AI models are trained on web content — the more high-quality sources "
            f"that describe {brand} accurately, the more likely AI engines will "
            f"mention you in their answers."
        )
    elif level == "low":
        return (
            f"The AI has some knowledge of {brand} but doesn't mention it consistently. "
            f"To improve recall:\n\n"
            f"1. Ensure your business is described consistently across the web\n"
            f"2. Get mentioned alongside competitors in industry comparisons and listicles\n"
            f"3. Build authority through content marketing in the {category} space\n"
            f"4. Get reviews and mentions on G2, Capterra, and industry publications\n"
            f"5. Create comparison pages on your own site ('{brand} vs [Competitor]')\n\n"
            f"The more the AI encounters {brand} in training data alongside your "
            f"competitors, the more it will mention you in relevant queries."
        )
    return "Continue building your online presence across high-authority sources."
