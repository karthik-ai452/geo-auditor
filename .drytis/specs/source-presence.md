# Task: Source Platform Presence (Pillar 5)

## Goal
Add a 5th audit pillar that checks whether the business exists on the source
platforms that AI search engines actually pull from when researching brands.

## User's framework
- Gemini searches: YouTube, Wikipedia, Reddit, Instagram
- ChatGPT searches: Forbes, big blogs, review sites (G2, Capterra)
- Perplexity searches: top SEO-ranked sites
- Sub-agents look at these sources first, then broader web
- Sources change over time

## Design

### Platforms checked (real HTTP, no mocking)
1. **Wikipedia** — Wikipedia REST API search for brand name
2. **GitHub** — GitHub API check for org/user with brand slug
3. **YouTube** — YouTube oEmbed API for channel existence
4. **Reddit** — Reddit JSON search API for brand mentions
5. **Crunchbase** — HTTP HEAD against organization URL pattern
6. **G2** — HTTP GET against product URL pattern
7. **LinkedIn** — HTTP GET against company URL pattern

### Scoring rebalance (5 pillars)
- Crawlability: 15% (was 20%)
- Answerability: 20% (was 25%)
- Structure: 15% (was 20%)
- Brand Recall: 25% (was 35%)
- Source Presence: 25% (new)

### Files to change
1. `models.py` — add SOURCE_PRESENCE to Pillar enum
2. `scoring.py` — rebalance weights, labels, descriptions
3. `analyzers/source_presence.py` — NEW analyzer
4. `audit.py` — wire in new analyzer
5. `templates/report.html` — 5-column pillar grid
6. `web/app.py` — 5th pillar on landing page
7. `README.md` — document the 5th pillar
8. `tests/test_source_presence.py` — unit tests

### Acceptance criteria
- [ ] All 7 platform checks execute real HTTP requests
- [ ] Each check handles failure gracefully (timeout, 403, 404)
- [ ] Checks run in parallel via asyncio.gather
- [ ] Score breakdown shows per-platform pass/fail
- [ ] Findings include actionable fixes per missing platform
- [ ] Report renders correctly with 5 pillars
- [ ] 3 official reports re-run successfully
- [ ] All tests pass
