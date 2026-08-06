"""Site crawler — fetches robots.txt, sitemap.xml, and key pages.

This is the foundation for all three analyzers. It fetches:
1. robots.txt  → parsed for AI bot rules
2. sitemap.xml → parsed for URL inventory
3. Key pages   → homepage + a few important linked pages / sitemap entries

Never hand-rolls HTML parsing — uses BeautifulSoup + lxml.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from geo_auditor.models import CrawlResult, PageData, RobotsData, SitemapData

logger = logging.getLogger(__name__)

# The AI bots we care about for GEO.
AI_BOTS = [
    "GPTBot",  # OpenAI / ChatGPT
    "OAI-SearchBot",  # OpenAI Search
    "PerplexityBot",  # Perplexity
    "Perplexity-User",
    "ClaudeBot",  # Anthropic / Claude
    "anthropic-ai",
    "CCBot",  # Common Crawl (feeds many LLMs)
    "Google-Extended",  # Google AI Overviews / Gemini
]

USER_AGENT = (
    "Mozilla/5.0 (compatible; GEOAuditor/0.1; +https://github.com/geo-auditor) "
    "GEOAuditor/0.1"
)

DEFAULT_TIMEOUT = 20.0
MAX_PAGES = 5  # how many pages to crawl per site
MAX_TEXT_LENGTH = 50000  # truncate extracted text to keep LLM calls reasonable


def normalize_url(raw: str) -> str:
    """Ensure a URL has a scheme and no trailing slash on the path."""
    raw = raw.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    # rebuild cleanly
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _is_private_ip(hostname: str) -> bool:
    """Block internal, private, and link-local IP ranges (SSRF guard)."""
    import ipaddress

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        if hostname in ("localhost", "0.0.0.0", "::1", "::"):
            return True
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def assert_public_url(url: str) -> None:
    """Reject non-public URLs to prevent SSRF attacks.

    Blocks: private IPs, localhost, loopback, link-local, cloud metadata (169.254.x.x).
    Raises ValueError if the URL points to a non-public address.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if not hostname:
        raise ValueError(f"Invalid URL: no hostname in '{url}'")
    if _is_private_ip(hostname):
        raise ValueError(
            f"URL rejected for security: '{hostname}' is not a public address. "
            f"Private/internal IPs and localhost are blocked."
        )


def get_base_url(url: str) -> str:
    """Return the scheme + host (root)."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------

# simple robots.txt parser — we only need User-agent + Allow/Disallow + Sitemap
def parse_robots_txt(raw_text: str) -> RobotsData:
    """Parse robots.txt for AI bot rules and sitemap declarations.

    Handles grouped user-agent rules (e.g. `User-agent: *` applying to all).
    Returns bot_rules: {bot_name: True (allowed) | False (blocked) | None (not mentioned)}.
    """
    data = RobotsData(raw=raw_text, fetch_ok=True)
    lines = raw_text.splitlines()

    # Parse into rule groups: list of (agents, rules)
    # A group starts with one or more User-agent lines, followed by rules.
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    current_agents: list[str] = []
    current_rules: list[tuple[str, str]] = []
    started_group = False

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if ":" not in line:
            continue
        field_name, _, value = line.partition(":")
        field_name = field_name.strip().lower()
        # Strip inline comments (# comment)
        if "#" in value:
            value = value[:value.index("#")]
        value = value.strip()

        if field_name == "user-agent":
            if started_group and current_rules:
                # previous group had rules — save it
                groups.append((current_agents, current_rules))
                current_agents = []
                current_rules = []
                started_group = False
            current_agents.append(value)
        elif field_name in ("allow", "disallow"):
            if current_agents:
                started_group = True
                current_rules.append((field_name, value))
        elif field_name == "sitemap":
            if value:
                data.sitemap_urls.append(value)

    # flush last group
    if current_agents and current_rules:
        groups.append((current_agents, current_rules))

    # Now determine each AI bot's status
    for bot in AI_BOTS:
        allowed = _bot_allowed(bot, groups)
        data.bot_rules[bot] = allowed

    return data


def _bot_allowed(bot: str, groups: list[tuple[list[str], list[str]]]) -> bool | None:
    """Determine if a bot is allowed.

    Returns True (allowed), False (blocked), or None (not mentioned).
    Priority: exact bot match > wildcard (*) > not mentioned (default allow).
    """
    bot_lower = bot.lower()

    # Check for exact match group first
    for agents, rules in groups:
        if any(a.lower() == bot_lower for a in agents):
            return _evaluate_rules(rules)

    # Then wildcard
    for agents, rules in groups:
        if any(a.lower() == "*" for a in agents):
            return _evaluate_rules(rules)

    # Not mentioned → allowed by default
    return None


def _evaluate_rules(rules: list[tuple[str, str]]) -> bool | None:
    """Evaluate allow/disallow rules. Most specific wins; disallow: / blocks all."""
    has_disallow_root = False
    has_allow = False

    for rule_type, path in rules:
        if rule_type == "disallow" and (path == "/" or path == ""):
            if path == "/":
                has_disallow_root = True
        elif rule_type == "disallow" and path:
            # specific disallow — not a full block
            pass
        elif rule_type == "allow":
            has_allow = True

    if has_disallow_root:
        return False
    return True  # allowed if no root disallow


# ---------------------------------------------------------------------------
# sitemap.xml
# ---------------------------------------------------------------------------

def parse_sitemap(raw_text: str) -> SitemapData:
    """Parse sitemap.xml for URL count and type (index vs URL set)."""
    data = SitemapData(fetch_ok=True)
    try:
        soup = BeautifulSoup(raw_text, "xml")
    except Exception:
        soup = BeautifulSoup(raw_text, "lxml-xml")

    # Detect sitemap index (contains <sitemap> elements)
    sitemap_tags = soup.find_all("sitemap")
    url_tags = soup.find_all("url")

    if sitemap_tags:
        data.is_index = True
        data.child_sitemap_count = len(sitemap_tags)
        for sm in sitemap_tags:
            loc = sm.find("loc")
            if loc and loc.text:
                data.urls.append(loc.text.strip())
        data.url_count = len(data.urls)
    elif url_tags:
        for u in url_tags:
            loc = u.find("loc")
            if loc and loc.text:
                data.urls.append(loc.text.strip())
        data.url_count = len(data.urls)

    return data


# ---------------------------------------------------------------------------
# Page fetch + text extraction
# ---------------------------------------------------------------------------

def extract_page_data(html: str, url: str, status_code: int, load_time_ms: float) -> PageData:
    """Extract structured data from raw HTML using BeautifulSoup."""
    soup = BeautifulSoup(html, "lxml")

    # --- Meta tags ---
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    meta_desc = ""
    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    if meta_desc_tag:
        meta_desc = meta_desc_tag.get("content", "").strip()

    meta_robots = ""
    meta_robots_tag = soup.find("meta", attrs={"name": "robots"})
    if meta_robots_tag:
        meta_robots = meta_robots_tag.get("content", "").strip()

    canonical = ""
    canonical_tag = soup.find("link", rel="canonical")
    if canonical_tag:
        canonical = canonical_tag.get("href", "").strip()

    og_title = ""
    og_title_tag = soup.find("meta", attrs={"property": "og:title"})
    if og_title_tag:
        og_title = og_title_tag.get("content", "").strip()

    og_desc = ""
    og_desc_tag = soup.find("meta", attrs={"property": "og:description"})
    if og_desc_tag:
        og_desc = og_desc_tag.get("content", "").strip()

    # --- JSON-LD blocks ---
    json_ld_blocks: list[dict] = []
    for script in soup.find_all("script", type="application/ld+json"):
        import json

        raw_json = script.string or script.get_text()
        if not raw_json:
            continue
        raw_json = raw_json.strip()
        try:
            parsed = json.loads(raw_json)
            # could be a list or single object
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        json_ld_blocks.append(item)
            elif isinstance(parsed, dict):
                # could be @graph
                if "@graph" in parsed and isinstance(parsed["@graph"], list):
                    for item in parsed["@graph"]:
                        if isinstance(item, dict):
                            json_ld_blocks.append(item)
                else:
                    json_ld_blocks.append(parsed)
        except (json.JSONDecodeError, ValueError):
            # malformed JSON-LD — record the raw for evidence
            json_ld_blocks.append({"_malformed": True, "_raw": raw_json[:500]})

    # --- Headings ---
    h1_tags = [h.get_text(strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]
    h2_tags = [h.get_text(strip=True) for h in soup.find_all("h2") if h.get_text(strip=True)]

    # --- Extract visible text ---
    # Remove script, style, nav, footer, header noise
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    # Get main content text — prefer <main>, <article>, then <body>
    main = soup.find("main") or soup.find("article") or soup.find("body")
    if main:
        text = main.get_text(separator=" ", strip=True)
    else:
        text = soup.get_text(separator=" ", strip=True)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH] + "..."

    word_count = len(text.split())

    # Check for FAQ schema
    has_faq_schema = any(
        str(b.get("@type", "")).lower() in ("faqpage", "faq")
        or (isinstance(b.get("@type"), list) and any(
            str(t).lower() in ("faqpage", "faq") for t in b["@type"]
        ))
        for b in json_ld_blocks
    )

    # Count paragraphs in main content
    paragraph_count = len(main.find_all("p")) if main else 0

    # --- Content signals (quick heuristic extraction) ---
    # Statistics: numbers with % or data-like patterns
    stats_count = len(re.findall(r"\b\d+([.,]\d+)?\s*%|\$\s*\d|\b\d{4}\b|\b\d+([.,]\d+)?x\b", text))

    # Definition patterns: "X is a..." / "X means..." / "X refers to..."
    has_definition = bool(re.search(
        r"\b(is|are|means|refers to|is defined as|describes)\b",
        text[:2000],  # check first 2000 chars where intro typically lives
    ))

    # Citations: "according to", "source:", quotation marks with attribution
    has_citations = bool(re.search(
        r"(according to|source:|as reported by|study by|research from|et al\.)",
        text, re.IGNORECASE,
    ))

    return PageData(
        url=url,
        status_code=status_code,
        load_time_ms=load_time_ms,
        html=html[:50000] if len(html) > 50000 else html,  # keep for deep parsing
        text=text,
        title=title,
        meta_description=meta_desc,
        meta_robots=meta_robots,
        canonical=canonical,
        og_title=og_title,
        og_description=og_desc,
        json_ld_blocks=json_ld_blocks,
        h1_tags=h1_tags,
        h2_tags=h2_tags,
        word_count=word_count,
        has_faq_schema=has_faq_schema,
        stats_count=stats_count,
        has_definition=has_definition,
        has_citations=has_citations,
        paragraph_count=paragraph_count,
    )


# ---------------------------------------------------------------------------
# Main crawl orchestrator
# ---------------------------------------------------------------------------

async def crawl_site(url: str, max_pages: int = MAX_PAGES) -> CrawlResult:
    """Crawl a site: robots.txt, sitemap, and key pages.

    Returns a CrawlResult with all data the analyzers need.
    """
    url = normalize_url(url)
    assert_public_url(url)  # SSRF guard — block private/internal addresses
    base_url = get_base_url(url)
    result = CrawlResult(base_url=base_url)

    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(DEFAULT_TIMEOUT),
        headers=headers,
        follow_redirects=True,
        verify=False,
    ) as client:
        # --- 1. Fetch robots.txt ---
        robots_url = urljoin(base_url, "/robots.txt")
        try:
            resp = await client.get(robots_url)
            if resp.status_code == 200:
                result.robots = parse_robots_txt(resp.text)
                result.robots.status_code = resp.status_code
            else:
                result.robots.status_code = resp.status_code
                result.robots.fetch_ok = False
        except Exception as e:
            logger.warning(f"Failed to fetch robots.txt: {e}")
            result.robots.fetch_ok = False
            result.robots.status_code = None

        # --- 2. Fetch sitemap.xml ---
        sitemap_url = urljoin(base_url, "/sitemap.xml")
        try:
            resp = await client.get(sitemap_url)
            if resp.status_code == 200:
                result.sitemap = parse_sitemap(resp.text)
                result.sitemap.status_code = resp.status_code
            else:
                result.sitemap.status_code = resp.status_code
        except Exception as e:
            logger.warning(f"Failed to fetch sitemap.xml: {e}")
            result.sitemap.status_code = None

        # If sitemap is an index, try to fetch the first child sitemap for URLs
        if result.sitemap.is_index and result.sitemap.urls:
            for child_url in result.sitemap.urls[:3]:
                try:
                    resp = await client.get(child_url)
                    if child_url == sitemap_url:  # safety: avoid infinite loop
                        continue
                    if resp.status_code == 200:
                        child_data = parse_sitemap(resp.text)
                        result.sitemap.urls.extend(child_data.urls)
                        result.sitemap.url_count += child_data.url_count
                        break
                except Exception:
                    continue
            # Deduplicate
            result.sitemap.urls = list(dict.fromkeys(result.sitemap.urls))
            result.sitemap.url_count = len(result.sitemap.urls)

        # --- 3. Determine pages to crawl ---
        pages_to_crawl = _select_pages(url, base_url, result)

        # --- 4. Crawl pages concurrently ---
        tasks = [_fetch_page(client, page_url) for page_url in pages_to_crawl]
        pages = await asyncio.gather(*tasks, return_exceptions=True)

        for page in pages:
            if isinstance(page, PageData):
                result.pages.append(page)
            elif isinstance(page, Exception):
                logger.warning(f"Page fetch failed: {page}")
                # add a stub so the analyzer knows it failed
                result.pages.append(PageData(url="", error=str(page)))

        # Identify homepage
        for p in result.pages:
            if _same_path(p.url, url) or p.url == url:
                p.url = url
                result.homepage = p
                break
        if not result.homepage and result.pages:
            result.homepage = result.pages[0]
            result.homepage.url = url

    return result


def _select_pages(url: str, base_url: str, result: CrawlResult) -> list[str]:
    """Choose which pages to crawl: homepage + key pages from sitemap/links."""
    pages = [url]

    # Try to get internal pages from sitemap
    sitemap_pages = [
        u for u in result.sitemap.urls
        if urlparse(u).netloc == urlparse(base_url).netloc
        and not _same_path(u, url)  # skip homepage
        and not any(ext in u.lower() for ext in [".jpg", ".png", ".pdf", ".css", ".js"])
    ]

    # Prioritize pages that look like content pages
    priority_patterns = ["/blog/", "/about", "/pricing", "/faq", "/services", "/product"]
    prioritized = []
    for pattern in priority_patterns:
        for sm_url in sitemap_pages:
            if pattern in sm_url.lower() and sm_url not in prioritized:
                prioritized.append(sm_url)
    # Fill remaining from sitemap
    for sm_url in sitemap_pages:
        if sm_url not in prioritized:
            prioritized.append(sm_url)

    for p in prioritized[: MAX_PAGES - 1]:
        if p not in pages:
            pages.append(p)

    return pages[:MAX_PAGES]


def _same_path(url1: str, url2: str) -> bool:
    """Check if two URLs point to the same path."""
    p1 = urlparse(url1)
    p2 = urlparse(url2)
    return p1.netloc == p2.netloc and (p1.path.rstrip("/") or "/") == (p2.path.rstrip("/") or "/")


async def _fetch_page(client: httpx.AsyncClient, url: str) -> PageData:
    """Fetch a single page and extract data."""
    start = time.monotonic()
    try:
        resp = await client.get(url)
        load_time_ms = (time.monotonic() - start) * 1000
        if resp.status_code == 200:
            return extract_page_data(resp.text, url, resp.status_code, round(load_time_ms, 0))
        else:
            return PageData(url=url, status_code=resp.status_code, load_time_ms=round(load_time_ms, 0),
                            error=f"HTTP {resp.status_code}")
    except Exception as e:
        load_time_ms = (time.monotonic() - start) * 1000
        return PageData(url=url, load_time_ms=round(load_time_ms, 0), error=str(e))
