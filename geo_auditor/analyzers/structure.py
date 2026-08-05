"""Pillar 3 — Structured Data & Machine-Readability Analyzer.

This pillar answers: **Can machines parse and understand your content?**

AI engines don't just read text — they parse structure. schema.org JSON-LD
is the lingua franca that helps models understand what a page is about
(an article? a product? an FAQ?). Missing or malformed structured data
makes it harder for AI engines to extract and cite your content accurately.

Checks:
1. JSON-LD / schema.org validity and coverage
2. Title and meta description presence and quality
3. Semantic HTML structure (headings, paragraphs)
4. Open Graph tags
5. Canonical URLs
"""

from __future__ import annotations

from geo_auditor.models import (
    CrawlResult,
    Finding,
    PageData,
    Pillar,
    ScoreComponent,
    Severity,
)

# Valuable schema.org types for AI search visibility
VALUABLE_SCHEMA_TYPES = {
    "Organization", "Corporation", "LocalBusiness", "Website", "WebSite",
    "Article", "NewsArticle", "BlogPosting", "TechArticle",
    "FAQPage", "HowTo",
    "Product", "Service", "Offer",
    "BreadcrumbList",
    "Person", "ContactPoint",
    "WebPage", "AboutPage", "ContactPage",
}


def analyze(crawl: CrawlResult) -> tuple[list[Finding], list[ScoreComponent]]:
    """Run all structure checks. Returns findings + score components."""
    findings: list[Finding] = []
    components: list[ScoreComponent] = []

    homepage = crawl.homepage or (crawl.pages[0] if crawl.pages else None)
    if not homepage:
        return findings, [ScoreComponent(
            label="No pages to analyze", points=0, max=100,
            detail="Could not fetch any pages for analysis."
        )]

    # Aggregate across all pages for some checks, homepage-focused for others
    all_pages = [p for p in crawl.pages if p.ok]

    # --- Check 1: JSON-LD presence and validity (40 pts) ---
    f1, c1 = _check_jsonld(homepage, all_pages)
    findings.extend(f1)
    components.extend(c1)

    # --- Check 2: Title + meta description (25 pts) ---
    f2, c2 = _check_title_meta(homepage, all_pages)
    findings.extend(f2)
    components.extend(c2)

    # --- Check 3: Semantic HTML structure (15 pts) ---
    f3, c3 = _check_semantic_html(homepage, all_pages)
    findings.extend(f3)
    components.extend(c3)

    # --- Check 4: Open Graph tags (10 pts) ---
    f4, c4 = _check_open_graph(homepage)
    findings.extend(f4)
    components.extend(c4)

    # --- Check 5: Canonical URLs (10 pts) ---
    f5, c5 = _check_canonical(homepage, all_pages)
    findings.extend(f5)
    components.extend(c5)

    return findings, components


# ---------------------------------------------------------------------------
# JSON-LD checks
# ---------------------------------------------------------------------------

def _check_jsonld(
    homepage: PageData, all_pages: list[PageData]
) -> tuple[list[Finding], list[ScoreComponent]]:
    findings = []
    components = []

    # Check homepage JSON-LD
    blocks = homepage.json_ld_blocks
    valid_blocks = [b for b in blocks if not b.get("_malformed")]
    malformed_blocks = [b for b in blocks if b.get("_malformed")]

    types_found = set()
    for b in valid_blocks:
        t = b.get("@type", "")
        if isinstance(t, list):
            types_found.update(str(x) for x in t)
        elif t:
            types_found.add(str(t))

    valuable_types = types_found & VALUABLE_SCHEMA_TYPES

    if not blocks:
        # No JSON-LD at all on homepage
        components.append(ScoreComponent(
            label="No structured data (JSON-LD) on homepage",
            points=0, max=40,
            detail="No <script type='application/ld+json'> blocks found on the homepage. "
                   "This is the single biggest missed opportunity for AI visibility — "
                   "schema.org data tells AI engines exactly what your page is about."
        ))
        findings.append(Finding(
            id="no-jsonld",
            title="No structured data (schema.org JSON-LD) on homepage",
            pillar=Pillar.STRUCTURE,
            severity=Severity.CRITICAL,
            page=homepage.url,
            evidence="No <script type='application/ld+json'> tags were found in the page HTML.",
            should_be="At minimum, Organization and WebSite schema should be present.",
            fix=_generate_org_schema_fix(),
            impact=80,
            effort=20,
        ))
    elif malformed_blocks:
        # Has JSON-LD but some is malformed
        good_pts = len(valid_blocks) / max(len(blocks), 1) * 40
        components.append(ScoreComponent(
            label=f"Structured data present but {len(malformed_blocks)} block(s) malformed",
            points=good_pts, max=40,
            detail=f"{len(valid_blocks)} valid JSON-LD block(s), {len(malformed_blocks)} malformed. "
                   f"Types found: {', '.join(sorted(valuable_types)) or 'none recognized'}."
        ))
        findings.append(Finding(
            id="malformed-jsonld",
            title=f"{len(malformed_blocks)} malformed JSON-LD block(s) on homepage",
            pillar=Pillar.STRUCTURE,
            severity=Severity.WARNING,
            page=homepage.url,
            evidence=f"Found {len(malformed_blocks)} JSON-LD block(s) with invalid JSON syntax. "
                     f"Malformed JSON-LD is ignored by search engines and AI crawlers.",
            should_be="All JSON-LD should be valid, parseable JSON.",
            fix="Validate your JSON-LD at https://validator.schema.org/ and fix syntax errors. "
                "Common issues: trailing commas, unescaped quotes, missing closing braces.",
            impact=50,
            effort=20,
        ))
    else:
        # Valid JSON-LD — score by coverage
        has_org = bool(types_found & {"Organization", "Corporation", "LocalBusiness"})
        has_website = "WebSite" in types_found
        has_content = bool(types_found & {"Article", "NewsArticle", "BlogPosting", "FAQPage", "HowTo"})
        has_product = bool(types_found & {"Product", "Service", "Offer"})

        pts = 15  # base for having valid JSON-LD
        if has_org:
            pts += 10
        if has_website:
            pts += 5
        if has_content:
            pts += 10
        if has_product:
            pts += 0  # bonus tracked separately

        pts = min(pts, 40)

        components.append(ScoreComponent(
            label=f"Structured data: {len(valid_blocks)} block(s), types: {', '.join(sorted(types_found)[:5])}",
            points=pts, max=40,
            detail=f"Valid JSON-LD found. Schema types: {', '.join(sorted(valuable_types)) or 'generic'}."
        ))

        if has_org and has_website:
            findings.append(Finding(
                id="jsonld-good",
                title="Good structured data coverage on homepage",
                pillar=Pillar.STRUCTURE,
                severity=Severity.POSITIVE,
                page=homepage.url,
                evidence=f"Found valid JSON-LD with types: {', '.join(sorted(valuable_types))}.",
                should_be="", fix="",
                impact=0, effort=0,
            ))
        else:
            # Has some schema but missing key types
            missing = []
            if not has_org:
                missing.append("Organization")
            if not has_website:
                missing.append("WebSite")
            findings.append(Finding(
                id="jsonld-incomplete",
                title=f"Structured data missing key types: {', '.join(missing)}",
                pillar=Pillar.STRUCTURE,
                severity=Severity.WARNING,
                page=homepage.url,
                evidence=f"Found JSON-LD types: {', '.join(sorted(types_found))}. "
                         f"Missing high-value types: {', '.join(missing)}.",
                should_be=f"Add {', '.join(missing)} schema to help AI engines understand your business.",
                fix=_generate_org_schema_fix() if "Organization" in missing else
                    _generate_website_schema_fix() if "WebSite" in missing else
                    "Add the missing schema types using schema.org vocabulary.",
                impact=40,
                effort=20,
            ))

    return findings, components


def _generate_org_schema_fix() -> str:
    """Copy-pasteable Organization + WebSite JSON-LD template."""
    return (
        "Add this to your homepage <head> (replace the placeholders):\n\n"
        '<script type="application/ld+json">\n'
        "{\n"
        '  "@context": "https://schema.org",\n'
        '  "@type": "Organization",\n'
        '  "name": "Your Business Name",\n'
        '  "url": "https://yoursite.com",\n'
        '  "logo": "https://yoursite.com/logo.png",\n'
        '  "description": "One sentence describing what your business does.",\n'
        '  "sameAs": [\n'
        '    "https://twitter.com/yourhandle",\n'
        '    "https://www.linkedin.com/company/yourcompany",\n'
        '    "https://www.crunchbase.com/organization/yourcompany"\n'
        "  ]\n"
        "}\n"
        "</script>\n\n"
        "Tip: if you use WordPress, plugins like Yoast SEO or RankMath can "
        "generate this automatically. If you use Webflow, it's under "
        "Page Settings > Schema Markup."
    )


def _generate_website_schema_fix() -> str:
    return (
        'Add this WebSite schema (helps AI engines understand your site):\n\n'
        '<script type="application/ld+json">\n'
        "{\n"
        '  "@context": "https://schema.org",\n'
        '  "@type": "WebSite",\n'
        '  "name": "Your Site Name",\n'
        '  "url": "https://yoursite.com"\n'
        "}\n"
        "</script>"
    )


# ---------------------------------------------------------------------------
# Title + meta description
# ---------------------------------------------------------------------------

def _check_title_meta(
    homepage: PageData, all_pages: list[PageData]
) -> tuple[list[Finding], list[ScoreComponent]]:
    findings = []
    points = 0
    details = []

    # --- Title ---
    if not homepage.title:
        findings.append(Finding(
            id="missing-title",
            title="Missing <title> tag on homepage",
            pillar=Pillar.STRUCTURE,
            severity=Severity.CRITICAL,
            page=homepage.url,
            evidence="No <title> tag found in the page HTML.",
            should_be="Every page should have a descriptive <title> tag (50-60 characters).",
            fix="Add a <title> tag to your homepage:\n\n"
                "<title>Your Business Name — What You Do in 6 Words</title>",
            impact=70,
            effort=5,
        ))
        details.append("title: missing")
    elif len(homepage.title) > 65:
        findings.append(Finding(
            id="title-too-long",
            title=f"Title tag is too long ({len(homepage.title)} characters)",
            pillar=Pillar.STRUCTURE,
            severity=Severity.INFO,
            page=homepage.url,
            evidence=f'Title: "{homepage.title}" ({len(homepage.title)} characters). '
                     f'Titles over 60 characters get truncated in search results.',
            should_be="Title should be 50-60 characters.",
            fix=f'Shorten your title to 50-60 characters. Current: "{homepage.title}"',
            impact=20,
            effort=5,
        ))
        points += 10
        details.append("title: present but too long")
    else:
        points += 15
        details.append(f'title: "{homepage.title[:40]}..."')

    # --- Meta description ---
    if not homepage.meta_description:
        findings.append(Finding(
            id="missing-meta-desc",
            title="Missing meta description on homepage",
            pillar=Pillar.STRUCTURE,
            severity=Severity.WARNING,
            page=homepage.url,
            evidence="No <meta name='description'> tag found.",
            should_be="A meta description of 120-160 characters summarizing the page.",
            fix="Add a meta description:\n\n"
                '<meta name="description" content="Your one-sentence value proposition. '
                'What you do, who you serve, and why it matters (120-160 characters)">',
            impact=50,
            effort=5,
        ))
        details.append("meta description: missing")
    elif len(homepage.meta_description) > 170:
        findings.append(Finding(
            id="meta-desc-too-long",
            title=f"Meta description too long ({len(homepage.meta_description)} chars)",
            pillar=Pillar.STRUCTURE,
            severity=Severity.INFO,
            page=homepage.url,
            evidence=f'Description: "{homepage.meta_description[:80]}..." '
                     f'({len(homepage.meta_description)} characters). '
                     f'Descriptions over 160 characters get truncated.',
            should_be="120-160 characters.",
            fix="Shorten your meta description to 120-160 characters.",
            impact=15,
            effort=5,
        ))
        points += 5
        details.append("meta description: present but too long")
    else:
        points += 10
        details.append("meta description: present")

    components = [ScoreComponent(
        label="; ".join(details),
        points=points, max=25,
        detail="; ".join(details)
    )]

    return findings, components


# ---------------------------------------------------------------------------
# Semantic HTML
# ---------------------------------------------------------------------------

def _check_semantic_html(
    homepage: PageData, all_pages: list[PageData]
) -> tuple[list[Finding], list[ScoreComponent]]:
    findings = []
    points = 0

    has_h1 = len(homepage.h1_tags) >= 1
    has_h2 = len(homepage.h2_tags) >= 2
    has_paragraphs = homepage.paragraph_count >= 3

    if has_h1:
        points += 6
    else:
        findings.append(Finding(
            id="missing-h1",
            title="Missing <h1> heading on homepage",
            pillar=Pillar.STRUCTURE,
            severity=Severity.WARNING,
            page=homepage.url,
            evidence="No <h1> tag found on the homepage. The H1 is the main heading "
                     "that tells both humans and machines what the page is about.",
            should_be="One clear <h1> tag per page.",
            fix="Add an <h1> tag with your primary topic or value proposition:\n\n"
                "<h1>Your Main Headline — What You Do</h1>",
            impact=40,
            effort=5,
        ))

    if has_h2:
        points += 5
    else:
        findings.append(Finding(
            id="few-h2",
            title="Few or no <h2> subheadings",
            pillar=Pillar.STRUCTURE,
            severity=Severity.INFO,
            page=homepage.url,
            evidence=f"Found {len(homepage.h2_tags)} H2 tags. Subheadings help structure "
                     "content for readability and machine understanding.",
            should_be="Use H2 subheadings to break up content sections.",
            fix="Add <h2> subheadings to organize your content into clear sections.",
            impact=25,
            effort=15,
        ))

    if has_paragraphs:
        points += 4
    else:
        findings.append(Finding(
            id="thin-content",
            title="Very little text content on homepage",
            pillar=Pillar.STRUCTURE,
            severity=Severity.WARNING,
            page=homepage.url,
            evidence=f"Only {homepage.paragraph_count} paragraph(s) found. "
                     f"Word count: {homepage.word_count}. AI engines need text to extract and cite.",
            should_be="Substantive text content (300+ words) that answers visitor questions.",
            fix="Add descriptive text content that explains what you do, who you serve, "
                "and answers common questions. Aim for at least 300 words of relevant content.",
            impact=60,
            effort=40,
        ))

    components = [ScoreComponent(
        label=f"H1: {'yes' if has_h1 else 'no'}, H2 count: {len(homepage.h2_tags)}, "
              f"paragraphs: {homepage.paragraph_count}, words: {homepage.word_count}",
        points=points, max=15,
        detail=f"H1: {'present' if has_h1 else 'missing'}, "
               f"H2 tags: {len(homepage.h2_tags)}, "
               f"paragraphs: {homepage.paragraph_count}, "
               f"word count: {homepage.word_count}"
    )]

    return findings, components


# ---------------------------------------------------------------------------
# Open Graph
# ---------------------------------------------------------------------------

def _check_open_graph(homepage: PageData) -> tuple[list[Finding], list[ScoreComponent]]:
    findings = []
    has_og_title = bool(homepage.og_title)
    has_og_desc = bool(homepage.og_description)

    points = 0
    if has_og_title:
        points += 5
    if has_og_desc:
        points += 5

    if not has_og_title and not has_og_desc:
        findings.append(Finding(
            id="missing-og",
            title="Missing Open Graph tags",
            pillar=Pillar.STRUCTURE,
            severity=Severity.INFO,
            page=homepage.url,
            evidence="No og:title or og:description tags found. Open Graph tags "
                     "control how your page appears when shared on social media and "
                     "some AI platforms.",
            should_be="og:title, og:description, and og:image tags.",
            fix="Add Open Graph tags:\n\n"
                '<meta property="og:title" content="Your Title">\n'
                '<meta property="og:description" content="Your description">\n'
                '<meta property="og:image" content="https://yoursite.com/og-image.png">\n'
                '<meta property="og:url" content="https://yoursite.com">',
            impact=20,
            effort=10,
        ))

    components = [ScoreComponent(
        label=f"Open Graph: title={'yes' if has_og_title else 'no'}, "
              f"desc={'yes' if has_og_desc else 'no'}",
        points=points, max=10,
        detail=f"og:title: {'present' if has_og_title else 'missing'}, "
               f"og:description: {'present' if has_og_desc else 'missing'}"
    )]

    return findings, components


# ---------------------------------------------------------------------------
# Canonical
# ---------------------------------------------------------------------------

def _check_canonical(
    homepage: PageData, all_pages: list[PageData]
) -> tuple[list[Finding], list[ScoreComponent]]:
    findings = []
    points = 0
    detail = ""

    if homepage.canonical:
        points = 10
        detail = f'canonical: "{homepage.canonical}"'
        # Check it points to itself (not a common mistake)
        from urllib.parse import urlparse
        canon_host = urlparse(homepage.canonical).netloc.replace("www.", "")
        page_host = urlparse(homepage.url).netloc.replace("www.", "")
        if canon_host and page_host and canon_host != page_host:
            points = 3
            findings.append(Finding(
                id="canonical-mismatch",
                title="Canonical URL points to a different domain",
                pillar=Pillar.STRUCTURE,
                severity=Severity.WARNING,
                page=homepage.url,
                evidence=f'Canonical tag points to "{homepage.canonical}" but the page '
                         f'is served from a different domain. This tells search engines '
                         f'the "real" version lives elsewhere.',
                should_be="Canonical should point to the page's own URL (self-referencing).",
                fix=f'Change the canonical to point to this page\'s own URL:\n\n'
                    f'<link rel="canonical" href="{homepage.url}">',
                impact=50,
                effort=5,
            ))
    else:
        findings.append(Finding(
            id="missing-canonical",
            title="Missing canonical URL tag",
            pillar=Pillar.STRUCTURE,
            severity=Severity.INFO,
            page=homepage.url,
            evidence="No <link rel='canonical'> tag found. Canonical tags prevent "
                     "duplicate content issues by telling search engines which URL "
                     "is the 'master' version of a page.",
            should_be="A self-referencing canonical tag.",
            fix=f'Add a canonical tag:\n\n'
                f'<link rel="canonical" href="{homepage.url}">',
            impact=20,
            effort=5,
        ))
        detail = "canonical: missing"

    components = [ScoreComponent(
        label=detail,
        points=points, max=10,
        detail=detail
    )]

    return findings, components
