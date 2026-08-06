# Reference Repos Study: ai-cmo & geo-aeo-tracker

## ai-cmo (AICMO/ai-cmo)

**Stack:** FastAPI + SQLModel + Celery workers + LiteLLM (multi-provider) + Docker Compose. Vertex AI service account for Gemini, OpenAI API key for GPT.

### What's special about their AI visibility approach:

1. **Real multi-provider prompt monitoring via search-enabled LLMs:**
   - OpenAI: `gpt-4o-search-preview` with `web_search_options` — this triggers actual live web search inside the model
   - Gemini: `gemini-2.5-flash` via Vertex AI with `GoogleSearch` tool — uses Google Search grounding
   - Both return real citations/grounding metadata, not training data recall

2. **Citation position tracking (company_domain_rank):**
   - Not just "is brand mentioned" but "at what position in the citation list"
   - Iterates annotations/grounding_chunks, normalizes domains, finds first match
   - 1-based rank — being cited #1 vs #8 is a huge visibility difference

3. **Brand name matching strategy:**
   - Uses company.name + company.name.replace(" ", "") + JSON aliases
   - Case-insensitive substring match in response text
   - Pragmatic — catches "Notion", "NotionInc", "notion.so" variants

4. **LLM-powered company understanding:**
   - `create_site_summary()` — feeds raw homepage HTML to LLM, gets structured {company_name, company_description, main_products}
   - `create_prompts()` — LLM generates target audience prompts where company should appear (product + expertise prompts)
   - `create_competitors()` — LLM generates up to 5 competitors
   - `generate_recommendation()` — LLM explains WHY competitor wins and generates action items (structured JSON via Pydantic schema)

5. **Scheduled monitoring with Celery:**
   - Prompts run on configurable refresh intervals (default weekly)
   - Quota management (QuotaType.LLM_CALLS)
   - MonitoredPrompt → MonitoredPromptRun lifecycle

6. **LiteLLM as provider abstraction:**
   - `litellm.completion()` wraps OpenAI/Gemini/Vertex behind one interface
   - Cost tracking via `litellm.completion_cost()`
   - Caching support

### Key takeaway for our tool:
- Their brand_mentioned check is a simple substring match (not great — we improved this with LLM-as-judge)
- Their citation rank tracking is excellent — we should consider adding it
- Their competitor recommendation engine is the standout feature — explains WHY, not just WHAT

---

## geo-aeo-tracker (danishashko/geo-aeo-tracker)

**Stack:** Next.js 16 + React + TypeScript. Local-first (IndexedDB/localStorage) with optional Supabase cloud sync. Uses Bright Data API for scraping + OpenRouter for LLM analysis.

### What's special about their AI visibility approach:

1. **Selection Rate Optimization (SRO) — novel quantitative metric:**
   - Gemini allocates ~2000 words of grounding per query response
   - Selection Rate = target_grounding_words / total_grounding_words
   - Measures what percentage of the AI's grounding budget comes from YOUR page
   - Calculated at word level using groundingSupports (which text segments map to which chunks)
   - This is genuinely novel — nobody else does word-level attribution

2. **Bright Data as infrastructure layer for 6 AI platforms:**
   - Instead of calling AI APIs directly, uses Bright Data dataset API to scrape structured responses
   - Platforms: Google AI Mode, Gemini, ChatGPT, Perplexity, Copilot, Grok
   - Each has a dataset_id, triggers a snapshot, polls for completion
   - Solves rate limits, bot detection, API availability — but costs money (Bright Data subscription)

3. **Text fragment parsing for cited sentences:**
   - Parses `#:~:text=` URL fragments from citations
   - Extracts the EXACT sentence the AI cited from a source
   - `parseTextFragment()` handles prefix/suffix/exact match formats
   - This gives evidence of WHAT was cited, not just THAT it was cited

4. **Cross-platform citation analysis:**
   - `scrapeAllPlatforms()` — runs all 6 platforms in parallel via Promise.allSettled
   - Checks if target URL is cited on each platform
   - "Cited on 4/6 platforms" — multi-platform presence signals authority

5. **Fan-out visibility via Gemini search queries:**
   - `groundingMetadata.webSearchQueries` reveals what sub-queries the AI generated
   - Shows the AI's internal research process before producing its answer
   - Understanding fan-out helps optimize for the queries that matter

6. **Production-grade SSRF guard:**
   - `assertPublicHttpUrl()` — blocks private IPs (RFC1918, link-local, CGNAT, multicast)
   - Follows redirects manually and re-validates every hop
   - Blocks cloud metadata endpoints (169.254.169.254)
   - DNS resolution check — hostname can't resolve to private IP
   - We should adopt this pattern

7. **AEO Audit (static HTML analysis) — 20 checks:**
   - Categories: discovery, structure, content, technical, rendering
   - Discovery: llms.txt, llms-full.txt, robots.txt AI bot access, sitemap
   - Structure: JSON-LD, FAQ schema, Open Graph, meta description, canonical
   - Content: BLUF/direct-answer style, heading hierarchy, content depth, internal links
   - Technical: HTTPS, page size, language tag
   - Rendering: CSR detection (React/Vue/Angular/Svelte), noscript fallback, JS weight, server content quality
   - Score = passed_checks / total_checks × 100

8. **Site context extraction:**
   - Scrapes homepage via Bright Data Web Unlocker
   - LLM extracts: primaryTopics, industry, targetAudience, contentThemes, siteDescription
   - This context feeds into the SRO analysis prompt

### Key takeaways for our tool:
- Selection Rate is a powerful concept but requires Gemini API access (we use LLM-as-judge instead)
- Their SSRF guard is the gold standard — we should implement one for our crawler
- Text fragment parsing for cited sentences is excellent evidence
- Their AEO Audit has 20 checks (we have 4 pillars going deep) — validates "go deep not wide"
- Bright Data dependency is expensive and creates vendor lock-in — our approach (direct HTTP + LLM) is more accessible
- `Promise.allSettled` for parallel platform checks — fault-tolerant pattern we should use

## What we're taking vs leaving:

**Taking:**
- SSRF guard pattern for our crawler
- Promise.allSettled for parallel source platform checks
- Citation rank concept (position matters)
- Text fragment / evidence extraction approach

**Leaving:**
- Bright Data dependency (too expensive, vendor lock-in)
- 20 shallow checks (we go deep on 5 pillars)
- Gemini grounding API (requires Google API access; our LLM-as-judge is more universal)
- Supabase/IndexedDB persistence (no DB needed per requirements)
- Celery workers (no async task queue needed)
