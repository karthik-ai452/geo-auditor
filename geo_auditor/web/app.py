"""FastAPI web app for GEO Auditor.

Provides a simple web UI:
  GET  /          → form to enter a URL
  POST /audit     → run audit, return HTML report
  GET  /audit/<url> → run audit via GET (for sharing/linking)
"""

from __future__ import annotations

import asyncio
import html
import os
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from geo_auditor.audit import run_audit
from geo_auditor.report import render_report

app = FastAPI(title="GEO Auditor", version="0.1.0")

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Landing page with URL input form."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GEO Auditor — AI Search Visibility Checker</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    padding: 20px;
  }
  .card {
    background: white; border-radius: 24px; padding: 48px;
    max-width: 640px; width: 100%; box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  }
  .logo { font-size: 32px; margin-bottom: 8px; }
  h1 { font-size: 28px; color: #1e293b; margin-bottom: 8px; }
  .subtitle { color: #64748b; font-size: 16px; margin-bottom: 32px; line-height: 1.5; }
  form { display: flex; flex-direction: column; gap: 16px; }
  .input-group { display: flex; gap: 12px; }
  input[type="text"] {
    flex: 1; padding: 16px 20px; font-size: 16px; border: 2px solid #e2e8f0;
    border-radius: 12px; outline: none; transition: border-color 0.2s;
  }
  input[type="text"]:focus { border-color: #4f46e5; }
  button {
    padding: 16px 32px; font-size: 16px; font-weight: 600; color: white;
    background: #4f46e5; border: none; border-radius: 12px; cursor: pointer;
    transition: background 0.2s; white-space: nowrap;
  }
  button:hover { background: #4338ca; }
  button:disabled { background: #94a3b8; cursor: not-allowed; }
  .loading { display: none; text-align: center; padding: 20px; color: #64748b; }
  .loading.show { display: block; }
  .spinner {
    border: 3px solid #e2e8f0; border-top: 3px solid #4f46e5; border-radius: 50%;
    width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto 12px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .examples { margin-top: 24px; padding-top: 24px; border-top: 1px solid #e2e8f0; }
  .examples h3 { font-size: 14px; color: #64748b; margin-bottom: 8px; }
  .example-links { display: flex; flex-wrap: wrap; gap: 8px; }
  .example-links a {
    padding: 6px 14px; background: #f1f5f9; border-radius: 8px;
    font-size: 13px; color: #4f46e5; text-decoration: none; transition: background 0.2s;
  }
  .example-links a:hover { background: #e2e8f0; }
  .what-is { margin-top: 32px; padding: 20px; background: #f8fafc; border-radius: 12px; font-size: 14px; color: #64748b; }
  .what-is h3 { color: #1e293b; margin-bottom: 8px; font-size: 15px; }
  .what-is ul { margin-left: 18px; }
  .what-is li { margin-top: 4px; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">🔍</div>
  <h1>GEO Auditor</h1>
  <p class="subtitle">See how visible your business is in AI search.<br>
  ChatGPT, Perplexity, Claude, Google AI Overviews — are they citing you?</p>

  <form id="auditForm" action="/audit" method="POST">
    <div class="input-group">
      <input type="text" name="url" placeholder="example.com" required autofocus>
      <button type="submit">Audit →</button>
    </div>
  </form>

  <div class="loading" id="loading">
    <div class="spinner"></div>
    <p>Auditing... this takes 20-40 seconds.</p>
  </div>

  <div class="examples">
    <h3>Try a real site:</h3>
    <div class="example-links">
      <a href="#" onclick="document.querySelector('input[name=url]').value='stripe.com';return false;">stripe.com</a>
      <a href="#" onclick="document.querySelector('input[name=url]').value='notion.so';return false;">notion.so</a>
      <a href="#" onclick="document.querySelector('input[name=url]').value='linear.app';return false;">linear.app</a>
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
document.getElementById('auditForm').addEventListener('submit', function() {
  document.getElementById('loading').classList.add('show');
  document.querySelector('button').disabled = true;
});
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.post("/audit", response_class=HTMLResponse)
async def audit_post(url: str = Form(...)):
    """Run audit and return the HTML report."""
    return await _do_audit(url)


@app.get("/audit/{url:path}", response_class=HTMLResponse)
async def audit_get(url: str):
    """Run audit via GET for direct linking."""
    return await _do_audit(url)


async def _do_audit(url: str) -> HTMLResponse:
    """Run the audit and return the rendered report HTML."""
    try:
        result = await run_audit(url)
        llm_data = {}  # already incorporated into findings
        html = render_report(result, llm_data)
        return HTMLResponse(content=html)
    except Exception as e:
        error_html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Audit Error</title>
<style>
  body {{ font-family: -apple-system, sans-serif; text-align: center; padding: 60px; background: #f8fafc; }}
  .error {{ max-width: 500px; margin: 0 auto; background: white; padding: 40px; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
  h1 {{ color: #dc2626; margin-bottom: 16px; }}
  p {{ color: #64748b; line-height: 1.6; }}
  a {{ color: #4f46e5; text-decoration: none; }}
  code {{ background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 13px; }}
</style></head>
<body>
<div class="error">
  <h1>⚠️ Audit Failed</h1>
  <p>Could not audit <code>{html.escape(url)}</code></p>
  <p style="margin-top: 16px;"><strong>Error:</strong> {html.escape(str(e)[:300])}</p>
  <p style="margin-top: 24px;"><a href="/">← Try another URL</a></p>
</div>
</body></html>"""
        return HTMLResponse(content=error_html, status_code=500)
