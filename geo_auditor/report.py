"""Report renderer — generates self-contained HTML reports.

Uses jinja2 to render the report template. The output is a single
self-contained HTML file with inline CSS (no external dependencies),
printable to PDF.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from geo_auditor.models import AuditResult

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
REPORTS_DIR = Path(__file__).parent.parent / "reports"


def render_report(result: AuditResult, llm_data: dict | None = None) -> str:
    """Render the audit result as a self-contained HTML string."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    # Don't autoescape the fix blocks (they contain intentional code formatting)
    env.policies["ext.i18n.trimmed"] = True

    template = env.get_template("report.html")

    # Determine model note
    if llm_data and llm_data.get("error"):
        model_note = "Content scoring: rule-based (LLM unavailable)"
    else:
        model_note = "Content scoring: LLM-assisted (drytis/kimi-k2.5)"

    grade_class = result.score.grade.lower()

    html = template.render(
        domain=result.domain,
        audited_at=result.audited_at,
        score=result.score,
        grade_class=grade_class,
        findings=result.findings,
        action_plan=result.action_plan,
        model_note=model_note,
    )
    return html


def save_report(result: AuditResult, output_dir: Path | None = None, llm_data: dict | None = None) -> tuple[str, str]:
    """Save the report as HTML + JSON. Returns (html_path, json_path)."""
    if output_dir is None:
        output_dir = REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate slug from domain
    slug = result.domain.replace("https://", "").replace("http://", "").replace("/", "_").replace(".", "-")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{slug}_{timestamp}"

    html_path = output_dir / f"{base_name}.html"
    json_path = output_dir / f"{base_name}.json"

    # Save HTML
    html = render_report(result, llm_data)
    html_path.write_text(html, encoding="utf-8")

    # Save JSON
    json_data = result.to_dict()
    if llm_data:
        json_data["llm_judge_data"] = llm_data
    json_path.write_text(json.dumps(json_data, indent=2, default=str), encoding="utf-8")

    logger.info(f"Report saved: {html_path}")
    return str(html_path), str(json_path)
