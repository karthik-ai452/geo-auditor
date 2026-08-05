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

#### Pillar 3: Structured Data & Machine-Readability (20%) — *Can machines parse and understand your content?*

**What it checks:**
- `schema.org` JSON-LD validity and type coverage
- Title and meta description presence and length
- Semantic HTML structure (H1, H2, paragraphs, word count)
- Open Graph tags, canonical URLs

#### Pillar 4: AI Brand Recall (35%) — *Do AI engines actually know and mention your business?*

**What it checks:**
The previous three pillars check *preconditions* — can bots reach you, is your content answerable, is your data parseable. This pillar checks the *outcome*: we send real questions to an AI model and measure whether it actually mentions the target business.

This tests the two pathways AI engines use to surface businesses:
1. **Training data knowledge** — does the model already know about you? (We ask: "What is [brand]?")
2. **Category/competitor visibility** — when asked about your industry, do you come up unprompted? (We ask: "What are the best [category] platforms?", "Can you compare the top [category] tools?")

**How it works:**
1. Infer the brand name and industry category from the homepage (title, JSON-LD, content)
2. Generate 4-5 relevant queries (direct brand, category, comparison, competitor-anchored)
3. Send each query to an LLM and capture the full response
4. Use a second LLM call to check whether the brand is mentioned, how, in what context, and where in the response
5. Score based on mention rate across query types (direct query: 40%, category: 35%, comparison: 25%)

**Why this matters and why it's weighted highest (35%):** The other pillars measure *inputs* to AI visibility — "can they reach you" and "does your content look good." This pillar measures the *output* — "do they actually mention you." A business can be perfectly crawlable, have great structured data, and publish answerable content, but if no AI model knows it exists, it won't appear in any AI answer. Brand recall is the closest proxy to "will ChatGPT/Perplexity/Claude mention me when a potential customer asks?"

**Honest limitation:** This tests one LLM's knowledge. Different AI engines (ChatGPT, Perplexity, Claude) use different models with different training data, so recall may vary across engines. The score is a directional indicator, not a guarantee of visibility on any specific platform.

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
- **Brand Recall (Pillar 4)**: real LLM queries and brand mention detection — real AI calls
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
| `OPENAI_API_KEY` | For Pillar 2 | API key for the LLM judge. Without it, rule-based scoring is used. |
| `OPENAI_BASE_URL` | For Pillar 2 | Base URL for the OpenAI-compatible gateway. |
| `APP_HOST` | No (default: 0.0.0.0) | Web app bind host. |
| `APP_PORT` | No (default: 8000) | Web app bind port. |

### Run the Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

60 tests covering scoring math, robots.txt parsing, sitemap parsing, HTML extraction, analyzer logic, and brand recall.

---

## Sample Reports

Three real audit reports are included in `reports/official/`:

| Site | Score | Grade | What it shows |
|------|-------|-------|---------------|
| **stripe.com** | 81.3/100 | Strong | Strong across all pillars — 100% brand recall (AI knows Stripe well), good structure, crawlable. Weaker content answerability (marketing copy). |
| **notion.so** | 77.4/100 | Moderate | 100% brand recall and perfect crawlability, but poor structured data and content signals hold it back from Strong. |
| **example.com** | 24.1/100 | Critical | Fails across all pillars — no robots.txt, no sitemap, no structured data, minimal content, and the AI barely recognizes the brand. |

These were chosen to demonstrate the tool differentiates between sites with different GEO maturity levels.

---

## How the Score Works

The overall score is a weighted average of four pillars:

```
Overall = Crawlability × 0.20 + Answerability × 0.25 + Structure × 0.20 + Brand Recall × 0.35
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
- **OpenAI-compatible LLM gateway** — content answerability judge
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
    → Brand Recall (real LLM brand mention testing)
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

**Why three pillars, not twelve?** The brief said "go deep, not wide. Three checks done properly beat twelve that tick boxes." I chose the three areas that I can defend with research evidence (the GEO benchmark) and real-world impact (bot blocking is the #1 killer).

**Why LLM-as-judge instead of pure rules?** The brief said "be able to defend every check." Using an LLM to assess content quality is defensible because it mirrors what AI search engines actually do. Pure regex rules would miss nuance (e.g., "is this answer actually good?" vs. "does it contain a definition pattern?").

**Why weighted 20/25/20/35?** Crawlability is binary-conditional (if you're blocked, nothing else matters, but if you're not, it doesn't differentiate much) — so 20%. Content answerability and structure are important inputs — 25% and 20%. Brand recall is weighted highest (35%) because it's the only pillar that measures the actual *outcome* — whether AI engines know and mention you. The other three measure preconditions; this one measures results.

---

## License

MIT
