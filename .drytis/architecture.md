# GEO Auditor — Architecture

## Directory Structure
```
/workspace
├── .drytis/              # blueprint files
├── geo_auditor/          # main package
│   ├── __init__.py
│   ├── __main__.py       # CLI entry: python -m geo_auditor
│   ├── cli.py            # CLI commands (audit)
│   ├── crawler.py        # robots.txt, sitemap, page fetch, text extract
│   ├── analyzers/
│   │   ├── __init__.py
│   │   ├── crawlability.py   # Pillar 1: AI crawlability
│   │   ├── answerability.py  # Pillar 2: LLM-as-judge content
│   │   └── structure.py      # Pillar 3: JSON-LD / schema.org
│   ├── llm.py            # OpenAI-compatible gateway client
│   ├── scoring.py        # transparent scoring engine
│   ├── report.py         # HTML report renderer (jinja2)
│   ├── models.py         # data classes: Finding, Score, AuditResult
│   └── web/
│       ├── __init__.py
│       └── app.py        # FastAPI app
├── geo_auditor/templates/  # jinja2 report template
│   └── report.html
├── geo_auditor/static/     # CSS for report
├── tests/
│   ├── test_crawler.py
│   ├── test_crawlability.py
│   ├── test_structure.py
│   ├── test_scoring.py
│   └── fixtures/
├── reports/              # generated audit reports (HTML + JSON)
├── README.md
├── requirements.txt
└── pyproject.toml
```

## Data Flow
```
URL input
  → Crawler: fetch robots.txt, sitemap.xml, N key pages
    → extract text + metadata per page
  → Analyzers (run in parallel on crawled data):
    → Crawlability analyzer (robots/sitemap/meta robots)
    → Structure analyzer (JSON-LD, semantic HTML, meta tags)
    → Answerability analyzer (LLM judge on extracted text)
  → Scoring engine: combine findings → pillar scores → overall score (with math shown)
  → Report renderer: jinja2 → self-contained HTML
```

## Key Decisions
- **Async crawler** with httpx for speed on 3–5 pages per site
- **Crawl scope**: homepage + pages found in sitemap (capped at 5 key pages). This keeps audits fast and focused.
- **LLM judge**: structured output (JSON schema) so scores are reproducible and parseable
- **No database** — audits are stateless, run on demand, output to files
- **Report is self-contained HTML** — inline CSS, no external deps, prints to PDF

## Ports
- Web app: 8000 (FastAPI/uvicorn) → Caddy reverse proxy at /
