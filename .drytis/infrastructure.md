# GEO Auditor — Infrastructure

## Web App
- Port: 8000 (uvicorn)
- Caddy proxy: reverse_proxy at / → localhost:8000

## Background Service
- `uvicorn geo_auditor.web.app:app --host 0.0.0.0 --port 8000`
- Registered via add_background_service

## Environment Variables
- OPENAI_API_KEY — LLM gateway key (secret)
- OPENAI_BASE_URL — LLM gateway base URL
- All other config is hardcoded defaults (no DB needed)

## Setup Script
- pip install -r requirements.txt
- (no build step, no migrations)

## Notes
- Stateless app, no database required
- Reports saved to /workspace/reports/
