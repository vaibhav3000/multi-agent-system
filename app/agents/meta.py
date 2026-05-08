import json
import os
from datetime import datetime

from anthropic import Anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.critique import CRITIQUE_SYSTEM
from app.agents.decomposition import DECOMPOSITION_SYSTEM
from app.agents.orchestrator import ORCHESTRATOR_SYSTEM
from app.agents.retrieval import RETRIEVAL_SYSTEM
from app.agents.synthesis import SYNTHESIS_SYSTEM
from app.core.database import EvalRun, PerformanceDelta, PromptRewrite
from app.eval.harness import run_eval_suite

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", "missing"))

DIMENSION_TO_AGENT = {
    "answer_correctness": "synthesis",
    "citation_accuracy": "retrieval",
    "contradiction_resolution": "synthesis",
    "tool_efficiency": "orchestrator",
    "budget_compliance": "orchestrator",
    "critique_agreement": "critique",
}

AGENT_PROMPTS = {
    "orchestrator": ORCHESTRATOR_SYSTEM,
    "decomposition": DECOMPOSITION_SYSTEM,
    "retrieval": RETRIEVAL_SYSTEM,
    "critique": CRITIQUE_SYSTEM,
    "synthesis": SYNTHESIS_SYSTEM,
}


async def propose_prompt_rewrite(session: AsyncSession) -> dict:
    result = await session.execute(select(EvalRun).order_by(EvalRun.timestamp.desc()))
    runs = result.scalars().all()
    if not runs:
        return {"error": "no_eval_runs", "code": "META_EMPTY"}

    lowest = min(runs, key=lambda row: row.scores_json.get("overall_average", 1.0))
    dimension_scores = {
        key: value["score"]
        for key, value in lowest.scores_json.items()
        if isinstance(value, dict) and "score" in value
    }
    worst_dimension = min(dimension_scores, key=dimension_scores.get)
    agent_id = DIMENSION_TO_AGENT.get(worst_dimension, "synthesis")
    original_prompt = AGENT_PROMPTS[agent_id]

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1800,
        system=(
            "You improve agent system prompts from eval failures. "
            "Return JSON with keys proposed_prompt, diff, justification. Never claim the rewrite was applied."
        ),
        messages=[{
            "role": "user",
            "content": f"""
Worst eval:
test_case_id={lowest.test_case_id}
category={lowest.category}
scores={json.dumps(lowest.scores_json, indent=2)}

Prompt to improve for agent {agent_id}:
{original_prompt}

Rewrite this prompt to improve the worst dimension: {worst_dimension}.
""",
        }],
    )

    try:
        proposed = json.loads(response.content[0].text)
    except json.JSONDecodeError:
        proposed = {
            "proposed_prompt": response.content[0].text,
            "diff": "Model returned free-form text instead of structured diff.",
            "justification": f"Improve {worst_dimension} based on failed eval {lowest.test_case_id}.",
        }

    rewrite = PromptRewrite(
        agent_id=agent_id,
        dimension=worst_dimension,
        original_prompt=original_prompt,
        proposed_prompt=proposed["proposed_prompt"],
        diff=proposed.get("diff", ""),
        justification=proposed.get("justification", ""),
        status="pending",
    )
    session.add(rewrite)
    await session.commit()
    return {
        "rewrite_id": rewrite.rewrite_id,
        "agent_id": agent_id,
        "dimension": worst_dimension,
        "status": rewrite.status,
    }


async def handle_rewrite_action(session: AsyncSession, rewrite_id: str, action: str) -> dict:
    rewrite = await session.get(PromptRewrite, rewrite_id)
    if not rewrite:
        return {"error": "not_found", "code": "REWRITE_NOT_FOUND"}
    if action == "reject":
        rewrite.status = "rejected"
        await session.commit()
        return {"rewrite_id": rewrite_id, "status": "rejected"}

    before = await run_eval_suite(session=session, failed_only=True)
    rewrite.status = "approved"
    rewrite.approved_at = datetime.utcnow()
    after = await run_eval_suite(session=session, failed_only=True)
    session.add(PerformanceDelta(
        rewrite_id=rewrite_id,
        before_scores_json=before,
        after_scores_json=after,
    ))
    await session.commit()
    return {
        "rewrite_id": rewrite_id,
        "status": "approved",
        "note": "Approved rewrite was stored. Runtime prompts remain code-defined until a prompt registry is added.",
        "before": before,
        "after": after,
    }
