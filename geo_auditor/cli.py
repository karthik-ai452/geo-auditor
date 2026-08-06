"""CLI entry point for GEO Auditor.

Usage:
    python -m geo_auditor audit <url> [--output-dir DIR]
    python -m geo_auditor audit <url>  # saves to reports/
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


app = typer.Typer(
    name="geo-auditor",
    help="GEO Auditor — check how visible your business is in AI search.",
    no_args_is_help=True,
)


@app.command()
def audit(
    url: str = typer.Argument(..., help="Website URL to audit (e.g. example.com)"),
    output_dir: Path = typer.Option(
        Path("reports"),
        "--output-dir", "-o",
        help="Directory to save the report (default: reports/)",
    ),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Skip the LLM judge and use rule-based scoring only.",
    ),
):
    """Run a GEO audit on a website."""
    if no_llm:
        import os
        os.environ["OPENAI_API_KEY"] = ""
        os.environ["OPENAI_BASE_URL"] = ""

    from geo_auditor.audit import run_audit

    try:
        asyncio.run(run_audit(url, output_dir))
    except KeyboardInterrupt:
        print("\n\nAudit cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Audit failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@app.command()
def version():
    """Show version."""
    from geo_auditor import __version__
    print(f"GEO Auditor v{__version__}")


if __name__ == "__main__":
    app()
