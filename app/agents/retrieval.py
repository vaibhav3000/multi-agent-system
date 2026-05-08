import json
import time

from app.core.budget import consume_budget, register_agent_budget
from app.core.context_schema import AgentID, AgentOutput, SharedContext, ToolCall
from app.core.database import get_active_prompt
from app.core.llm import call_llm
from app.core.logger import structured_log
from app.tools.web_search import run_web_search

FALLBACK_RETRIEVAL_SYSTEM = """You are a retrieval-augmented reasoning agent. You perform multi-hop reasoning.

Rules:
- You must retrieve at least two separate chunks of information before forming an answer
- For each claim in your answer, cite which chunk (chunk_1 or chunk_2, etc.) contributed to it
- Use the web_search tool for each hop
- After two hops, synthesize your answer

Output format:
{
  "answer": "your answer here",
  "hops": [
    {"hop_number": 1, "query_used": "...", "chunk_id": "chunk_1", "key_finding": "..."},
    {"hop_number": 2, "query_used": "...", "chunk_id": "chunk_2", "key_finding": "..."}
  ],
  "citations": {"sentence or claim": "chunk_id"}
}
"""


async def run_retrieval(ctx: SharedContext) -> dict:
    start = time.time()
    register_agent_budget(ctx, AgentID.RETRIEVAL)
    system_prompt = get_active_prompt(AgentID.RETRIEVAL.value, FALLBACK_RETRIEVAL_SYSTEM)

    subtask_descriptions = [t.description for t in ctx.subtasks if t.status != "complete"]
    query_context = "\n".join(subtask_descriptions) if subtask_descriptions else ctx.original_query

    prompt = f"""
Original query: {ctx.original_query}
Sub-tasks to address: {query_context}

Perform multi-hop retrieval. First search for the primary topic, then search for a related or dependent aspect. Cite both chunks in your answer.
"""

    if not consume_budget(ctx, AgentID.RETRIEVAL, prompt):
        structured_log(agent_id=AgentID.RETRIEVAL.value, event_type="budget_violation", job_id=ctx.job_id)
        return {"answer": "Budget exceeded", "hops": [], "citations": {}}

    hop1_result = await _do_retrieval_hop(ctx, query_context, hop_number=1)
    followup_query = await _derive_followup_query(ctx.original_query, hop1_result)
    hop2_result = await _do_retrieval_hop(ctx, followup_query, hop_number=2)

    synthesis_prompt = f"""
Original query: {ctx.original_query}

Chunk 1 findings: {json.dumps(hop1_result)}
Chunk 2 findings: {json.dumps(hop2_result)}

Now produce a JSON answer following the required output format with citations linking claims to chunk_1 or chunk_2.
"""

    response = call_llm(synthesis_prompt, system=system_prompt, max_tokens=1500)

    raw = response.text
    latency = (time.time() - start) * 1000

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {"answer": raw, "hops": [], "citations": {}}

    for task in ctx.subtasks:
        if task.status == "pending":
            task.status = "complete"
            task.result = result

    structured_log(
        agent_id=AgentID.RETRIEVAL.value,
        event_type="retrieval_complete",
        input_data=ctx.original_query,
        output_data=result,
        latency_ms=latency,
        token_count=response.total_tokens,
        job_id=ctx.job_id,
    )

    ctx.agent_outputs[AgentID.RETRIEVAL.value] = AgentOutput(
        agent_id=AgentID.RETRIEVAL,
        output=result,
        token_count=response.total_tokens,
        provenance=result.get("citations", {}),
    )

    return result


async def _do_retrieval_hop(ctx: SharedContext, query: str, hop_number: int) -> dict:
    tool_start = time.time()
    max_retries = 2
    result = None

    for attempt in range(max_retries + 1):
        raw_result = await run_web_search(query)
        latency = (time.time() - tool_start) * 1000

        tool_call = ToolCall(
            tool_name="web_search",
            input={"query": query},
            output=raw_result,
            latency_ms=latency,
            retry_count=attempt,
        )

        if "error" in raw_result:
            if raw_result["code"] == "TOOL_TIMEOUT" and attempt < max_retries:
                tool_call.accepted = False
                tool_call.failure_reason = raw_result["error"]
                ctx.tool_call_log.append(tool_call)
                continue
            tool_call.accepted = False
            tool_call.failure_reason = raw_result.get("error", "unknown")
            ctx.tool_call_log.append(tool_call)
            return {"chunk_id": f"chunk_{hop_number}", "content": [], "error": raw_result["error"]}

        tool_call.accepted = True
        ctx.tool_call_log.append(tool_call)
        result = raw_result
        break

    return {"chunk_id": f"chunk_{hop_number}", "query": query, "content": result}


async def _derive_followup_query(original_query: str, hop1_result: dict) -> str:
    response = call_llm(
        f"""
Given the original query: "{original_query}"
And the first retrieval result: {json.dumps(hop1_result)[:500]}

What is a good follow-up search query to get complementary information? Reply with only the query string, no explanation.
""",
        max_tokens=100,
    )
    return response.text.strip()
