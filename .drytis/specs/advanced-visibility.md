# Task: Add 4 AI Visibility Features from Reference Repos

## Features
1. **Citation Rank Tracking** (from ai-cmo) — track WHERE in the AI response the brand appears (position matters: mentioned 1st vs 5th)
2. **Text Fragment Evidence** (from geo-aeo-tracker) — extract the exact sentence(s) where the brand is mentioned
3. **Search-Enabled Queries** (from ai-cmo) — try to use models with web search built in for live retrieval testing
4. **Selection Rate** (from geo-aeo-tracker) — measure what % of the AI response is derived from/overlaps with the target site's content

## Files to change
- `geo_auditor/llm.py` — add search-enabled query, citation rank in mention check, evidence extraction
- `geo_auditor/analyzers/brand_recall.py` — surface citation rank, evidence sentences, selection rate in scoring + findings
- `geo_auditor/analyzers/selection_rate.py` — NEW: content overlap analysis
- `geo_auditor/templates/report.html` — show citation rank, evidence, selection rate
- `tests/test_brand_recall.py` — update for new fields

## Acceptance criteria
- [ ] Citation rank shown per query (1st mention, 2nd, etc.)
- [ ] Exact sentence extracted for each mention
- [ ] Search-enabled query attempted (falls back gracefully)
- [ ] Selection rate computed per query (% of response grounded in target content)
- [ ] All displayed in report evidence
- [ ] All tests pass
