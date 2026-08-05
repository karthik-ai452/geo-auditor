# Task: GEO Auditor — Full Build

## Files to Create
- requirements.txt, pyproject.toml
- geo_auditor/__init__.py, __main__.py
- geo_auditor/models.py — dataclasses (Finding, Score, PageData, AuditResult)
- geo_auditor/crawler.py — robots.txt, sitemap, page fetch, text extract
- geo_auditor/llm.py — OpenAI-compatible gateway client
- geo_auditor/analyzers/crawlability.py — Pillar 1
- geo_auditor/analyzers/answerability.py — Pillar 2 (LLM-as-judge)
- geo_auditor/analyzers/structure.py — Pillar 3 (JSON-LD/schema.org)
- geo_auditor/scoring.py — transparent scoring engine
- geo_auditor/report.py — HTML report renderer (jinja2)
- geo_auditor/templates/report.html — report template
- geo_auditor/static/report.css — report styles
- geo_auditor/web/app.py — FastAPI web app
- geo_auditor/cli.py — CLI commands
- tests/ — unit tests for crawler, analyzers, scoring

## Acceptance Criteria
- [ ] CLI: `python -m geo_auditor audit <url>` produces a report file
- [ ] Web app: enter URL → see report in browser at /
- [ ] robots.txt per-bot analysis with real evidence (which bots allowed/blocked)
- [ ] sitemap.xml analysis with URL count
- [ ] JSON-LD / schema.org analysis with validity + coverage
- [ ] LLM-as-judge content answerability with scored signal extraction
- [ ] Score breakdown shows the math for every component
- [ ] Every finding names the exact page, shows what was found, shows what it should be
- [ ] Copy-pasteable fix snippets (robots.txt lines, JSON-LD blocks)
- [ ] Monday-morning action plan ordered by impact × effort
- [ ] Unit tests pass (scoring math, analyzers with fixtures)
- [ ] Three real audit reports generated against real businesses
- [ ] README with run steps, build/cut reasoning, real vs mocked, next-week roadmap
