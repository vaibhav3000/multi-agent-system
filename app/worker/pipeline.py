from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.critique import run_critique
from app.agents.decomposition import run_decomposition
from app.agents.orchestrator import run_orchestrator
from app.agents.retrieval import run_retrieval
from app.agents.synthesis import run_synthesis
from app.core.context_schema import SharedContext

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _emit(callback: EventCallback | None, event_type: str, payload: dict[str, Any]) -> None:
    if callback:
        await callback(event_type, payload)


async def run_full_pipeline(ctx: SharedContext, event_callback: EventCallback | None = None) -> SharedContext:
    await _emit(event_callback, "agent_start", {"job_id": ctx.job_id, "agent_id": "orchestrator"})
    routing = await run_orchestrator(ctx)
    await _emit(event_callback, "context_budget_update", {"job_id": ctx.job_id, "budget_states": ctx.model_dump(mode="json")["budget_states"]})

    next_agents = routing.get("next_agents") or ["decomposition", "retrieval", "critique", "synthesis"]
    if "retrieval" not in next_agents:
        next_agents.append("retrieval")
    if "critique" not in next_agents:
        next_agents.append("critique")
    if "synthesis" not in next_agents:
        next_agents.append("synthesis")

    agent_runners = {
        "decomposition": run_decomposition,
        "retrieval": run_retrieval,
        "critique": run_critique,
        "synthesis": run_synthesis,
    }

    for agent_id in next_agents:
        runner = agent_runners.get(agent_id)
        if runner is None:
            continue
        await _emit(event_callback, "agent_start", {"job_id": ctx.job_id, "agent_id": agent_id})
        if agent_id == "retrieval":
            await _emit(event_callback, "tool_call_start", {"job_id": ctx.job_id, "tool_name": "web_search"})
        output = await runner(ctx)
        if agent_id == "retrieval":
            await _emit(event_callback, "tool_call_complete", {"job_id": ctx.job_id, "tool_count": len(ctx.tool_call_log)})
        await _emit(event_callback, "agent_output_token", {"job_id": ctx.job_id, "agent_id": agent_id, "token": str(output)[:500]})
        await _emit(event_callback, "context_budget_update", {"job_id": ctx.job_id, "budget_states": ctx.model_dump(mode="json")["budget_states"]})

    ctx.status = "complete"
    await _emit(event_callback, "pipeline_complete", {"job_id": ctx.job_id, "final_answer": ctx.final_answer})
    return ctx

