"""Cognitive reasoning and LLM orchestration engine with strict anti-hallucination verification."""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from config.constants import (
    DEFAULT_RECOMMENDATIONS_COUNT,
    MAX_RECOMMENDATIONS_COUNT,
    MAX_RATIONALE_LENGTH,
)
from config.settings import settings
from src.models.schema import (
    UserPreferences,
    RestaurantCandidate,
    RestaurantRecommendation,
    RecommendationResponse,
)
from src.prompts.templates import (
    SYSTEM_PROMPT,
    build_user_prompt,
)
from src.engine.filter import filter_restaurants

logger = logging.getLogger(__name__)


def validate_grounding(
    raw_recommendations: List[RestaurantRecommendation],
    candidates: List[RestaurantCandidate],
    target_count: int = DEFAULT_RECOMMENDATIONS_COUNT,
) -> List[RestaurantRecommendation]:
    """Anti-hallucination verification asserting all recommendations match retrieved candidates.
    
    1. Checks if each recommendation's ID or name exists in the candidate pool.
    2. Overwrites factual and numerical attributes from the canonical dataset record
       to prevent attribute drift / mutation.
    3. Truncates rationales to MAX_RATIONALE_LENGTH.
    4. Automatically backfills from top candidates if hallucinations were caught and rejected.
    """
    if not candidates:
        return []

    id_to_candidate: Dict[str, RestaurantCandidate] = {c.restaurant_id: c for c in candidates}
    name_to_candidate: Dict[str, RestaurantCandidate] = {c.name.strip().lower(): c for c in candidates}

    verified: List[RestaurantRecommendation] = []
    seen_ids: Set[str] = set()

    for rec in raw_recommendations:
        candidate: Optional[RestaurantCandidate] = None

        # Match 1: Exact restaurant_id match
        if rec.restaurant_id in id_to_candidate:
            candidate = id_to_candidate[rec.restaurant_id]
        # Match 2: Name match (auto-corrects hallucinated or swapped ID)
        elif rec.restaurant_name.strip().lower() in name_to_candidate:
            candidate = name_to_candidate[rec.restaurant_name.strip().lower()]
            logger.info(
                "Auto-corrected mismatched ID for '%s': was '%s', corrected to '%s'",
                rec.restaurant_name,
                rec.restaurant_id,
                candidate.restaurant_id,
            )
        else:
            logger.warning(
                "Anti-hallucination rejection: restaurant '%s' (ID: '%s') not in candidate pool",
                rec.restaurant_name,
                rec.restaurant_id,
            )
            continue

        if candidate.restaurant_id in seen_ids:
            continue
        seen_ids.add(candidate.restaurant_id)

        # Enforce canonical metadata directly from source dataset record
        clean_rec = RestaurantRecommendation(
            restaurant_id=candidate.restaurant_id,
            restaurant_name=candidate.name,
            cuisine=", ".join(candidate.cuisines),
            rating=candidate.rating,
            estimated_cost_for_two=f"₹{candidate.cost_for_two:,} ({candidate.budget_tier.value.capitalize()})",
            recommendation_reason=rec.recommendation_reason.strip()[:MAX_RATIONALE_LENGTH],
        )
        verified.append(clean_rec)

    # If verification left fewer than target count, backfill from remaining top candidates
    max_needed = min(len(candidates), target_count)
    if len(verified) < max_needed:
        for c in candidates:
            if c.restaurant_id not in seen_ids:
                seen_ids.add(c.restaurant_id)
                features_str = f" featuring {', '.join(c.highlights[:2])}" if c.highlights else ""
                fallback_reason = (
                    f"{c.name} in {c.locality} is a top-rated choice ({c.rating}★, {c.votes} votes) "
                    f"serving {', '.join(c.cuisines[:2])}{features_str}."
                )[:MAX_RATIONALE_LENGTH]

                verified.append(
                    RestaurantRecommendation(
                        restaurant_id=c.restaurant_id,
                        restaurant_name=c.name,
                        cuisine=", ".join(c.cuisines),
                        rating=c.rating,
                        estimated_cost_for_two=f"₹{c.cost_for_two:,} ({c.budget_tier.value.capitalize()})",
                        recommendation_reason=fallback_reason,
                    )
                )
                if len(verified) >= max_needed:
                    break

    return verified[:target_count]


def generate_deterministic_recommendations(
    preferences: UserPreferences,
    candidates: List[RestaurantCandidate],
    relaxation_applied: bool = False,
    relaxation_message: Optional[str] = None,
) -> RecommendationResponse:
    """Generate high-quality grounded recommendations programmatically when LLM is unavailable."""
    target_count = min(len(candidates), preferences.max_recommendations)
    verified = validate_grounding([], candidates, target_count=target_count)

    cuisines_str = ", ".join(c.title() for c in preferences.cuisines)
    location_str = preferences.location.title()
    query_summary = f"Curated {cuisines_str} dining in {location_str} with {preferences.budget_tier.value} budget"
    if preferences.additional_notes:
        query_summary += f" ({preferences.additional_notes.strip()[:60]})"

    return RecommendationResponse(
        query_summary=query_summary,
        total_candidates_analyzed=len(candidates),
        relaxation_applied=relaxation_applied,
        relaxation_message=relaxation_message,
        recommendations=verified,
    )


def extract_json_payload(raw_text: str) -> str:
    """Extract valid JSON substring from LLM response text."""
    # First attempt: search for json fenced code block
    match_code = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if match_code:
        return match_code.group(1).strip()

    # Second attempt: search for outermost JSON object
    match_braces = re.search(r"(\{.*\})", raw_text, re.DOTALL)
    if match_braces:
        return match_braces.group(1).strip()

    return raw_text.strip()


def call_gemini(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model_name: str,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    custom_client: Optional[Any] = None,
) -> RecommendationResponse:
    """Invoke Google Gemini using official google.genai structured outputs."""
    if custom_client is not None:
        client = custom_client
    else:
        from google import genai
        client = genai.Client(api_key=api_key)

    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=temperature,
        max_output_tokens=max_tokens,
        response_mime_type="application/json",
        response_schema=RecommendationResponse,
    )

    response = client.models.generate_content(
        model=model_name,
        contents=user_prompt,
        config=config,
    )

    # In modern google.genai with response_schema, response.parsed or json in response.text
    if hasattr(response, "parsed") and response.parsed is not None:
        if isinstance(response.parsed, RecommendationResponse):
            return response.parsed
        return RecommendationResponse.model_validate(response.parsed)

    json_str = extract_json_payload(response.text)
    return RecommendationResponse.model_validate_json(json_str)


def call_openai(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model_name: str,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    custom_client: Optional[Any] = None,
) -> RecommendationResponse:
    """Invoke OpenAI using beta.chat.completions.parse structured outputs."""
    if custom_client is not None:
        client = custom_client
    else:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

    completion = client.beta.chat.completions.parse(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=RecommendationResponse,
    )

    message = completion.choices[0].message
    if hasattr(message, "parsed") and message.parsed is not None:
        return message.parsed

    json_str = extract_json_payload(message.content or "{}")
    return RecommendationResponse.model_validate_json(json_str)


def call_groq(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model_name: str,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    custom_client: Optional[Any] = None,
) -> RecommendationResponse:
    """Invoke Groq LLM using the Groq SDK with JSON mode structured outputs.
    
    Groq's LPU™ engine provides sub-second inference. JSON mode is used because
    Groq does not yet support native response_schema enforcement.
    """
    if custom_client is not None:
        client = custom_client
    else:
        from groq import Groq
        client = Groq(api_key=api_key)

    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )

    raw_content = completion.choices[0].message.content or "{}"
    json_str = extract_json_payload(raw_content)
    return RecommendationResponse.model_validate_json(json_str)



@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=6),
    retry=retry_if_exception_type((Exception,)),
    reraise=True,
)
def invoke_llm_with_retry(
    provider: str,
    system_prompt: str,
    user_prompt: str,
    llm_client: Optional[Any] = None,
) -> RecommendationResponse:
    """Invoke LLM provider with exponential backoff retry on transient failures."""
    provider_clean = provider.strip().lower()

    if provider_clean == "groq":
        api_key = settings.GROQ_API_KEY
        model_name = settings.GROQ_MODEL
        return call_groq(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            model_name=model_name,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_OUTPUT_TOKENS,
            custom_client=llm_client,
        )
    elif provider_clean == "gemini":
        api_key = settings.GEMINI_API_KEY
        model_name = settings.GEMINI_MODEL
        return call_gemini(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            model_name=model_name,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_OUTPUT_TOKENS,
            custom_client=llm_client,
        )
    elif provider_clean in ("openai", "gpt"):
        api_key = settings.OPENAI_API_KEY
        model_name = settings.OPENAI_MODEL
        return call_openai(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            model_name=model_name,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_OUTPUT_TOKENS,
            custom_client=llm_client,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


def generate_recommendations(
    preferences: UserPreferences,
    candidates: List[RestaurantCandidate],
    relaxation_applied: bool = False,
    relaxation_message: Optional[str] = None,
    provider: Optional[str] = None,
    llm_client: Optional[Any] = None,
) -> RecommendationResponse:
    """Generate grounded, cognitive recommendations matching user preferences.
    
    1. Returns empty response immediately if candidates list is empty.
    2. Builds optimized prompts and invokes configured LLM.
    3. Programmatically enforces anti-hallucination verification.
    4. Gracefully degrades to deterministic recommendations if LLM key is absent or API fails.
    """
    if not candidates:
        cuisines_str = ", ".join(preferences.cuisines)
        return RecommendationResponse(
            query_summary=f"No matching restaurants found for {cuisines_str} in {preferences.location}",
            total_candidates_analyzed=0,
            relaxation_applied=relaxation_applied,
            relaxation_message=relaxation_message,
            recommendations=[],
        )

    selected_provider = (provider or settings.DEFAULT_LLM_PROVIDER).strip().lower()

    # Check whether an API key is available for the selected provider
    has_api_key = False
    if llm_client is not None:
        has_api_key = True
    elif selected_provider == "groq" and settings.GROQ_API_KEY:
        has_api_key = True
    elif selected_provider == "gemini" and settings.GEMINI_API_KEY:
        has_api_key = True
    elif selected_provider in ("openai", "gpt") and settings.OPENAI_API_KEY:
        has_api_key = True

    if not has_api_key:
        logger.info(
            "No API key configured for provider '%s'. Operating in deterministic grounded mode.",
            selected_provider,
        )
        return generate_deterministic_recommendations(
            preferences=preferences,
            candidates=candidates,
            relaxation_applied=relaxation_applied,
            relaxation_message=relaxation_message,
        )

    # Build prompts
    target_count = min(len(candidates), preferences.max_recommendations)
    system_prompt = SYSTEM_PROMPT.format(requested_count=target_count)
    user_prompt = build_user_prompt(preferences, candidates, relaxation_message=relaxation_message)

    try:
        raw_response = invoke_llm_with_retry(
            provider=selected_provider,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            llm_client=llm_client,
        )

        # Anti-Hallucination Grounding Verification
        verified_recs = validate_grounding(
            raw_recommendations=raw_response.recommendations,
            candidates=candidates,
            target_count=target_count,
        )

        return RecommendationResponse(
            query_summary=raw_response.query_summary,
            total_candidates_analyzed=len(candidates),
            relaxation_applied=relaxation_applied,
            relaxation_message=relaxation_message,
            recommendations=verified_recs,
        )

    except Exception as exc:
        logger.error(
            "LLM invocation failed after retries (%s: %s). Falling back to deterministic recommendations.",
            type(exc).__name__,
            exc,
        )
        return generate_deterministic_recommendations(
            preferences=preferences,
            candidates=candidates,
            relaxation_applied=relaxation_applied,
            relaxation_message=relaxation_message,
        )


def recommend(
    preferences: UserPreferences,
    df: Optional[pd.DataFrame] = None,
    provider: Optional[str] = None,
    llm_client: Optional[Any] = None,
) -> RecommendationResponse:
    """Execute end-to-end recommendation pipeline: Filter -> LLM Reasoning -> Verify Grounding."""
    if df is None:
        from src.data.preprocessor import load_processed_data
        df = load_processed_data()

    candidates, relaxed, rel_msg, _ = filter_restaurants(df, preferences)

    return generate_recommendations(
        preferences=preferences,
        candidates=candidates,
        relaxation_applied=relaxed,
        relaxation_message=rel_msg,
        provider=provider,
        llm_client=llm_client,
    )
