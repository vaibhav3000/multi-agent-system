import json
import time

from app.core.budget import consume_budget, register_agent_budget
from app.core.context_schema import AgentID, AgentOutput, SharedContext
from app.core.database import get_active_prompt
from app.core.llm import call_llm
from app.core.logger import structured_log

FALLBACK_SYNTHESIS_SYSTEM = """You are a synthesis agent. You merge outputs from all prior agents into a final answer.

You receive:
- Decomposition subtasks and their statuses
- Retrieval results with citations
- Critique scores with flagged claims

Your job:
1. Resolve every contradiction flagged by the critique agent (do not surface contradictions to the user)
2. Produce a final answer
3. Produce a provenance map: for each sentence in your answer, state which agent and which chunk it came from

Output JSON:
{
  "final_answer": "the complete answer to the original query",
  "contradiction_resolutions": [
    {"flagged_claim": "...", "resolution": "...", "resolution_reasoning": "..."}
  ],
  "provenance_map": {
    "sentence or phrase from final_answer": "source agent + chunk id"
  }
}

Never include raw flagged contradictions in the final answer. Resolve them first.
"""


async def run_synthesis(ctx: SharedContext) -> dict:
    start = time.time()
    register_agent_budget(ctx, AgentID.SYNTHESIS)
    system_prompt = get_active_prompt(AgentID.SYNTHESIS.value, FALLBACK_SYNTHESIS_SYSTEM)

    decomp_output = ctx.agent_outputs.get(AgentID.DECOMPOSITION.value, {})
    retrieval_output = ctx.agent_outputs.get(AgentID.RETRIEVAL.value, {})
    critique_output = ctx.agent_outputs.get(AgentID.CRITIQUE.value, {})

    flagged_claims = []
    if isinstance(critique_output, AgentOutput):
        flagged_claims = [
            c.model_dump() for c in critique_output.claim_scores if c.flagged
        ]

    prompt = f"""
Original query: {ctx.original_query}

Decomposition output:
{json.dumps(decomp_output.output if hasattr(decomp_output, 'output') else decomp_output, default=str)[:1000]}

Retrieval output:
{json.dumps(retrieval_output.output if hasattr(retrieval_output, 'output') else retrieval_output, default=str)[:2000]}

Flagged claims requiring resolution:
{json.dumps(flagged_claims, default=str)[:1000]}

Produce the final synthesized answer with provenance map and contradiction resolutions.
"""

    if not consume_budget(ctx, AgentID.SYNTHESIS, prompt):
        structured_log(agent_id=AgentID.SYNTHESIS.value, event_type="budget_violation", job_id=ctx.job_id)
        return {"final_answer": "Budget exceeded during synthesis", "contradiction_resolutions": [], "provenance_map": {}}

    response = call_llm(prompt, system=system_prompt, max_tokens=2000)

    raw = response.text
    latency = (time.time() - start) * 1000

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {
            "final_answer": raw,
            "contradiction_resolutions": [],
            "provenance_map": {},
        }

    ctx.final_answer = result.get("final_answer", "")
    ctx.provenance_map = result.get("provenance_map", {})

    structured_log(
        agent_id=AgentID.SYNTHESIS.value,
        event_type="synthesis_complete",
        output_data=result,
        latency_ms=latency,
        token_count=response.total_tokens,
        job_id=ctx.job_id,
    )

    ctx.agent_outputs[AgentID.SYNTHESIS.value] = AgentOutput(
        agent_id=AgentID.SYNTHESIS,
        output=result,
        token_count=response.total_tokens,
        provenance=result.get("provenance_map", {}),
    )

    return result
