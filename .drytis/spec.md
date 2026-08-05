# GEO Auditor — Spec

## Overview
A tool where a user enters a business website URL and receives an audit report covering:
1. How visible they are in AI search (a score + visible breakdown of the math)
2. What is broken (specific, evidence-backed — naming the exact page and showing what was found vs what it should be)
3. What to fix, in what order (prioritized by impact × effort)

## Tech Stack
- Python 3.13
- httpx (async HTTP client)
- Beautiful Soup / lxml (HTML parsing — never hand-rolled)
- jsonschema (JSON-LD validation)
- jinja2 (report rendering)
- FastAPI + uvicorn (web app)
- typer/click (CLI)
- OpenAI-compatible LLM gateway (LLM-as-judge for content answerability)

## Three Audit Pillars

### Pillar 1 — AI Crawlability (weight: 25%)
Checks whether AI engines can even reach the site.
- robots.txt parsed per-bot: GPTBot, PerplexityBot, ClaudeBot, anthropic-ai, CCBot, Google-Extended
- sitemap.xml presence + validity + URL count
- Per-page meta robots / noindex
- HTTP reachability + load time

### Pillar 2 — Content Answerability (weight: 45%) — LLM-as-judge
Checks whether content answers questions the way AI engines extract and cite.
- Crawl key pages, extract text
- LLM scores how well content answers domain questions
- Signal extraction: statistic density, direct-answer/definition presence, citation/quotation density, FAQ schema presence

### Pillar 3 — Structured Data & Machine-Readability (weight: 30%)
Checks whether machines can parse the content.
- schema.org JSON-LD validity + coverage (Org, Article, FAQ, Product, etc.)
- Semantic HTML structure, meta description, Open Graph, canonical

## Scoring
Overall = weighted avg of three pillars. Every sub-score shows the exact math. No magic numbers.

## Report
Self-contained printable-to-PDF HTML:
- Executive summary — score + one-line verdict
- Score breakdown — visual bars, expandable to raw math
- Findings — each card: severity, exact page, what was found, what it should be, copy-pasteable fix
- Monday-morning action plan — impact × effort, jargon explained inline

## Cut (documented in README)
- Backlink/DA analysis (needs paid SEO API)
- Live citation tracking on real engines (light LLM-impression proxy, labelled)
- Broad web mention counts
- Auth/billing/DB/multi-user

## Acceptance Criteria
- [ ] CLI: `python -m geo_auditor audit <url>` produces a report file
- [ ] Web app: enter URL → see report in browser
- [ ] robots.txt per-bot analysis with real evidence
- [ ] sitemap.xml analysis with URL count
- [ ] JSON-LD / schema.org analysis with validity + coverage
- [ ] LLM-as-judge content answerability with scored signal extraction
- [ ] Score breakdown shows the math for every component
- [ ] Every finding names the exact page, shows what was found, shows what it should be
- [ ] Copy-pasteable fix snippets (robots.txt lines, JSON-LD blocks)
- [ ] Monday-morning action plan ordered by impact × effort
- [ ] Three real audit reports generated against real businesses
- [ ] README with run steps, build/cut reasoning, real vs mocked, next-week roadmap
