import json
import time

from app.core.budget import consume_budget, register_agent_budget
from app.core.context_schema import AgentID, AgentOutput, ClaimScore, SharedContext
from app.core.llm import call_llm
from app.core.logger import structured_log

CRITIQUE_SYSTEM = """You are a critique agent. You review outputs from other agents claim by claim.

For each claim or sentence in the input, assign:
- confidence (0.0 to 1.0)
- flagged (true/false)
- flag_reason (string if flagged, null otherwise)

Output JSON:
{
  "claim_scores": [
    {
      "claim_text": "exact text of the claim",
      "confidence": 0.85,
      "flagged": false,
      "flag_reason": null
    }
  ],
  "overall_reliability": 0.0 to 1.0,
  "summary": "one sentence summary of the critique"
}

Rules:
- Flag a claim if it is unverified, contradicts another claim, or makes a strong assertion without evidence
- Do NOT flag the entire output, only specific spans
- Be precise about which text you are scoring
"""


async def run_critique(ctx: SharedContext) -> dict:
    start = time.time()
    register_agent_budget(ctx, AgentID.CRITIQUE)

    outputs_to_critique = {}
    for agent_id, agent_output in ctx.agent_outputs.items():
        if agent_id not in [AgentID.ORCHESTRATOR.value, AgentID.CRITIQUE.value]:
            outputs_to_critique[agent_id] = agent_output.output

    if not outputs_to_critique:
        return {"claim_scores": [], "overall_reliability": 0.0, "summary": "No outputs to critique"}

    prompt = f"""
Review the following agent outputs and score each claim:

{json.dumps(outputs_to_critique, indent=2, default=str)[:3000]}

Score every distinct claim or sentence separately.
"""

    if not consume_budget(ctx, AgentID.CRITIQUE, prompt):
        structured_log(agent_id=AgentID.CRITIQUE.value, event_type="budget_violation", job_id=ctx.job_id)
        return {"claim_scores": [], "overall_reliability": 0.0, "summary": "Budget exceeded"}

    response = call_llm(prompt, system=CRITIQUE_SYSTEM, max_tokens=2000)

    raw = response.text
    latency = (time.time() - start) * 1000

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {"claim_scores": [], "overall_reliability": 0.5, "summary": "Parse failed"}

    claim_scores = [
        ClaimScore(
            claim_text=c["claim_text"],
            confidence=c["confidence"],
            flagged=c["flagged"],
            flag_reason=c.get("flag_reason"),
        )
        for c in result.get("claim_scores", [])
    ]

    structured_log(
        agent_id=AgentID.CRITIQUE.value,
        event_type="critique_complete",
        output_data=result,
        latency_ms=latency,
        token_count=response.total_tokens,
        job_id=ctx.job_id,
    )

    ctx.agent_outputs[AgentID.CRITIQUE.value] = AgentOutput(
        agent_id=AgentID.CRITIQUE,
        output=result,
        claim_scores=claim_scores,
        token_count=response.total_tokens,
    )

    return result
