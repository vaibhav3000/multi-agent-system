import json
import time

from app.core.budget import check_remaining_budget, consume_budget, register_agent_budget
from app.core.context_schema import AgentID, AgentOutput, SharedContext
from app.core.database import get_active_prompt
from app.core.llm import call_llm
from app.core.logger import structured_log

FALLBACK_ORCHESTRATOR_SYSTEM = """You are a master orchestrator agent. Given a user query and the current pipeline state, you must decide:
1. Which sub-agents to invoke next (decomposition, retrieval, critique, synthesis)
2. In what order
3. Why

You must output a JSON object with this exact schema:
{
  "reasoning": "string explaining your routing decision",
  "next_agents": ["list of agent IDs in execution order"],
  "context_budget_allocation": {"agent_id": token_budget_integer},
  "skip_reasons": {"agent_id": "reason if skipping"}
}

Agent IDs are: decomposition, retrieval, critique, synthesis
Do not hardcode sequences. Reason about what the query needs.
If the query is simple and factual, you may skip decomposition.
If there are no prior retrieval results, you must include retrieval before synthesis.
critique must always run before synthesis if retrieval or decomposition ran.
"""


async def run_orchestrator(ctx: SharedContext) -> dict:
    start = time.time()
    register_agent_budget(ctx, AgentID.ORCHESTRATOR)
    system_prompt = get_active_prompt(AgentID.ORCHESTRATOR.value, FALLBACK_ORCHESTRATOR_SYSTEM)

    pipeline_state = {
        "original_query": ctx.original_query,
        "completed_agents": list(ctx.agent_outputs.keys()),
        "subtask_count": len(ctx.subtasks),
        "subtask_statuses": {t.task_id: t.status for t in ctx.subtasks},
        "budget_remaining": check_remaining_budget(ctx, AgentID.ORCHESTRATOR),
        "tool_calls_so_far": len(ctx.tool_call_log),
    }

    user_message = f"""
Query: {ctx.original_query}

Current pipeline state:
{json.dumps(pipeline_state, indent=2)}

Decide which agents to run next and in what order. Output only valid JSON.
"""

    if not consume_budget(ctx, AgentID.ORCHESTRATOR, user_message):
        structured_log(
            agent_id=AgentID.ORCHESTRATOR.value,
            event_type="budget_exceeded_fallback",
            job_id=ctx.job_id,
        )
        return {
            "reasoning": "Budget exceeded, using default routing",
            "next_agents": ["decomposition", "retrieval", "critique", "synthesis"],
            "context_budget_allocation": {},
            "skip_reasons": {},
        }

    response = call_llm(user_message, system=system_prompt, max_tokens=1000)

    raw = response.text
    latency = (time.time() - start) * 1000

    try:
        routing = json.loads(raw)
    except json.JSONDecodeError:
        routing = {
            "reasoning": "Parse failed, using default routing",
            "next_agents": ["decomposition", "retrieval", "critique", "synthesis"],
            "context_budget_allocation": {},
            "skip_reasons": {},
        }

    ctx.routing_log.append({
        "job_id": ctx.job_id,
        "routing_decision": routing,
        "latency_ms": latency,
    })

    structured_log(
        agent_id=AgentID.ORCHESTRATOR.value,
        event_type="routing_decision",
        input_data=pipeline_state,
        output_data=routing,
        latency_ms=latency,
        token_count=response.total_tokens,
        job_id=ctx.job_id,
    )

    ctx.agent_outputs[AgentID.ORCHESTRATOR.value] = AgentOutput(
        agent_id=AgentID.ORCHESTRATOR,
        output=routing,
        token_count=response.total_tokens,
    )

    return routing
