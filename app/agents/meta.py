import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.critique import FALLBACK_CRITIQUE_SYSTEM
from app.agents.decomposition import FALLBACK_DECOMPOSITION_SYSTEM
from app.agents.orchestrator import FALLBACK_ORCHESTRATOR_SYSTEM
from app.agents.retrieval import FALLBACK_RETRIEVAL_SYSTEM
from app.agents.synthesis import FALLBACK_SYNTHESIS_SYSTEM
from app.core.database import AgentPrompt, EvalRun, PerformanceDelta, PromptRewrite
from app.core.llm import call_llm
from app.eval.harness import run_eval_suite

DIMENSION_TO_AGENT = {
    "answer_correctness": "synthesis",
    "citation_accuracy": "retrieval",
    "contradiction_resolution": "synthesis",
    "tool_efficiency": "orchestrator",
    "budget_compliance": "orchestrator",
    "critique_agreement": "critique",
}

AGENT_PROMPTS = {
    "orchestrator": FALLBACK_ORCHESTRATOR_SYSTEM,
    "decomposition": FALLBACK_DECOMPOSITION_SYSTEM,
    "retrieval": FALLBACK_RETRIEVAL_SYSTEM,
    "critique": FALLBACK_CRITIQUE_SYSTEM,
    "synthesis": FALLBACK_SYNTHESIS_SYSTEM,
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

    response = call_llm(
        f"""
Worst eval:
test_case_id={lowest.test_case_id}
category={lowest.category}
scores={json.dumps(lowest.scores_json, indent=2)}

Prompt to improve for agent {agent_id}:
{original_prompt}

Rewrite this prompt to improve the worst dimension: {worst_dimension}.
""",
        max_tokens=1800,
        system=(
            "You improve agent system prompts from eval failures. "
            "Return JSON with keys proposed_prompt, diff, justification. Never claim the rewrite was applied."
        ),
    )

    try:
        proposed = json.loads(response.text)
    except json.JSONDecodeError:
        proposed = {
            "proposed_prompt": response.text,
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
    active_prompt = await session.get(AgentPrompt, rewrite.agent_id)
    if active_prompt is None:
        active_prompt = AgentPrompt(
            agent_id=rewrite.agent_id,
            active_prompt=rewrite.proposed_prompt,
            rewrite_id=rewrite.rewrite_id,
            updated_at=datetime.utcnow(),
        )
        session.add(active_prompt)
    else:
        active_prompt.active_prompt = rewrite.proposed_prompt
        active_prompt.rewrite_id = rewrite.rewrite_id
        active_prompt.updated_at = datetime.utcnow()
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
        "note": "Approved rewrite was stored as the active prompt and failed cases were re-evaluated.",
        "before": before,
        "after": after,
    }
