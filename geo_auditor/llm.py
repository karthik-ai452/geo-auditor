"""OpenAI-compatible LLM client for the content answerability judge.

Uses the project's OpenAI-compatible gateway (create_openai_api_key).
The LLM acts as a judge to assess how well a page's content answers
questions the way an AI search engine would extract and cite.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)


def _get_client() -> OpenAI:
    """Create an OpenAI client pointing at the configured gateway."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://llm.drytis.ai")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. The content answerability check "
            "requires an LLM. Set OPENAI_API_KEY in your environment."
        )
    return OpenAI(api_key=api_key, base_url=base_url)


# The model to use for judging.
# These names are validated at runtime; if unavailable we fall back.
PREFERRED_MODELS = ["drytis/kimi-k2.5", "drytis/kimi-k3", "drytis/kimi"]


def _resolve_model(client: OpenAI) -> str:
    """Pick an available model from the gateway."""
    try:
        resp = client.models.list()
        available = {m.id for m in resp.data}
        for model in PREFERRED_MODELS:
            if model in available:
                return model
        # If none of our preferred, use the first available
        if available:
            return sorted(available)[0]
    except Exception as e:
        logger.warning(f"Could not list models: {e}")
    return "gpt-4o-mini"  # fallback


JUDGE_SYSTEM_PROMPT = """\
You are an expert evaluator for Generative Engine Optimization (GEO).
Your job is to assess how well a web page's content would perform in
AI-powered search engines (ChatGPT, Perplexity, Claude, Google AI Overviews).

AI search engines select and cite sources based on:
1. Whether the content directly answers questions with clear, definitional statements
2. Whether it contains specific statistics and data points (these are highly cited)
3. Whether it cites sources and provides evidence for claims
4. Whether the content is structured with clear sections and headings
5. Whether it uses natural, conversational language that matches how people ask questions

Score each signal from 0-100 and provide specific, evidence-backed reasoning.
Return ONLY valid JSON — no markdown, no explanation outside the JSON."""

JUDGE_USER_TEMPLATE = """\
Analyze this web page content for AI search engine answerability.

URL: {url}
Page Title: {title}

CONTENT (first 8000 chars):
{content}

Extracted signals:
- Statistics found: {stats_count}
- Definition/answer patterns: {has_definition}
- Citation patterns: {has_citations}
- Word count: {word_count}
- Has FAQ schema: {has_faq_schema}
- H2 headings: {h2_count}

Evaluate this content on a 0-100 scale across these dimensions.
For each dimension, cite specific examples from the content as evidence.

Return JSON with this exact structure:
{{
  "direct_answers": {{
    "score": 0-100,
    "reasoning": "specific evidence from the content",
    "example": "a quote or paraphrase from the content"
  }},
  "statistical_richness": {{
    "score": 0-100,
    "reasoning": "...",
    "example": "..."
  }},
  "citation_quality": {{
    "score": 0-100,
    "reasoning": "...",
    "example": "..."
  }},
  "structure_clarity": {{
    "score": 0-100,
    "reasoning": "...",
    "example": "..."
  }},
  "conversational_match": {{
    "score": 0-100,
    "reasoning": "...",
    "example": "..."
  }},
  "overall_assessment": "2-3 sentence summary of how this content would perform in AI search",
  "top_suggestion": "the single most impactful improvement"
}}"""


def judge_content(
    url: str,
    title: str,
    content: str,
    stats_count: int,
    has_definition: bool,
    has_citations: bool,
    word_count: int,
    has_faq_schema: bool,
    h2_count: int,
) -> dict[str, Any]:
    """Run the LLM judge on page content. Returns structured scores.

    Raises RuntimeError if the LLM call fails.
    """
    client = _get_client()
    model = _resolve_model(client)

    # Truncate content for the prompt
    truncated = content[:8000]

    user_msg = JUDGE_USER_TEMPLATE.format(
        url=url,
        title=title or "(no title)",
        content=truncated,
        stats_count=stats_count,
        has_definition=has_definition,
        has_citations=has_citations,
        word_count=word_count,
        has_faq_schema=has_faq_schema,
        h2_count=h2_count,
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,  # low temperature for consistency
            max_tokens=1200,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON: {e}")
        raise RuntimeError(f"LLM judge returned invalid JSON: {e}")
    except Exception as e:
        logger.error(f"LLM judge call failed: {e}")
        raise RuntimeError(f"LLM judge call failed: {e}")


def get_model_name() -> str:
    """Return the model name for reporting purposes."""
    return "drytis/kimi-k2.5"  # matches _resolve_model fallback
