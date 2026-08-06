"""FastAPI web app for GEO Auditor.

Provides a simple web UI with async audit pattern:
  GET  /              → form to enter a URL
  POST /audit/start   → start audit in background, return job ID (instant)
  GET  /audit/status/{job_id} → poll for audit status (instant)
  GET  /audit/report/{job_id} → show the finished report
  GET  /report/{url:path}     → pre-generated static reports
"""

from __future__ import annotations

import asyncio
import html
import os
import uuid
import json
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from geo_auditor.audit import run_audit
from geo_auditor.report import render_report

app = FastAPI(title="GEO Auditor", version="0.2.0")

import tempfile
import threading

# ---------------------------------------------------------------------------
# File-based job store (survives across uvicorn workers)
# ---------------------------------------------------------------------------
_JOBS_DIR = Path(tempfile.gettempdir()) / "geo_auditor_jobs"
_JOBS_DIR.mkdir(exist_ok=True)
_MAX_JOB_AGE_HOURS = 2
_job_lock = threading.Lock()


def _job_path(job_id: str) -> Path:
    return _JOBS_DIR / f"{job_id}.json"


def _save_job(job_id: str, data: dict) -> None:
    """Save job state to disk (atomic write)."""
    tmp = _job_path(job_id).with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(_job_path(job_id))


def _load_job(job_id: str) -> dict | None:
    """Load job state from disk."""
    p = _job_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_report(job_id: str, report_html: str) -> None:
    """Save rendered report HTML to a separate file (too large for JSON)."""
    (_JOBS_DIR / f"{job_id}.html").write_text(report_html, encoding="utf-8")


def _load_report(job_id: str) -> str | None:
    """Load rendered report HTML."""
    p = _JOBS_DIR / f"{job_id}.html"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def _prune_old_jobs() -> None:
    """Remove job files older than _MAX_JOB_AGE_HOURS."""
    now = datetime.utcnow()
    for f in _JOBS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(data["created_at"])
            if (now - created).total_seconds() > _MAX_JOB_AGE_HOURS * 3600:
                f.unlink(missing_ok=True)
                (_JOBS_DIR / f"{f.stem}.html").unlink(missing_ok=True)
        except Exception:
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Pre-generated reports
# ---------------------------------------------------------------------------
REPORTS_DIR = Path(__file__).parent.parent.parent / "reports" / "official"


def _load_static_reports() -> dict[str, str]:
    """Load any pre-generated HTML reports from reports/official/."""
    reports = {}
    if REPORTS_DIR.exists():
        for f in REPORTS_DIR.glob("*.html"):
            # filename like stripe-com_20260805_071928.html
            stem = f.stem
            # extract domain part before first underscore-timestamp
            parts = stem.split("_")
            if parts:
                domain_key = parts[0].replace("-", ".")
                reports[domain_key] = f.name
    return reports


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    """Landing page with URL input form."""
    static_reports = _load_static_reports()
    example_links = ""
    for domain in sorted(static_reports.keys()):
        example_links += (
            f'<a href="/report/{domain}">{domain}</a>'
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GEO Auditor — AI Search Visibility Checker</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    padding: 20px;
  }}
  .card {{
    background: white; border-radius: 24px; padding: 48px;
    max-width: 640px; width: 100%; box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  }}
  .logo {{ font-size: 32px; margin-bottom: 8px; }}
  h1 {{ font-size: 28px; color: #1e293b; margin-bottom: 8px; }}
  .subtitle {{ color: #64748b; font-size: 16px; margin-bottom: 32px; line-height: 1.5; }}
  form {{ display: flex; flex-direction: column; gap: 16px; }}
  .input-group {{ display: flex; gap: 12px; }}
  input[type="text"] {{
    flex: 1; padding: 16px 20px; font-size: 16px; border: 2px solid #e2e8f0;
    border-radius: 12px; outline: none; transition: border-color 0.2s;
  }}
  input[type="text"]:focus {{ border-color: #4f46e5; }}
  button {{
    padding: 16px 32px; font-size: 16px; font-weight: 600; color: white;
    background: #4f46e5; border: none; border-radius: 12px; cursor: pointer;
    transition: background 0.2s; white-space: nowrap;
  }}
  button:hover {{ background: #4338ca; }}
  button:disabled {{ background: #94a3b8; cursor: not-allowed; }}
  .loading {{ display: none; text-align: center; padding: 20px; color: #64748b; }}
  .loading.show {{ display: block; }}
  .spinner {{
    border: 3px solid #e2e8f0; border-top: 3px solid #4f46e5; border-radius: 50%;
    width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto 12px;
  }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  .examples {{ margin-top: 24px; padding-top: 24px; border-top: 1px solid #e2e8f0; }}
  .examples h3 {{ font-size: 14px; color: #64748b; margin-bottom: 8px; }}
  .example-links {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .example-links a {{
    padding: 6px 14px; background: #f1f5f9; border-radius: 8px;
    font-size: 13px; color: #4f46e5; text-decoration: none; transition: background 0.2s;
  }}
  .example-links a:hover {{ background: #e2e8f0; }}
  .what-is {{ margin-top: 32px; padding: 20px; background: #f8fafc; border-radius: 12px; font-size: 14px; color: #64748b; }}
  .what-is h3 {{ color: #1e293b; margin-bottom: 8px; font-size: 15px; }}
  .what-is ul {{ margin-left: 18px; }}
  .what-is li {{ margin-top: 4px; }}
  #status-text {{ font-size: 14px; min-height: 20px; }}
</style>
</head>
<body>
<div class="card">
  <div class="logo">🔍</div>
  <h1>GEO Auditor</h1>
  <p class="subtitle">See how visible your business is in AI search.<br>
  ChatGPT, Perplexity, Claude, Google AI Overviews — are they citing you?</p>

  <form id="auditForm" onsubmit="startAudit(event)">
    <div class="input-group">
      <input type="text" id="urlInput" placeholder="example.com" required autofocus>
      <button type="submit" id="auditBtn">Audit →</button>
    </div>
  </form>

  <div class="loading" id="loading">
    <div class="spinner"></div>
    <p id="status-text">Starting audit...</p>
  </div>

  <div class="examples">
    <h3>Sample audit reports (pre-generated, instant):</h3>
    <div class="example-links">
      {example_links or '<span style="font-size:13px;color:#94a3b8">No pre-generated reports available</span>'}
    </div>
    <h3 style="margin-top:12px">Try a live audit:</h3>
    <div class="example-links">
      <a href="#" onclick="document.getElementById('urlInput').value='stripe.com';return false;">stripe.com</a>
      <a href="#" onclick="document.getElementById('urlInput').value='notion.so';return false;">notion.so</a>
      <a href="#" onclick="document.getElementById('urlInput').value='linear.app';return false;">linear.app</a>
    </div>
  </div>

  <div class="what-is">
    <h3>What does this check?</h3>
    <ul>
      <li><strong>AI Crawlability</strong> — Can ChatGPT/Perplexity/Claude crawlers reach your site?</li>
      <li><strong>Content Answerability</strong> — Does your content answer questions AI engines extract and cite?</li>
      <li><strong>Structured Data</strong> — Can machines parse your site's schema.org data?</li>
      <li><strong>AI Brand Recall</strong> — When AI engines answer questions about your industry, do they mention you?</li>
      <li><strong>AI Visibility & Competitive Intelligence</strong> — The core pillar. Checks 5 things:
        <ul style="margin-top: 4px; font-size: 13px; color: #94a3b8;">
          <li>Are you on the 7 platforms AI engines search first?</li>
          <li>Do competitors have platform coverage you don't?</li>
          <li>Does the AI describe you correctly (positioning accuracy)?</li>
          <li>Does the AI mention you more or less than competitors (share of voice)?</li>
          <li>Will AI vector/semantic search retrieve your content?</li>
        </ul>
      </li>
    </ul>
  </div>
</div>
<script>
async function startAudit(event) {{
  event.preventDefault();
  const url = document.getElementById('urlInput').value.trim();
  if (!url) return;

  document.getElementById('loading').classList.add('show');
  document.getElementById('auditBtn').disabled = true;
  document.getElementById('status-text').textContent = 'Starting audit...';

  try {{
    const resp = await fetch('/audit/start', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
      body: 'url=' + encodeURIComponent(url)
    }});
    const data = await resp.json();

    if (data.job_id) {{
      pollStatus(data.job_id);
    }} else {{
      document.getElementById('status-text').textContent = 'Error: ' + (data.error || 'Could not start audit');
      document.getElementById('auditBtn').disabled = false;
      document.getElementById('loading').classList.remove('show');
    }}
  }} catch (e) {{
    document.getElementById('status-text').textContent = 'Error starting audit. Please try again.';
    document.getElementById('auditBtn').disabled = false;
    document.getElementById('loading').classList.remove('show');
  }}
}}

async function pollStatus(jobId) {{
  const steps = [
    'Fetching robots.txt & sitemap...',
    'Crawling pages...',
    'Analyzing structured data...',
    'Running LLM content judge...',
    'Testing AI brand recall...',
    'Checking platform presence...',
    'Analyzing competitive coverage...',
    'Checking AI positioning accuracy...',
    'Measuring share of voice...',
    'Testing vector search inclusion...',
    'Computing final scores...'
  ];
  let stepIdx = 0;

  const interval = setInterval(async () => {{
    try {{
      const resp = await fetch('/audit/status/' + jobId);
      const data = await resp.json();

      if (data.status === 'done') {{
        clearInterval(interval);
        window.location.href = '/audit/report/' + jobId;
      }} else if (data.status === 'error') {{
        clearInterval(interval);
        document.getElementById('status-text').innerHTML =
          '❌ Audit failed: ' + (data.error || 'Unknown error') +
          ' <br><a href="/" style="color:#4f46e5">← Try again</a>';
        document.getElementById('auditBtn').disabled = false;
      }} else {{
        // Update status text with rotating steps for UX
        if (stepIdx < steps.length) {{
          document.getElementById('status-text').textContent = steps[stepIdx];
          stepIdx++;
        }}
      }}
    }} catch (e) {{
      // Network blip — keep polling
    }}
  }}, 3000);  // poll every 3 seconds
}}
</script>
</body>
</html>"""
    return HTMLResponse(content=page)


# ---------------------------------------------------------------------------
# Async audit endpoints
# ---------------------------------------------------------------------------

@app.post("/audit/start")
async def audit_start(url: str = Form(...)):
    """Start an audit in the background. Returns job ID instantly."""
    job_id = str(uuid.uuid4())[:8]
    job_data = {
        "url": url,
        "status": "running",
        "created_at": datetime.utcnow().isoformat(),
        "error": None,
    }
    with _job_lock:
        _save_job(job_id, job_data)
        _prune_old_jobs()

    # Fire and forget — run in a background task
    asyncio.create_task(_run_audit_bg(job_id, url))

    return JSONResponse({"job_id": job_id, "status": "running"})


async def _run_audit_bg(job_id: str, url: str):
    """Run the audit in a background asyncio task (thread pool under the hood)."""
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: asyncio.run(run_audit(url))),
            timeout=180,
        )
        # Render the report HTML once and cache it
        report_html = render_report(result, {})
        _save_report(job_id, report_html)

        # Update job status
        job = _load_job(job_id) or {"url": url, "created_at": datetime.utcnow().isoformat()}
        job["status"] = "done"
        with _job_lock:
            _save_job(job_id, job)
    except asyncio.TimeoutError:
        job = _load_job(job_id) or {}
        job["status"] = "error"
        job["error"] = "Audit timed out (180s limit). The site may be too large or slow to respond."
        with _job_lock:
            _save_job(job_id, job)
    except Exception as e:
        job = _load_job(job_id) or {}
        job["status"] = "error"
        job["error"] = str(e)[:500]
        with _job_lock:
            _save_job(job_id, job)


@app.get("/audit/status/{job_id}")
async def audit_status(job_id: str):
    """Poll endpoint — returns current status instantly."""
    job = _load_job(job_id)
    if not job:
        return JSONResponse({"status": "error", "error": "Job not found"}, status_code=404)
    return JSONResponse({
        "status": job.get("status", "unknown"),
        "error": job.get("error"),
        "url": job.get("url"),
    })


@app.get("/audit/report/{job_id}", response_class=HTMLResponse)
async def audit_report(job_id: str):
    """Show the finished audit report."""
    job = _load_job(job_id)
    if not job:
        return _error_page("Report not found", "This audit job doesn't exist or has expired.")
    if job.get("status") == "error":
        return _error_page("Audit Failed", job.get("error", "Unknown error"))
    if job.get("status") == "running":
        return HTMLResponse(
            content='<meta http-equiv="refresh" content="3">Still running... <a href="/">Go home</a>',
            status_code=302,
        )
    report_html = _load_report(job_id)
    if not report_html:
        return _error_page("Report not found", "Report file is missing.")
    return HTMLResponse(content=report_html)


# ---------------------------------------------------------------------------
# Pre-generated static reports
# ---------------------------------------------------------------------------

@app.get("/report/{domain}", response_class=HTMLResponse)
async def static_report(domain: str):
    """Serve a pre-generated report by domain name."""
    reports = _load_static_reports()
    # Try exact match first, then fuzzy
    filename = reports.get(domain)
    if not filename:
        # Try with dashes → dots conversion
        dash_domain = domain.replace(".", "-")
        filename = reports.get(dash_domain)
    if not filename:
        # Try partial match
        for key, val in reports.items():
            if domain in key or key in domain:
                filename = val
                break

    if not filename:
        return _error_page(
            "No Pre-Generated Report",
            f"No pre-generated report found for '{html.escape(domain)}'. Try running a live audit instead."
        )

    filepath = REPORTS_DIR / filename
    content = filepath.read_text(encoding="utf-8")
    return HTMLResponse(content=content)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error_page(title: str, message: str) -> HTMLResponse:
    return HTMLResponse(content=f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>{html.escape(title)}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; text-align: center; padding: 60px; background: #f8fafc; }}
  .error {{ max-width: 500px; margin: 0 auto; background: white; padding: 40px; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
  h1 {{ color: #dc2626; margin-bottom: 16px; }}
  p {{ color: #64748b; line-height: 1.6; }}
  a {{ color: #4f46e5; text-decoration: none; }}
</style></head>
<body>
<div class="error">
  <h1>⚠️ {html.escape(title)}</h1>
  <p>{html.escape(message)}</p>
  <p style="margin-top: 24px;"><a href="/">← Back to home</a></p>
</div>
</body></html>""", status_code=500)
