import os
import time

import httpx


async def run_web_search(query: str):
    if not isinstance(query, str) or not query.strip():
        return {"error": "invalid_input", "code": "TOOL_MALFORMED"}

    endpoint = os.getenv("SEARCH_API_URL")
    api_key = os.getenv("SEARCH_API_KEY")

    if not endpoint:
        return [
            {
                "url": f"https://example.com/search?q={query.replace(' ', '+')}",
                "title": f"Stub result for {query}",
                "snippet": f"Structured placeholder search result related to: {query}",
                "relevance_score": 0.82,
            },
            {
                "url": f"https://example.org/reference/{abs(hash(query)) % 10000}",
                "title": f"Reference background for {query}",
                "snippet": f"Supplemental context for multi-hop retrieval about: {query}",
                "relevance_score": 0.71,
            },
        ]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            response = await client.get(endpoint, params={"q": query}, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException:
        return {"error": "timeout", "code": "TOOL_TIMEOUT"}
    except Exception as exc:
        return {"error": "search_error", "code": "TOOL_ERROR", "detail": str(exc)}

    raw_results = payload.get("results") or payload.get("items") or []
    if not raw_results:
        return {"error": "no_results", "code": "TOOL_EMPTY"}

    results = []
    for item in raw_results[:5]:
        results.append({
            "url": item.get("url") or item.get("link") or "",
            "title": item.get("title") or "Untitled",
            "snippet": item.get("snippet") or item.get("description") or "",
            "relevance_score": float(item.get("relevance_score", item.get("score", 0.5))),
        })
    return results or {"error": "no_results", "code": "TOOL_EMPTY"}


async def timed_web_search(query: str):
    start = time.time()
    result = await run_web_search(query)
    return result, (time.time() - start) * 1000

