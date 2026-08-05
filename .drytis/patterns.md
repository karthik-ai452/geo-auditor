# GEO Auditor — Patterns

## Coding Standards
- Python 3.13+, type hints on all public functions
- Dataclasses for structured data (Finding, Score, AuditResult, PageData)
- Async where I/O-bound (httpx crawling, LLM calls)
- Pure functions for scoring math — easy to unit test
- jinja2 for templating, never string concatenation for HTML

## Naming
- snake_case for functions and variables
- PascalCase for dataclasses
- UPPER_CASE for constants
- Descriptive analyzer method names: `analyze_robots_txt`, `check_json_ld_coverage`

## Error Handling
- Network failures → captured as Finding with severity=error, never crash the audit
- LLM failures → fall back to rule-based signal extraction, note the degradation
- Parse failures → log + skip that check, continue the audit
- Always produce a report, even from partial data

## Test Conventions
- pytest, tests in tests/
- Use HTML fixtures in tests/fixtures/ for parser tests (don't hit live sites in tests)
- Unit tests for scoring math (deterministic, no network)
- Unit tests for analyzers with fixture HTML
- Integration test for crawler with a mocked HTTP server (responses library)
- LLM judge: test with a mock/mockable client

## Report Conventions
- Every Finding has: id, title, severity (critical/warning/info/positive), pillar, evidence (dict), fix (copy-pasteable string), impact (0-100), effort (0-100)
- Scores are always tuples of (value, max, explanation) — never a bare number
