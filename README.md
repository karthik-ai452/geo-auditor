# GEO Auditor

**See how visible your business is in AI search.**

People are moving from Google to AI — ChatGPT, Perplexity, Claude, Google AI Overviews. A business can rank #1 on Google and be completely invisible inside AI answers, because AI engines choose their sources by a different set of rules. This tool checks whether your site follows those rules.

Enter a URL. Get an audit report with:
1. **A visibility score** — with every point visible in the breakdown
2. **What's broken** — each finding names the exact page, shows what was found, and shows what it should be
3. **What to fix, in what order** — prioritized by impact × effort, with copy-pasteable fixes

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set up your LLM key (needed for content answerability scoring)
export OPENAI_API_KEY="your-key"
export OPENAI_BASE_URL="https://your-llm-gateway.com"

# Run an audit via CLI
python -m geo_auditor audit stripe.com

# Or run the web app
python -m uvicorn geo_auditor.web.app:app --host 0.0.0.0 --port 8000
# Then open http://localhost:8000
```

The CLI saves reports to `reports/` as self-contained HTML files (printable to PDF) and JSON.

---

## What This Tool Checks — and Why

GEO (Generative Engine Optimization) is a new field (~2 years old). Nobody has agreed on what an audit should contain. Here's what I chose to check, what I deliberately cut, and why.

### The Four Pillars

#### Pillar 1: AI Crawlability (20%) — *Can AI engines even reach you?*

**What it checks:**
- `robots.txt` parsed per-bot for 8 AI crawlers: GPTBot (OpenAI/ChatGPT), OAI-SearchBot, PerplexityBot, Perplexity-User, ClaudeBot (Anthropic), anthropic-ai, CCBot (Common Crawl — feeds many LLMs), Google-Extended (Google AI Overviews/Gemini)
- `sitemap.xml` presence, validity, and URL count
- Per-page `meta robots` / `noindex` directives
- HTTP reachability and load time

**Why this matters:** If GPTBot or ClaudeBot is blocked in robots.txt, your content is literally invisible to that engine — no matter how good it is. This is the #1 silent killer of AI visibility, and most businesses don't even know they're doing it (often an overzealous "block all bots" security plugin).

#### Pillar 2: Content Answerability (25%) — *Does your content answer questions the way AI engines extract and cite?*

**What it checks:**
- **LLM-as-judge**: An LLM evaluates the content across 5 dimensions (direct answers, statistical richness, citation quality, structure clarity, conversational match)
- **Rule-based signals**: statistic density, definition/answer patterns, citation patterns, FAQ schema presence

**Why this matters:** The GEO research benchmark (Aggarwal et al., 2023) showed that specific content-level strategies lift citation rates by 30-40% (adding statistics, citing sources, writing direct answers).

#### Pillar 3: Structured Data & Machine-Readability (15%) — *Can machines parse and understand your content?*

**What it checks:**
- `schema.org` JSON-LD validity and type coverage
- Title and meta description presence and length
- Semantic HTML structure (H1, H2, paragraphs, word count)
- Open Graph tags, canonical URLs

#### Pillar 4: AI Brand Recall (25%) — *Do AI engines actually know and mention your business?*

**What it checks:**
The previous three pillars check *preconditions* — can bots reach you, is your content answerable, is your data parseable. This pillar checks the *outcome*: we send real questions to an AI model and measure whether it actually mentions the target business.

**What we test (live retrieval pathway):**
1. **Category visibility** — when asked about your industry ("What are the best payment processing platforms?"), does your brand come up unprompted?
2. **Comparison visibility** — when asked to compare tools in your space ("Can you compare the top payment processing platforms?"), does your brand appear alongside competitors?

**What we deliberately don't test:**
We do NOT test training data knowledge (asking "What is [brand]?" to see if the model has memorized your company). The probability of appearing in a specific model's training data is very low for most businesses — training corpora are vast and arbitrary, and a business has no practical way to influence whether it ends up memorized. More importantly, it's not actionable: a business cannot realistically optimize "get into the next training run." Category and comparison queries, by contrast, test the live retrieval pathway that AI engines actually use when serving answers, and the results are influenceable through content, authority, and presence.

**How it works:**
1. Infer the brand name and industry category from the homepage (title, JSON-LD, content)
2. Generate 3 relevant queries (2 category, 1 comparison)
3. Send each query to an LLM with search enabled (`enable_search: true`)
4. Use a second LLM call to check whether the brand is mentioned, how, in what context, citation rank, exact sentence, and selection rate
5. Score based on mention rate across query types (category: 55%, comparison: 45%)

**Honest limitation:** This tests one LLM's behavior. Different AI engines (ChatGPT, Perplexity, Claude) use different models with different retrieval pipelines, so recall may vary across engines. The score is a directional indicator, not a guarantee of visibility on any specific platform.

#### Pillar 5: AI Visibility & Competitive Intelligence (25%) — *The core pillar. If the AI can't find you, describe you wrong, or your competitor out-covers you — everything else is wasted effort.*

Five sub-checks, each worth 20 points:

**Sub-check 1: Platform Coverage (20 pts)**
Does your brand exist on the 7 platforms AI engines search first? AI engines deploy sub-agents that search specific source platforms before broadening to the wider web:
- **Gemini** searches: YouTube, Wikipedia, Reddit, Instagram
- **ChatGPT** searches: Forbes, big blogs, review sites like G2 and Capterra
- **Perplexity** searches: top SEO-ranked sites

| Platform | How we check | Used by |
|----------|-------------|---------|
| Wikipedia | MediaWiki API search for brand name | Gemini, Google AI Overviews |
| GitHub | Organization page existence | ChatGPT, Perplexity, Claude |
| YouTube | Channel page content verification | Gemini |
| Reddit | JSON search API for brand mentions | Gemini, Google AI Overviews |
| Crunchbase | Organization profile page | ChatGPT, Perplexity |
| G2 | Product review page | ChatGPT, Perplexity |
| LinkedIn | Company page content verification | ChatGPT, Perplexity, Google AI Overviews |

**Sub-check 2: Competitive Coverage Gap (20 pts)**
Where do competitors have platform presence that you don't? If a competitor is on YouTube and G2 but you're only on G2, they win that surface — the AI will recommend them, not you. We check top 3 competitors across all 7 platforms and build a coverage map showing gaps vs advantages.

**Sub-check 3: AI Positioning Accuracy (20 pts)**
Does the AI describe you the way you describe yourself? If you sell "premium soaps" but the AI says "affordable soaps," it will recommend you for the wrong queries. We compare your homepage self-description against how the AI describes you in its responses using an LLM-powered mismatch detector (price, audience, category, features, tone).

**Sub-check 4: Share of Voice (20 pts)**
Across category and comparison queries, does the AI mention you more or less often than competitors? Share of voice = target mentions / total mentions. 50%+ earns full points.

**Sub-check 5: Vector Search Inclusion (20 pts)**
Will AI vector/semantic search actually retrieve your content? We compute real embedding similarity (OpenAI embeddings API + cosine similarity) between your homepage content and typical category queries. Low similarity means your content won't surface in vector search even if it's crawlable.

**Honest limitations:** Some platforms (Reddit, Crunchbase, G2) block automated requests. When blocked (403), we report "blocked — cannot verify" rather than false negatives. Vector search depends on the embedding model being available on the LLM gateway.

---

### What I Deliberately Cut — and Why

| Check | Why I cut it |
|-------|-------------|
| **Backlink / Domain Authority analysis** | Requires a paid SEO API (Ahrefs, Moz, Semrush). Would have to be mocked, and I won't present mock data as real. |
| **Live citation tracking** (actually querying ChatGPT/Perplexity for brand mentions) | Needs a query corpus + engine APIs. AI engines don't offer reliable citation APIs. Would be faked. |
| **Broad web mention counts** | Needs a search API (Google Custom Search, Bing API). Adds dependency for marginal value. |
| **Page speed / Core Web Vitals** | Lighthouse/CWV is well-covered by existing tools (PageSpeed Insights). Not a GEO-specific signal. |
| **Auth, billing, user accounts, database** | The brief explicitly says to skip these. |
| **Multi-page deep crawl (50+ pages)** | The brief says "make it work well for 3-5 real businesses." A focused crawl of 5 key pages is faster and sufficient for an audit. |

---

## What's Real vs. Mocked

**Everything is real.** No mocked data, no fake results.

- ✅ robots.txt fetching and parsing — real HTTP requests
- ✅ sitemap.xml fetching and parsing — real HTTP requests
- ✅ Page crawling and text extraction — real HTTP requests + BeautifulSoup parsing
- ✅ JSON-LD/schema.org extraction — real HTML parsing
- ✅ Content signal extraction (statistics, definitions, citations) — real regex analysis
- ✅ LLM content judge — real LLM calls (if `OPENAI_API_KEY` is set)
- ✅ Brand Recall — real LLM queries with search enabled and brand mention detection
- ✅ Source Platform Presence — real HTTP requests to 7 platforms (Wikipedia, GitHub, YouTube, Reddit, Crunchbase, G2, LinkedIn)
- ✅ Competitive Coverage Gap — real HTTP checks of top 3 competitors across 7 platforms
- ✅ AI Positioning Accuracy — real LLM analysis comparing self-description vs AI description
- ✅ Share of Voice — real LLM competitor mention analysis across brand recall query responses
- ✅ Vector Search Inclusion — real OpenAI embeddings API with cosine similarity computation
- ✅ SSRF guard — blocks private IPs, localhost, and cloud metadata endpoints
- ✅ Scoring — real computation, fully transparent
- ✅ Report generation — real HTML output from real data

**Graceful degradation:** If the LLM gateway is unavailable, the content answerability pillar falls back to rule-based scoring only (statistics, definitions, citations, FAQ schema). This is clearly labelled in the report as "rule-based (LLM unavailable)."

---

## How to Run It

### CLI

```bash
# Full audit with LLM judge
python -m geo_auditor audit example.com

# Skip LLM, use rule-based scoring only
python -m geo_auditor audit example.com --no-llm

# Custom output directory
python -m geo_auditor audit example.com -o my_reports/
```

### Web App

```bash
python -m uvicorn geo_auditor.web.app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`, enter a URL, and get an in-browser report.

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | For Pillars 2, 4 & 5 | API key for the LLM judge, brand recall, positioning accuracy, share of voice, and vector search. Without it, rule-based scoring is used and brand recall/vector search score 0. |
| `OPENAI_BASE_URL` | For Pillars 2, 4 & 5 | Base URL for the OpenAI-compatible gateway. |
| `APP_HOST` | No (default: 0.0.0.0) | Web app bind host. |
| `APP_PORT` | No (default: 8000) | Web app bind port. |

### Run the Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

88 tests covering scoring math, robots.txt parsing, sitemap parsing, HTML extraction, analyzer logic, brand recall, and all 5 source presence sub-checks (platform coverage, competitive gap, positioning accuracy, share of voice, vector search inclusion).

---

## Sample Reports

Three real audit reports are included in `reports/official/`:

| Site | Score | Grade | What it shows |
|------|-------|-------|---------------|
| **stripe.com** | 70.0/100 | Moderate | 100% brand recall (AI mentions Stripe in category/comparison queries), good structure, crawlable. Platform coverage 3/7 (GitHub, LinkedIn, YouTube). Share of voice 33% (PayPal and Square also mentioned). Positioning accuracy 72/100. |
| **notion.so** | 71.4/100 | Moderate | 100% brand recall and perfect crawlability, strong share of voice (100% — dominates). Platform coverage 3/7. Positioning accuracy 72/100. Weaker structured data. |
| **example.com** | 12.7/100 | Critical | Fails across all pillars — no robots.txt, no sitemap, no structured data, minimal content, 0/3 brand recall, 0/7 platform presence, 0% share of voice. |

These were chosen to demonstrate the tool differentiates between sites with different GEO maturity levels.

---

## How the Score Works

The overall score is a weighted average of five pillars:

```
Overall = Crawlability × 0.15 + Answerability × 0.20 + Structure × 0.15 + Brand Recall × 0.25 + Source Presence × 0.25
```

**Every sub-score shows the exact math.** In the report, expand any pillar to see each component: what it checked, what it found, and how many points it earned out of the maximum. No magic 73/100 — you can trace every point.

### Grades

| Score | Grade | Meaning |
|-------|-------|---------|
| 80-100 | Strong | Well-optimized for AI search |
| 60-79 | Moderate | Foundation in place, key gaps remain |
| 40-59 | Weak | Likely invisible or poorly represented |
| 0-39 | Critical | Almost certainly invisible in AI search |

---

## Tech Stack

- **Python 3.13** — chosen for rich text processing ecosystem and async HTTP
- **httpx** — async HTTP client for fast multi-page crawling
- **BeautifulSoup + lxml** — HTML parsing (never hand-rolled, per the brief)
- **jsonschema** — JSON-LD validation
- **Jinja2** — report template rendering
- **FastAPI + Uvicorn** — web app
- **OpenAI-compatible LLM gateway** — content answerability judge, brand recall, positioning accuracy, share of voice, embeddings
- **ThreadPoolExecutor** — parallel source platform checks
- **pytest** — unit tests

---

## Architecture

```
URL input
  → Crawler: fetch robots.txt, sitemap.xml, 5 key pages
    → extract text + metadata per page (BeautifulSoup)
  → Analyzers (run on crawled data):
    → Crawlability (robots/sitemap/meta robots)
    → Structure (JSON-LD, semantic HTML, meta tags)
    → Answerability (LLM judge + rule-based signals)
    → Brand Recall (real LLM brand mention testing with search enabled)
    → AI Visibility & Competitive Intelligence (5 sub-checks: platform coverage, competitive gap, positioning accuracy, share of voice, vector search)
  → Scoring engine: findings → pillar scores → overall (math visible)
  → Report renderer: Jinja2 → self-contained HTML
```

---

## What I'd Build Next (With Another Week)

1. **Live citation tracking** — Actually query AI engines with brand-related questions and measure citation frequency. This is the holy grail of GEO but requires either engine APIs or a proxy-based approach.

2. **Multi-page deep analysis** — Crawl 20-50 pages and analyze content patterns across the whole site, not just the homepage.

3. **Competitor comparison** — Audit a competitor alongside and show the gap. "Your competitor scores 72, you score 45 — here's what they do that you don't."

4. **Historical tracking** — Re-audit over time and show trend lines. "Your score went from 45 to 62 after adding FAQ schema."

5. **Backlink and authority signals** — Integrate with a SEO API (Ahrefs/Moz) for domain authority, backlink profile, and referral traffic. These correlate with AI visibility even if they aren't GEO-specific.

6. **Content rewriting suggestions** — Instead of "add direct answers," actually draft the answer paragraph for the business owner to paste.

7. **PDF export** — The HTML report is already print-to-PDF friendly, but a direct PDF export button would be smoother.

8. **More AI engines** — Add checking for You.com, Phind, Kagi, and other emerging AI search platforms as their crawler behaviors become documented.

---

## Key Design Decisions

**Why a transparent score, not a magic number?** The brief said "if you show a number, we must be able to see how it was calculated." I took this seriously — every point in the score traces to a specific check with specific evidence. The report's score breakdown is expandable to show every component.

**Why copy-pasteable fixes?** The brief said "don't describe the fix — hand it to them." Every actionable finding includes a ready-to-use fix: the actual robots.txt lines, the actual JSON-LD block, the actual meta tag. A business owner should be able to act without Googling "how to add FAQ schema."

**Why five pillars, not twelve?** The brief said "go deep, not wide. Three checks done properly beat twelve that tick boxes." I chose the five areas that I can defend with research evidence (the GEO benchmark), real-world impact (bot blocking is the #1 killer), and the actual AI search mechanism (brand recall tests the outcome, source presence tests where AI looks).

**Why LLM-as-judge instead of pure rules?** The brief said "be able to defend every check." Using an LLM to assess content quality is defensible because it mirrors what AI search engines actually do. Pure regex rules would miss nuance (e.g., "is this answer actually good?" vs. "does it contain a definition pattern?").

**Why weighted 15/20/15/25/25?** Crawlability is binary-conditional (if you're blocked, nothing else matters, but if you're not, it doesn't differentiate much) — so 15%. Content answerability and structure are important inputs — 20% and 15%. Brand recall and AI Visibility & Competitive Intelligence are weighted highest (25% each) because they measure the actual *outcome* — whether AI engines know and mention you, whether you're on the platforms they search, whether they describe you correctly, and whether you have more share of voice than competitors.

---

## License

MIT
