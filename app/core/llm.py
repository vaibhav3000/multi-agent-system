import json
import os
from dataclasses import dataclass
from typing import Any

import httpx
from openai import OpenAI


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _provider() -> str:
    return os.getenv("LLM_PROVIDER", "deepseek").strip().lower()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required for LLM_PROVIDER={_provider()}")
    return value


def _messages(system: str | None, user_content: str) -> list[dict[str, str]]:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_content})
    return messages


def _mock_response(system: str | None, user_content: str) -> LLMResponse:
    lower = f"{system or ''}\n{user_content}".lower()
    if "follow-up search query" in lower:
        text = "background evidence and current context"
    elif "routing decision" in lower or "next_agents" in lower:
        text = json.dumps({
            "reasoning": "Mock provider selected the default evidence-first route.",
            "next_agents": ["decomposition", "retrieval", "critique", "synthesis"],
            "context_budget_allocation": {},
            "skip_reasons": {},
        })
    elif "subtasks" in lower and "dependency_explanation" in lower:
        text = json.dumps({
            "subtasks": [{
                "task_id": "t1",
                "description": "Answer the user's query with supporting evidence.",
                "task_type": "retrieval",
                "depends_on": [],
            }],
            "dependency_explanation": "The query can be handled as one evidence-gathering task.",
        })
    elif "claim_scores" in lower and "overall_reliability" in lower:
        text = json.dumps({
            "claim_scores": [],
            "overall_reliability": 0.75,
            "summary": "Mock critique found no specific contradictions.",
        })
    elif "final_answer" in lower and "provenance_map" in lower:
        text = json.dumps({
            "final_answer": "Mock final answer produced for plumbing verification. Set LLM_PROVIDER=deepseek for real model answers.",
            "contradiction_resolutions": [],
            "provenance_map": {
                "Mock final answer produced for plumbing verification.": "synthesis + mock"
            },
        })
    elif "answer" in lower and "hops" in lower and "citations" in lower:
        text = json.dumps({
            "answer": "Mock retrieval answer based on two placeholder chunks.",
            "hops": [
                {"hop_number": 1, "query_used": "primary topic", "chunk_id": "chunk_1", "key_finding": "Mock primary evidence."},
                {"hop_number": 2, "query_used": "related topic", "chunk_id": "chunk_2", "key_finding": "Mock complementary evidence."},
            ],
            "citations": {"Mock retrieval answer based on two placeholder chunks.": "chunk_1"},
        })
    elif "select" in lower and "postgresql" in lower:
        text = json.dumps({"sql": "SELECT id, name, category, price, inventory_count FROM products LIMIT 10"})
    else:
        text = "Mock response"
    return LLMResponse(text=text, input_tokens=len(user_content.split()), output_tokens=len(text.split()))


def call_llm(
    user_content: str,
    *,
    system: str | None = None,
    max_tokens: int = 1000,
    model: str | None = None,
) -> LLMResponse:
    provider = _provider()
    if provider == "mock":
        return _mock_response(system, user_content)
    if provider == "deepseek":
        return _call_openai_sdk(
            user_content,
            system=system,
            max_tokens=max_tokens,
            model=model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            api_key_env="DEEPSEEK_API_KEY",
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )
    if provider == "groq":
        return _call_openai_sdk(
            user_content,
            system=system,
            max_tokens=max_tokens,
            model=model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            api_key_env="GROQ_API_KEY",
            base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        )
    if provider == "gemini":
        return _call_gemini(
            user_content,
            system=system,
            max_tokens=max_tokens,
            model=model or os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
        )
    if provider == "anthropic":
        return _call_anthropic(
            user_content,
            system=system,
            max_tokens=max_tokens,
            model=model or os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307"),
        )
    raise RuntimeError(f"Unsupported LLM_PROVIDER={provider}")


def _call_openai_sdk(
    user_content: str,
    *,
    system: str | None,
    max_tokens: int,
    model: str,
    api_key_env: str,
    base_url: str,
) -> LLMResponse:
    client = OpenAI(
        api_key=_require_env(api_key_env),
        base_url=base_url,
    )
    response = client.chat.completions.create(
        model=model,
        messages=_messages(system, user_content),
        max_tokens=max_tokens,
        temperature=0.2,
    )
    usage: Any = response.usage
    return LLMResponse(
        text=response.choices[0].message.content or "",
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
    )


def _call_gemini(
    user_content: str,
    *,
    system: str | None,
    max_tokens: int,
    model: str,
) -> LLMResponse:
    api_key = _require_env("GEMINI_API_KEY")
    prompt = f"{system}\n\n{user_content}" if system else user_content
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.2,
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, params={"key": api_key}, json=payload)
        response.raise_for_status()
        data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    usage: dict[str, Any] = data.get("usageMetadata") or {}
    return LLMResponse(
        text=text,
        input_tokens=int(usage.get("promptTokenCount") or 0),
        output_tokens=int(usage.get("candidatesTokenCount") or 0),
    )


def _call_anthropic(
    user_content: str,
    *,
    system: str | None,
    max_tokens: int,
    model: str,
) -> LLMResponse:
    api_key = _require_env("ANTHROPIC_API_KEY")
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": user_content}],
    }
    if system:
        payload["system"] = system

    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    text = data["content"][0]["text"]
    usage = data.get("usage", {})
    return LLMResponse(
        text=text,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
    )

