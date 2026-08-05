"""Shared analyzer helpers."""

from __future__ import annotations


def analyze_robots_fix(bot: str) -> str:
    """Generate a copy-pasteable robots.txt fix for a blocked bot."""
    return (
        f"To allow {bot}, add or modify this in your /robots.txt:\n\n"
        f"User-agent: {bot}\n"
        f"Allow: /\n\n"
        f"Or simply remove the 'Disallow: /' rule under 'User-agent: {bot}'.\n"
        f"If your bot blocking is done by a WordPress/plugin security tool "
        f"(e.g. Wordfence, Cloudflare bot management), check those settings too."
    )
