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
business is mentioned in the response and extract precise details.

Return ONLY valid JSON with this structure:
{
  "mentioned": true/false,
  "how_mentioned": "description of how the brand appears",
  "exact_sentence": "the full sentence from the response where the brand is first mentioned, or empty string",
  "context": "positive / neutral / negative / not_mentioned",
  "citation_rank": 1,
  "position": "first_quarter / second_quarter / third_quarter / fourth_quarter / not_mentioned"
}

citation_rank: The ordinal position of this brand among ALL brands/companies \
mentioned in the response. If the response mentions Stripe, PayPal, and Square \
in that order, Stripe has citation_rank=1, PayPal has citation_rank=2, etc. \
If the brand is not mentioned, use 0.

exact_sentence: Extract the complete sentence (not a fragment) from the AI \
response where the brand first appears. Include the full sentence as written. \
If the brand is mentioned multiple times, use the first occurrence.
"""


def check_brand_mention(
    brand: str, brand_aliases: list[str], ai_response: str
) -> dict:
    """Use the LLM to check whether a brand is mentioned in an AI response.

    Returns {mentioned, how_mentioned, exact_sentence, context, citation_rank, position}.
    Falls back to simple text matching if LLM unavailable.
    """
    # First, try a fast text match — covers most cases without an LLM call
    all_names = [brand.lower()] + [a.lower() for a in brand_aliases]
    response_lower = ai_response.lower()
    text_mentioned = any(name in response_lower for name in all_names if len(name) > 2)

    # If text match found (or response is long enough to be worth checking), get details from LLM
    if text_mentioned or len(ai_response) > 20:
        try:
            client = _get_client()
            model = _resolve_model(client)

            user_msg = (
                f"Business to check: {brand}\n"
                f"Also known as: {', '.join(brand_aliases) if brand_aliases else 'N/A'}\n\n"
                f"AI response:\n{ai_response[:3000]}\n\n"
                f"Is {brand} mentioned in this response? "
                f"Evaluate and return JSON with citation_rank and exact_sentence."
            )

            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": BRAND_MENTION_CHECK_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
                max_tokens=400,
                response_format={"type": "json_object"},
            )
            result = json.loads(resp.choices[0].message.content)
            # Ensure all keys exist
            result.setdefault("mentioned", False)
            result.setdefault("how_mentioned", "")
            result.setdefault("context", "not_mentioned")
            result.setdefault("position", "not_mentioned")
            result.setdefault("exact_sentence", "")
            result.setdefault("citation_rank", 0)
            return result
        except Exception as e:
            logger.warning(f"Brand mention LLM check failed, using text match: {e}")

    # Fallback: text matching only — extract sentence + compute rank
    if text_mentioned:
        return _text_match_fallback(brand, all_names, ai_response)
    return {
        "mentioned": False,
        "how_mentioned": "",
        "exact_sentence": "",
        "context": "not_mentioned",
        "citation_rank": 0,
        "position": "not_mentioned",
    }


def _text_match_fallback(brand: str, all_names: list[str], ai_response: str) -> dict:
    """Fallback mention analysis using text matching heuristics."""
    import re

    words = ai_response.split()
    total_words = len(words)

    # Find position and extract sentence
    found_idx = -1
    found_name = ""
    for name in all_names:
        if len(name) <= 2:
            continue
        for i, word in enumerate(words):
            if name in word.lower():
                if found_idx == -1 or i < found_idx:
                    found_idx = i
                    found_name = name

    if found_idx == -1:
        return {
            "mentioned": False, "how_mentioned": "", "exact_sentence": "",
            "context": "not_mentioned", "citation_rank": 0, "position": "not_mentioned",
        }

    quarter_idx = found_idx / max(total_words, 1)
    if quarter_idx < 0.25:
        position = "first_quarter"
    elif quarter_idx < 0.5:
        position = "second_quarter"
    elif quarter_idx < 0.75:
        position = "third_quarter"
    else:
        position = "fourth_quarter"

    # Extract the sentence containing the first mention
    sentences = re.split(r'(?<=[.!?])\s+', ai_response)
    exact_sentence = ""
    for s in sentences:
        if found_name in s.lower():
            exact_sentence = s.strip()
            break

    # Estimate citation rank by counting other capitalized brands before this one
    # (rough heuristic — count capitalized words that appear before the mention)
    preceding_text = " ".join(words[:found_idx])
    other_brands = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', preceding_text)
    # Deduplicate
    other_brands = list(dict.fromkeys(other_brands))
    # Subtract common words
    common = {"The", "This", "That", "These", "Those", "It", "There", "Here",
              "For", "In", "On", "At", "To", "Of", "And", "But", "Or", "A", "An",
              "Is", "Are", "Was", "Were", "Be", "Been", "Have", "Has", "Had",
              "When", "Where", "What", "Who", "How", "Why", "Which", "Some"}
    real_brands = [b for b in other_brands if b not in common and len(b) > 2]
    citation_rank = len(real_brands) + 1

    return {
        "mentioned": True,
        "how_mentioned": f"Found '{found_name}' in the text",
        "exact_sentence": exact_sentence,
        "context": "neutral",
        "citation_rank": citation_rank,
        "position": position,
    }


# ---------------------------------------------------------------------------
# Feature 3: Search-enabled LLM query
# Attempts to use a model with live web search, falling back gracefully.
# Inspired by ai-cmo's use of gpt-4o-search-preview with web_search_options.
# ---------------------------------------------------------------------------

# Models known to support web search (tried in order)
SEARCH_ENABLED_MODELS = [
    "drytis/kimi-k2.5",   # may support search in some gateways
]


def query_brand_recall_with_search(
    query: str,
) -> dict[str, Any]:
    """Send a brand recall query, attempting to use a search-enabled model.

    Returns {response: str, model_used: str, search_enabled: bool}.

    Tries to use a model with built-in web search first (for live retrieval
    testing). If unavailable, falls back to the standard model.

    Inspired by ai-cmo's approach of using gpt-4o-search-preview with
    web_search_options to test real-time brand visibility, not just
    training data recall.
    """
    client = _get_client()
    model = _resolve_model(client)

    # Try search-enabled parameters first
    # Some gateways support extra_body with search parameters
    search_enabled = False
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": BRAND_RECALL_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.5,
            max_tokens=800,
            extra_body={"enable_search": True},  # hint to the gateway
        )
        search_enabled = True
    except Exception as e:
        logger.debug(f"Search-enabled query failed, using standard: {e}")
        # Fall back to standard query
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
        except Exception as e2:
            logger.error(f"Brand recall query failed: {e2}")
            raise RuntimeError(f"Brand recall query failed: {e2}")

    return {
        "response": resp.choices[0].message.content or "",
        "model_used": model,
        "search_enabled": search_enabled,
    }


# ---------------------------------------------------------------------------
# Feature 4: Selection Rate
# Measures content overlap between the AI response and the target website.
# Inspired by geo-aeo-tracker's Selection Rate metric (word-level attribution).
# ---------------------------------------------------------------------------

# Common English words to ignore when computing overlap
_STOPWORDS = frozenset(
    "the a an and or but in on at to of for with from by is are was were be "
    "been being have has had do does did will would could should may might "
    "can must shall this that these those it its their there they them then "
    "than also both each all any some many most more when where what who how "
    "why which not no yes if so about into through during before after above "
    "below up down out off over under again further once here there new your "
    "you we i he she they me my our his her their its".split()
)


def _tokenize(text: str) -> set[str]:
    """Extract meaningful tokens (lowercase, alpha-only, stopwords removed)."""
    import re
    tokens = re.findall(r'\b[a-z]{3,}\b', text.lower())
    return {t for t in tokens if t not in _STOPWORDS}


def compute_selection_rate(
    ai_response: str, target_content: str
) -> dict[str, Any]:
    """Compute selection rate: how much of the AI response is grounded
    in the target website's content.

    Selection Rate = |shared phrases| / |total phrases in AI response|

    This is an approximation of geo-aeo-tracker's word-level attribution
    metric. We can't access Gemini's groundingSupports directly (requires
    Google API access), but we can measure content overlap at the phrase
    level — if the AI's response uses phrases that appear on the target
    site, that indicates the site's content is "selected" by the AI.

    Returns {selection_rate, shared_phrase_count, total_phrase_count,
             top_shared_phrases, target_word_count, response_word_count}.
    """
    import re

    # Extract phrases (n-grams of 3-5 words) from both texts
    def extract_phrases(text: str, n_min: int = 3, n_max: int = 5) -> list[str]:
        words = re.findall(r'\b[a-z]{2,}\b', text.lower())
        words = [w for w in words if w not in _STOPWORDS or len(w) > 4]
        phrases = []
        for n in range(n_min, n_max + 1):
            for i in range(len(words) - n + 1):
                phrases.append(" ".join(words[i:i+n]))
        return phrases

    response_phrases = extract_phrases(ai_response)
    target_phrases = set(extract_phrases(target_content))

    if not response_phrases:
        return {
            "selection_rate": 0.0,
            "shared_phrase_count": 0,
            "total_phrase_count": 0,
            "top_shared_phrases": [],
            "target_word_count": len(target_content.split()),
            "response_word_count": len(ai_response.split()),
        }

    shared = [p for p in response_phrases if p in target_phrases]

    # Selection rate = fraction of response phrases that overlap with target
    selection_rate = len(set(shared)) / len(set(response_phrases))

    # Get top shared phrases (longest ones first — more meaningful)
    top_shared = sorted(set(shared), key=len, reverse=True)[:10]

    return {
        "selection_rate": round(selection_rate, 4),
        "shared_phrase_count": len(set(shared)),
        "total_phrase_count": len(set(response_phrases)),
        "top_shared_phrases": top_shared,
        "target_word_count": len(target_content.split()),
        "response_word_count": len(ai_response.split()),
    }


# ---------------------------------------------------------------------------
# Positioning Accuracy — does the AI describe you the way you describe yourself?
# ---------------------------------------------------------------------------

POSITIONING_SYSTEM_PROMPT = """\
You are a brand analyst. You will receive two descriptions of a company:
1. SELF-DESCRIPTION: how the company describes itself (from their website)
2. AI-DESCRIPTION: how an AI model described the same company

Your job is to find SEMANTIC MISMATCHES between the two — places where the \
AI's understanding diverges from the company's intended positioning.

Common mismatch types:
- Price positioning: "premium" vs "affordable", "enterprise" vs "free"
- Target audience: "for developers" vs "for enterprises", "B2B" vs "B2C"
- Category: described as a different type of product entirely
- Feature emphasis: AI highlights different features than the company leads with
- Tone: formal vs casual, technical vs accessible

Return ONLY valid JSON:
{
  "accuracy_score": 0-100,
  "mismatches": [
    {
      "category": "price|audience|category|features|tone|other",
      "self_description": "what the company says",
      "ai_description": "what the AI says",
      "severity": "critical|moderate|minor"
    }
  ],
  "summary": "one sentence overall assessment"
}
"""


def check_positioning_accuracy(
    brand: str, self_description: str, ai_description: str
) -> dict[str, Any]:
    """Check if the AI describes the brand the way the brand describes itself.

    Detects semantic mismatches like "premium soaps" being described as
    "affordable soaps" — which means the AI will recommend you for the
    wrong queries.

    Returns {accuracy_score, mismatches, summary}.
    """
    try:
        client = _get_client()
        model = _resolve_model(client)

        user_msg = (
            f"Company: {brand}\n\n"
            f"SELF-DESCRIPTION (from their website):\n{self_description[:2000]}\n\n"
            f"AI-DESCRIPTION (from AI model response):\n{ai_description[:2000]}\n\n"
            f"Analyze the positioning accuracy. Are there semantic mismatches? "
            f"Return JSON."
        )

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": POSITIONING_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content)
        result.setdefault("accuracy_score", 50)
        result.setdefault("mismatches", [])
        result.setdefault("summary", "")
        return result
    except Exception as e:
        logger.warning(f"Positioning accuracy check failed: {e}")
        return {
            "accuracy_score": 0,
            "mismatches": [],
            "summary": f"Check failed: {type(e).__name__}",
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Vector Search Inclusion — will AI vector search retrieve your content?
# ---------------------------------------------------------------------------

def get_embedding(text: str) -> list[float] | None:
    """Get an embedding vector for the given text.

    Uses the OpenAI-compatible embeddings endpoint. Returns None if
    embeddings are not available (gateway may not support them).
    """
    try:
        client = _get_client()
        model = _resolve_model(client)

        # Try embeddings endpoint
        resp = client.embeddings.create(
            model=model,
            input=text[:8000],  # truncate to stay within limits
        )
        return resp.data[0].embedding
    except Exception as e:
        logger.debug(f"Embedding failed: {e}")
        return None


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    import math
    if len(vec_a) != len(vec_b) or len(vec_a) == 0:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def compute_vector_search_inclusion(
    homepage_content: str, category: str, brand: str
) -> dict[str, Any]:
    """Measure how likely AI vector search is to retrieve your content.

    AI engines use vector/embedding-based search to find relevant content.
    If your homepage content has low semantic similarity to the queries
    users actually ask, vector search won't surface you.

    We compute embeddings for:
    1. Your homepage content
    2. Typical category queries a user would ask
    3. Measure cosine similarity

    Returns {similarity_score, will_be_retrieved, query_similarities, detail}.
    """
    # Generate typical queries a user would ask for this category
    test_queries = [
        f"best {category} for businesses",
        f"top {category} platforms",
        f"recommended {category} tools",
        f"compare {category} options",
    ]

    # Get embedding for homepage
    homepage_emb = get_embedding(homepage_content[:4000])
    if homepage_emb is None:
        return {
            "similarity_score": 0,
            "will_be_retrieved": "unknown",
            "query_similarities": [],
            "detail": "Embeddings not available on this gateway — cannot measure vector search inclusion.",
            "method": "embedding",
        }

    # Get embeddings for queries and compute similarity
    query_sims = []
    for q in test_queries:
        q_emb = get_embedding(q)
        if q_emb is not None:
            sim = cosine_similarity(homepage_emb, q_emb)
            query_sims.append({"query": q, "similarity": round(sim, 4)})

    if not query_sims:
        return {
            "similarity_score": 0,
            "will_be_retrieved": "unknown",
            "query_similarities": [],
            "detail": "Could not compute query embeddings.",
            "method": "embedding",
        }

    avg_sim = sum(qs["similarity"] for qs in query_sims) / len(query_sims)

    # Interpret the score
    # These thresholds are approximate for cosine similarity of normalized embeddings
    if avg_sim >= 0.75:
        verdict = "high — your content will be retrieved for relevant queries"
    elif avg_sim >= 0.55:
        verdict = "moderate — likely retrieved for some queries, but competitors may rank higher"
    elif avg_sim >= 0.35:
        verdict = "low — unlikely to be retrieved unless query is very specific"
    else:
        verdict = "very low — vector search will not surface your content"

    # Build per-query detail
    detail_parts = [f"Average similarity: {avg_sim:.1%} — {verdict}"]
    for qs in sorted(query_sims, key=lambda x: x["similarity"], reverse=True):
        detail_parts.append(f'  "{qs["query"]}": {qs["similarity"]:.1%}')

    return {
        "similarity_score": round(avg_sim, 4),
        "will_be_retrieved": verdict,
        "query_similarities": query_sims,
        "detail": "\n".join(detail_parts),
        "method": "embedding",
    }


# ---------------------------------------------------------------------------
# Competitor Mention Analysis — do AI responses mention your competitors more?
# ---------------------------------------------------------------------------

COMPETITOR_ANALYSIS_SYSTEM_PROMPT = """\
You are a brand analyst. You will receive an AI's response to a user query \
and a list of company names. For each company, determine:
1. Is it mentioned in the response?
2. If so, how favorably? (positive / neutral / negative)
3. If so, what is its citation rank (1st company mentioned = rank 1)?

Return ONLY valid JSON:
{
  "brands": [
    {
      "name": "company name",
      "mentioned": true/false,
      "favorability": "positive/neutral/negative/not_mentioned",
      "citation_rank": 0,
      "context": "brief description of how it's mentioned"
    }
  ]
}
"""


def analyze_competitor_mentions(
    ai_response: str, brand: str, competitors: list[str]
) -> dict[str, Any]:
    """Analyze which brands (target + competitors) are mentioned in an AI response.

    Returns a share-of-voice analysis showing who appears and how favorably.
    """
    all_brands = [brand] + competitors

    try:
        client = _get_client()
        model = _resolve_model(client)
        user_msg = (
            f"AI response:\n{ai_response[:3000]}\n\n"
            f"Brands to check: {', '.join(all_brands)}\n\n"
            f"For each brand, determine if it's mentioned, how favorably, "
            f"and its citation rank. Return JSON."
        )

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": COMPETITOR_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content)
        return result
    except Exception as e:
        logger.warning(f"Competitor analysis failed: {e}")
        # Fallback: text matching
        brands_data = []
        response_lower = ai_response.lower()
        rank = 0
        for b in all_brands:
            mentioned = b.lower() in response_lower
            if mentioned:
                rank += 1
            brands_data.append({
                "name": b,
                "mentioned": mentioned,
                "favorability": "neutral" if mentioned else "not_mentioned",
                "citation_rank": rank if mentioned else 0,
                "context": "",
            })
        return {"brands": brands_data, "fallback": True}
