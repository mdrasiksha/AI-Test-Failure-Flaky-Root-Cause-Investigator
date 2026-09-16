"""OpenAI-backed, optional root-cause investigation for deterministic evidence."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

import openai
from openai import OpenAI

from backend.config import max_ai_text_chars, openai_model
from backend.sanitizer import sanitize_evidence

ROOT_CAUSE_CATEGORIES = frozenset(
    {
        "synchronization",
        "locator",
        "application",
        "network",
        "environment",
        "test_data",
        "assertion",
        "test_design",
        "unknown",
    }
)
CONFIDENCE_LEVELS = frozenset({"low", "medium", "high"})
OWNERSHIP_HINTS = frozenset({"test", "application", "environment", "uncertain"})


class AIAnalyzerError(RuntimeError):
    """A safe, client-facing AI analysis failure."""

    code = "ai_service_error"


class AIConfigurationError(AIAnalyzerError):
    code = "ai_not_configured"


class AIResponseError(AIAnalyzerError):
    code = "invalid_ai_response"


SYSTEM_INSTRUCTION = """You are a senior QA automation and Playwright failure investigator.
Base conclusions ONLY on the supplied evidence. Never invent logs, screenshots, requests,
selectors, timing data, application behavior, or test history. Clearly distinguish evidence
from hypotheses and say when evidence is insufficient. Do not assume every intermittent
failure is synchronization-related or automatically blame the test. Consider test
implementation, application defects, synchronization, locator instability, test data,
network, environment, and CI infrastructure. Do not default to increasing timeouts,
time.sleep(), or page.wait_for_timeout(). Prefer meaningful application states. Suggest code
only when evidence supports it. Keep the investigation concise and actionable. ownership_hint
is an investigative hint, never proof or a definitive assignment of ownership."""

AI_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "summary",
        "root_cause_category",
        "root_cause_confidence",
        "ownership_hint",
        "evidence",
        "hypotheses",
        "recommended_investigation",
        "suggested_remediation",
        "suggested_code",
        "needs_more_evidence",
        "additional_evidence_requested",
    ],
    "properties": {
        "summary": {"type": "string"},
        "root_cause_category": {
            "type": "string",
            "enum": sorted(ROOT_CAUSE_CATEGORIES),
        },
        "root_cause_confidence": {"type": "string", "enum": sorted(CONFIDENCE_LEVELS)},
        "ownership_hint": {"type": "string", "enum": sorted(OWNERSHIP_HINTS)},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["hypothesis", "confidence"],
                "properties": {
                    "hypothesis": {"type": "string"},
                    "confidence": {"type": "string", "enum": sorted(CONFIDENCE_LEVELS)},
                },
            },
        },
        "recommended_investigation": {"type": "array", "items": {"type": "string"}},
        "suggested_remediation": {"type": "array", "items": {"type": "string"}},
        "suggested_code": {"type": ["string", "null"]},
        "needs_more_evidence": {"type": "boolean"},
        "additional_evidence_requested": {"type": "array", "items": {"type": "string"}},
    },
}


def build_prompt(evidence: Mapping[str, Any]) -> str:
    """Build the user prompt separately from provider communication."""

    return "Investigate this structured test-failure evidence:\n" + json.dumps(
        evidence, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def validate_ai_response(value: Any) -> dict[str, Any]:
    """Validate model output even when provider-side structured output is bypassed."""

    required_strings = (
        "summary",
        "root_cause_category",
        "root_cause_confidence",
        "ownership_hint",
    )
    required_lists = (
        "evidence",
        "recommended_investigation",
        "suggested_remediation",
        "additional_evidence_requested",
    )
    if not isinstance(value, dict) or any(
        not isinstance(value.get(key), str) for key in required_strings
    ):
        raise AIResponseError("The AI provider returned an incomplete response")
    if value["root_cause_category"] not in ROOT_CAUSE_CATEGORIES:
        raise AIResponseError(
            "The AI provider returned an unsupported root-cause category"
        )
    if value["root_cause_confidence"] not in CONFIDENCE_LEVELS:
        raise AIResponseError(
            "The AI provider returned an unsupported confidence level"
        )
    if value["ownership_hint"] not in OWNERSHIP_HINTS:
        raise AIResponseError("The AI provider returned an unsupported ownership hint")
    if any(not _string_list(value.get(key)) for key in required_lists):
        raise AIResponseError("The AI provider returned an incomplete response")
    hypotheses = value.get("hypotheses")
    if not isinstance(hypotheses, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("hypothesis"), str)
        or item.get("confidence") not in CONFIDENCE_LEVELS
        for item in hypotheses
    ):
        raise AIResponseError("The AI provider returned invalid hypotheses")
    if (
        not isinstance(value.get("needs_more_evidence"), bool)
        or value.get("suggested_code") is not None
        and not isinstance(value.get("suggested_code"), str)
    ):
        raise AIResponseError("The AI provider returned an incomplete response")
    return value


def analyze_with_ai(
    evidence: Mapping[str, Any], client: Any | None = None
) -> dict[str, Any]:
    """Sanitize evidence, request structured output, and return validated analysis."""

    api_key = os.getenv("OPENAI_API_KEY")
    if client is None and not api_key:
        raise AIConfigurationError("AI analysis is not configured; set OPENAI_API_KEY")
    safe_evidence = sanitize_evidence(dict(evidence), max_ai_text_chars())
    provider = client or OpenAI(api_key=api_key, timeout=30.0, max_retries=1)
    try:
        response = provider.responses.create(
            model=openai_model(),
            instructions=SYSTEM_INSTRUCTION,
            input=build_prompt(safe_evidence),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "root_cause_analysis",
                    "strict": True,
                    "schema": AI_RESPONSE_SCHEMA,
                }
            },
        )
        try:
            parsed = json.loads(response.output_text)
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            raise AIResponseError("The AI provider returned malformed JSON") from exc
        return validate_ai_response(parsed)
    except AIResponseError:
        raise
    except openai.AuthenticationError as exc:
        raise AIConfigurationError("AI provider authentication failed") from exc
    except openai.RateLimitError as exc:
        raise AIAnalyzerError("AI provider rate limit reached; retry later") from exc
    except (openai.APITimeoutError, openai.APIConnectionError) as exc:
        raise AIAnalyzerError("AI provider is temporarily unavailable") from exc
    except openai.APIError as exc:
        raise AIAnalyzerError("AI provider request failed") from exc
