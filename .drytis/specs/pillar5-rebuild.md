# Task: Rebuild Pillar 5 — AI Visibility & Competitive Intelligence

## Goal
Transform Pillar 5 from a simple "are you on 7 platforms" check into a 
comprehensive competitive intelligence pillar that answers: **Will AI engines
find you, describe you correctly, and recommend you over competitors?**

## Five sub-checks

### 1. Platform Coverage (existing, refined) — 20 pts
- Check target brand on 7 platforms (Wikipedia, GitHub, YouTube, Reddit, G2, Crunchbase, LinkedIn)
- Keep existing HTTP-based checks

### 2. Competitive Coverage Gap (NEW) — 20 pts  
- Check top 3 competitors on the SAME 7 platforms
- Build a coverage map: where do they have presence that you don't?
- Score: you lose points for each platform where a competitor is present but you're not
- "Your competitor is on YouTube but you're not — they win that surface"

### 3. AI Positioning Accuracy (NEW) — 20 pts
- Send a query to the LLM asking it to describe the brand
- Compare the AI's description against the brand's actual self-description (from their homepage)
- Check for semantic mismatches: "premium" vs "affordable", "enterprise" vs "small business"
- Score: how accurately does the AI understand what you are?

### 4. Share of Voice (NEW) — 20 pts
- Across all category/comparison queries, count target brand mentions vs competitor mentions
- "You appear in 3/4 queries, competitor appears in 4/4 — they have more share of voice"
- Score based on ratio of your mentions to total brand mentions

### 5. Vector Search Inclusion (NEW) — 20 pts
- Compute embedding of homepage content
- Compute embeddings of typical category queries
- Measure cosine similarity — if low, the content won't be retrieved by vector search
- "Your content embedding has only 23% similarity to relevant queries — 
   the AI's vector search won't surface you"

## Files to change
- `geo_auditor/analyzers/source_presence.py` — complete rewrite as competitive intelligence
- `geo_auditor/llm.py` — add embedding computation, positioning accuracy check
- `geo_auditor/models.py` — add dataclasses for competitor data
- `geo_auditor/analyzers/brand_recall.py` — share competitor query results with pillar 5
- `geo_auditor/templates/report.html` — competitive coverage map
- `tests/test_source_presence.py` — update for new structure
- `README.md` — document the rebuilt pillar

## Acceptance criteria
- [ ] Competitive coverage map shows your presence vs competitor presence per platform
- [ ] AI positioning accuracy detects mismatches between self-description and AI description
- [ ] Share of voice tracks target brand vs competitors across queries
- [ ] Vector search inclusion computed via real embedding similarity
- [ ] All 5 sub-checks scored and surfaced in report
- [ ] Graceful degradation when LLM/embeddings unavailable
- [ ] All tests pass
- [ ] 3 official reports re-run
