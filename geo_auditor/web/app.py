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
            f'<a href="/report/{domain}" class="genz-pill border-glow">🔥 {domain}</a>'
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GEO Auditor — Are You Main Character in AI Search? ⚡</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  :root {{
    --bg-dark: #090d16;
    --neon-green: #10b981;
    --neon-cyan: #06b6d4;
    --neon-pink: #ec4899;
    --neon-purple: #8b5cf6;
    --card-bg: rgba(18, 24, 38, 0.7);
    --card-border: rgba(255, 255, 255, 0.12);
  }}

  body {{
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    background-color: var(--bg-dark);
    color: #f8fafc;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 30px 20px;
    position: relative;
    overflow-x: hidden;
  }}

  /* Animated background mesh glow */
  body::before {{
    content: '';
    position: fixed;
    top: -10%; left: -10%;
    width: 60vw; height: 60vw;
    background: radial-gradient(circle, rgba(139, 92, 246, 0.22) 0%, rgba(0,0,0,0) 70%);
    z-index: -1;
    filter: blur(80px);
    animation: floatGlow 12s infinite alternate ease-in-out;
  }}
  body::after {{
    content: '';
    position: fixed;
    bottom: -10%; right: -10%;
    width: 60vw; height: 60vw;
    background: radial-gradient(circle, rgba(6, 182, 212, 0.22) 0%, rgba(0,0,0,0) 70%);
    z-index: -1;
    filter: blur(80px);
    animation: floatGlow 15s infinite alternate-reverse ease-in-out;
  }}

  @keyframes floatGlow {{
    0% {{ transform: translate(0, 0) scale(1); }}
    100% {{ transform: translate(40px, 40px) scale(1.1); }}
  }}

  .badge-top {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: rgba(139, 92, 246, 0.15);
    border: 1px solid rgba(139, 92, 246, 0.4);
    color: #c084fc;
    padding: 6px 16px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 20px;
    box-shadow: 0 0 20px rgba(139, 92, 246, 0.2);
  }}

  .card {{
    background: var(--card-bg);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--card-border);
    border-radius: 28px;
    padding: 52px 48px;
    max-width: 720px;
    width: 100%;
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.6), inset 0 1px 0 rgba(255, 255, 255, 0.1);
    position: relative;
  }}

  .logo-bar {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 12px;
  }}
  .logo-icon {{
    font-size: 36px;
    background: linear-gradient(135deg, #a855f7, #06b6d4);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }}

  h1 {{
    font-size: 38px;
    font-weight: 800;
    line-height: 1.15;
    letter-spacing: -0.02em;
    background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 12px;
  }}

  .subtitle {{
    color: #94a3b8;
    font-size: 17px;
    line-height: 1.6;
    margin-bottom: 36px;
  }}
  .highlight-text {{
    color: #38bdf8;
    font-weight: 600;
  }}

  form {{ display: flex; flex-direction: column; gap: 16px; }}

  .input-container {{
    display: flex;
    gap: 12px;
    background: rgba(10, 15, 26, 0.8);
    padding: 8px;
    border-radius: 18px;
    border: 1px solid rgba(255, 255, 255, 0.15);
    transition: all 0.3s ease;
  }}
  .input-container:focus-within {{
    border-color: #a855f7;
    box-shadow: 0 0 25px rgba(168, 85, 247, 0.3);
  }}

  input[type="text"] {{
    flex: 1;
    background: transparent;
    border: none;
    padding: 14px 18px;
    font-size: 17px;
    color: #f8fafc;
    font-family: inherit;
    outline: none;
  }}
  input[type="text"]::placeholder {{
    color: #475569;
  }}

  button[type="submit"] {{
    padding: 16px 36px;
    font-size: 16px;
    font-weight: 800;
    color: #090d16;
    background: linear-gradient(135deg, #06b6d4 0%, #3b82f6 50%, #a855f7 100%);
    background-size: 200% 200%;
    border: none;
    border-radius: 14px;
    cursor: pointer;
    transition: all 0.3s ease;
    white-space: nowrap;
    box-shadow: 0 4px 20px rgba(6, 182, 212, 0.4);
  }}
  button[type="submit"]:hover {{
    transform: translateY(-2px);
    box-shadow: 0 8px 30px rgba(168, 85, 247, 0.5);
    background-position: right center;
  }}
  button[type="submit"]:disabled {{
    opacity: 0.5;
    cursor: not-allowed;
    transform: none;
  }}

  .loading {{
    display: none;
    text-align: center;
    padding: 24px;
    background: rgba(15, 23, 42, 0.6);
    border-radius: 16px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    margin-top: 20px;
  }}
  .loading.show {{ display: block; }}
  .spinner {{
    border: 3px solid rgba(255, 255, 255, 0.1);
    border-top: 3px solid #06b6d4;
    border-right: 3px solid #a855f7;
    border-radius: 50%;
    width: 44px; height: 44px;
    animation: spin 0.8s cubic-bezier(0.68, -0.55, 0.27, 1.55) infinite;
    margin: 0 auto 14px;
  }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}

  #status-text {{
    font-size: 15px;
    font-weight: 600;
    color: #38bdf8;
    min-height: 24px;
  }}

  .section-divider {{
    margin-top: 36px;
    padding-top: 28px;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
  }}

  .section-title {{
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: #64748b;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 6px;
  }}

  .genz-pills {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }}

  .genz-pill {{
    padding: 8px 16px;
    background: rgba(30, 41, 59, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 12px;
    font-size: 14px;
    font-weight: 600;
    color: #e2e8f0;
    text-decoration: none;
    transition: all 0.2s ease;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }}
  .genz-pill:hover {{
    background: rgba(51, 65, 85, 0.9);
    border-color: #a855f7;
    color: #ffffff;
    transform: translateY(-2px);
    box-shadow: 0 4px 14px rgba(168, 85, 247, 0.25);
  }}

  .grid-checks {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 14px;
    margin-top: 16px;
  }}

  .check-card {{
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    padding: 16px;
    transition: all 0.2s ease;
  }}
  .check-card:hover {{
    border-color: rgba(255, 255, 255, 0.2);
    background: rgba(30, 41, 59, 0.5);
  }}
  .check-card h4 {{
    font-size: 15px;
    color: #f1f5f9;
    margin-bottom: 6px;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .check-card p {{
    font-size: 13px;
    color: #94a3b8;
    line-height: 1.5;
  }}

  .footer-tag {{
    text-align: center;
    margin-top: 28px;
    font-size: 13px;
    color: #475569;
    font-weight: 600;
  }}
</style>
</head>
<body>

<div class="badge-top">
  ⚡ Next-Gen AI Visibility Audit • No Cap
</div>

<div class="card">
  <div class="logo-bar">
    <span class="logo-icon">🚀</span>
    <span style="font-weight: 800; font-size: 18px; letter-spacing: -0.5px; color: #94a3b8;">GEO AUDITOR</span>
  </div>

  <h1>Are You Main Character in AI Search or Ghosted? 👻</h1>
  <p class="subtitle">
    ChatGPT, Perplexity, Claude & Gemini are answering user questions right now.
    We check if your site gets <span class="highlight-text">cited</span> or completely slept on. 💯
  </p>

  <form id="auditForm" onsubmit="startAudit(event)">
    <div class="input-container">
      <input type="text" id="urlInput" placeholder="Enter site domain (e.g. stripe.com)" required autofocus>
      <button type="submit" id="auditBtn">Audit Site ✨</button>
    </div>
  </form>

  <div class="loading" id="loading">
    <div class="spinner"></div>
    <p id="status-text">Cooking up your audit...</p>
  </div>

  <div class="section-divider">
    <div class="section-title">⚡ Instant Pre-Generated Audits</div>
    <div class="genz-pills">
      {example_links or '<span style="font-size:13px;color:#64748b">No pre-generated reports available</span>'}
    </div>

    <div class="section-title" style="margin-top: 20px;">🔥 Live Demo Quick Hits</div>
    <div class="genz-pills">
      <a href="#" class="genz-pill" onclick="document.getElementById('urlInput').value='stripe.com';return false;">💳 stripe.com</a>
      <a href="#" class="genz-pill" onclick="document.getElementById('urlInput').value='notion.so';return false;">📝 notion.so</a>
      <a href="#" class="genz-pill" onclick="document.getElementById('urlInput').value='linear.app';return false;">⚡ linear.app</a>
    </div>
  </div>

  <div class="section-divider">
    <div class="section-title">🔮 What We Check Under The Hood</div>
    <div class="grid-checks">
      <div class="check-card">
        <h4>🤖 AI Crawlability</h4>
        <p>Checks if GPTBot, ClaudeBot & Perplexity agents are blocked in your robots.txt or sitemaps.</p>
      </div>
      <div class="check-card">
        <h4>🧠 Content Answerability</h4>
        <p>LLM evaluation on direct answer clarity, stats, facts, citations and schema structure.</p>
      </div>
      <div class="check-card">
        <h4>🏷️ Structured Data</h4>
        <p>Verifies JSON-LD machine readability, OpenGraph tags, and semantic hierarchy.</p>
      </div>
      <div class="check-card">
        <h4>🎯 Live AI Brand Recall</h4>
        <p>Queries AI models in real time to see if your brand is recommended for industry questions.</p>
      </div>
      <div class="check-card" style="grid-column: 1 / -1;">
        <h4>👁️ AI Visibility & Competitive Intelligence</h4>
        <p>Checks 7 key search platforms (Reddit, Wikipedia, G2, YouTube...), positioning accuracy, share of voice vs competitors, and vector search embedding inclusion.</p>
      </div>
    </div>
  </div>
</div>

<div class="footer-tag">
  Built for the AI Search Era • GEO Auditor v0.2.0 ✨
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
          ' <br><a href="/" style="color:#06b6d4; margin-top: 8px; display: inline-block;">← Try again</a>';
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
