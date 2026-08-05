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


# ---------------------------------------------------------------------------
# Brand Recall — test whether an LLM actually knows about the business
# ---------------------------------------------------------------------------

BRAND_RECALL_SYSTEM_PROMPT = """\
You are helping evaluate whether a business is visible in AI search engines.
You will be asked questions about various businesses. Answer each question \
naturally, as you would in a real conversation with a user.

IMPORTANT: Answer based on your own knowledge. Do not say "I don't know" \
unless you genuinely have no knowledge of the topic. List specific companies, \
products, and tools when asked for recommendations or comparisons.
"""


def generate_brand_recall_queries(
    brand: str, category: str, competitors: list[str] | None = None
) -> list[dict[str, str]]:
    """Generate a set of queries to test brand recall.

    Returns a list of {query, type, description} dicts.
    """
    queries = []

    # 1. Category queries — does the brand come up unprompted?
    queries.append({
        "query": f"What are the best {category} platforms for businesses?",
        "type": "category_unprompted",
        "description": f"When asked about {category}, does the AI mention {brand}?"
    })

    queries.append({
        "query": f"What are the top {category} companies or tools?",
        "type": "category_unprompted",
        "description": f"When asked about top {category} tools, does the AI mention {brand}?"
    })

    # 2. Comparison queries — does the brand come up in comparisons?
    queries.append({
        "query": f"Can you compare the top {category} platforms and their key features?",
        "type": "comparison",
        "description": f"In a {category} comparison, does the AI mention {brand}?"
    })

    # 3. Competitor-anchored queries
    if competitors:
        queries.append({
            "query": f"What are the main alternatives to {competitors[0]} for {category}?",
            "type": "competitor_anchored",
            "description": f"Asking for alternatives to {competitors[0]} — does the AI mention {brand}?"
        })

    return queries


def query_brand_recall(
    query: str,
) -> str:
    """Send a single brand recall query to the LLM. Returns the response text.

    Raises RuntimeError if the LLM call fails.
    """
    client = _get_client()
    model = _resolve_model(client)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": BRAND_RECALL_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.5,
            max_tokens=800,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"Brand recall query failed: {e}")
        raise RuntimeError(f"Brand recall query failed: {e}")


BRAND_MENTION_CHECK_SYSTEM_PROMPT = """\
You are an evaluator. You will be given an AI's response to a user's question \
and the name of a specific business. Your job is to determine whether the \
business is mentioned in the response.

Return ONLY valid JSON with this structure:
{
  "mentioned": true/false,
  "how_mentioned": "exact quote or description of how the brand appears",
  "context": "positive / neutral / negative / not_mentioned",
  "position": "first_quarter / second_quarter / third_quarter / fourth_quarter / not_mentioned"
}
"""


def check_brand_mention(
    brand: str, brand_aliases: list[str], ai_response: str
) -> dict:
    """Use the LLM to check whether a brand is mentioned in an AI response.

    Returns {mentioned, how_mentioned, context, position}.
    Falls back to simple text matching if LLM unavailable.
    """
    # First, try a fast text match — covers most cases without an LLM call
    all_names = [brand.lower()] + [a.lower() for a in brand_aliases]
    response_lower = ai_response.lower()
    text_mentioned = any(name in response_lower for name in all_names if len(name) > 2)

    # If text match found, get details from LLM for richer reporting
    if text_mentioned or len(ai_response) > 20:
        try:
            client = _get_client()
            model = _resolve_model(client)

            user_msg = (
                f"Business to check: {brand}\n"
                f"Also known as: {', '.join(brand_aliases) if brand_aliases else 'N/A'}\n\n"
                f"AI response:\n{ai_response[:3000]}\n\n"
                f"Is {brand} mentioned in this response? "
                f"Evaluate and return JSON."
            )

            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": BRAND_MENTION_CHECK_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
            result = json.loads(resp.choices[0].message.content)
            return result
        except Exception as e:
            logger.warning(f"Brand mention LLM check failed, using text match: {e}")

    # Fallback: text matching only
    if text_mentioned:
        # Find position
        words = ai_response.split()
        total_words = len(words)
        for name in all_names:
            for i, word in enumerate(words):
                if name in word.lower():
                    quarter_idx = i / max(total_words, 1)
                    if quarter_idx < 0.25:
                        position = "first_quarter"
                    elif quarter_idx < 0.5:
                        position = "second_quarter"
                    elif quarter_idx < 0.75:
                        position = "third_quarter"
                    else:
                        position = "fourth_quarter"
                    return {
                        "mentioned": True,
                        "how_mentioned": f"Found '{name}' in the text",
                        "context": "neutral",
                        "position": position,
                    }
    return {
        "mentioned": False,
        "how_mentioned": "",
        "context": "not_mentioned",
        "position": "not_mentioned",
    }
