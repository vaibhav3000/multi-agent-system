import json
import time

from app.core.budget import consume_budget, register_agent_budget
from app.core.context_schema import AgentID, AgentOutput, SharedContext, SubTask
from app.core.database import get_active_prompt
from app.core.llm import call_llm
from app.core.logger import structured_log

FALLBACK_DECOMPOSITION_SYSTEM = """You are a decomposition agent. Break the given query into typed sub-tasks.

Output a JSON object:
{
  "subtasks": [
    {
      "task_id": "unique short string like t1, t2",
      "description": "what needs to be done",
      "task_type": "retrieval | computation | comparison | summarization | verification",
      "depends_on": ["list of task_ids this depends on, or empty list"]
    }
  ],
  "dependency_explanation": "string explaining the dependency graph"
}

Rules:
- Never create circular dependencies
- A task with depends_on must not execute before its dependencies complete
- If the query is atomic and cannot be broken down, return a single subtask with no dependencies
- Be explicit about why each dependency exists
"""


async def run_decomposition(ctx: SharedContext) -> list[SubTask]:
    start = time.time()
    register_agent_budget(ctx, AgentID.DECOMPOSITION)
    system_prompt = get_active_prompt(AgentID.DECOMPOSITION.value, FALLBACK_DECOMPOSITION_SYSTEM)

    prompt = f"Query to decompose: {ctx.original_query}"

    if not consume_budget(ctx, AgentID.DECOMPOSITION, prompt):
        structured_log(
            agent_id=AgentID.DECOMPOSITION.value,
            event_type="budget_violation",
            job_id=ctx.job_id,
        )
        return []

    response = call_llm(prompt, system=system_prompt, max_tokens=1000)

    raw = response.text
    latency = (time.time() - start) * 1000

    try:
        data = json.loads(raw)
        subtasks = []
        for item in data.get("subtasks", []):
            st = SubTask(
                task_id=item["task_id"],
                description=item["description"],
                depends_on=item.get("depends_on", []),
                status="pending",
                assigned_agent=AgentID.RETRIEVAL,
            )
            subtasks.append(st)
        ctx.subtasks = subtasks
    except (json.JSONDecodeError, KeyError):
        subtasks = [SubTask(
            task_id="t1",
            description=ctx.original_query,
            depends_on=[],
            status="pending",
        )]
        ctx.subtasks = subtasks

    structured_log(
        agent_id=AgentID.DECOMPOSITION.value,
        event_type="decomposition_complete",
        input_data=ctx.original_query,
        output_data=[t.model_dump() for t in subtasks],
        latency_ms=latency,
        token_count=response.total_tokens,
        job_id=ctx.job_id,
    )

    ctx.agent_outputs[AgentID.DECOMPOSITION.value] = AgentOutput(
        agent_id=AgentID.DECOMPOSITION,
        output=[t.model_dump(mode="json") for t in subtasks],
        token_count=response.total_tokens,
    )

    return subtasks


def get_executable_subtasks(ctx: SharedContext) -> list[SubTask]:
    """Return subtasks whose dependencies are all complete."""
    complete_ids = {t.task_id for t in ctx.subtasks if t.status == "complete"}
    return [
        t for t in ctx.subtasks
        if t.status == "pending" and all(dep in complete_ids for dep in t.depends_on)
    ]
