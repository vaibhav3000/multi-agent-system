from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.critique import FALLBACK_CRITIQUE_SYSTEM
from app.agents.decomposition import FALLBACK_DECOMPOSITION_SYSTEM
from app.agents.orchestrator import FALLBACK_ORCHESTRATOR_SYSTEM
from app.agents.retrieval import FALLBACK_RETRIEVAL_SYSTEM
from app.agents.synthesis import FALLBACK_SYNTHESIS_SYSTEM
from app.core.context_manager import save_context
from app.core.context_schema import SharedContext
from app.core.database import AsyncSessionLocal, EvalRun
from app.eval.scoring import score_test_case
from app.eval.test_cases import TEST_CASES
from app.worker.pipeline import run_full_pipeline

PROMPTS = {
    "orchestrator": FALLBACK_ORCHESTRATOR_SYSTEM,
    "decomposition": FALLBACK_DECOMPOSITION_SYSTEM,
    "retrieval": FALLBACK_RETRIEVAL_SYSTEM,
    "critique": FALLBACK_CRITIQUE_SYSTEM,
    "synthesis": FALLBACK_SYNTHESIS_SYSTEM,
}


async def _failed_case_ids(session: AsyncSession) -> set[str]:
    result = await session.execute(select(EvalRun))
    failed = set()
    for row in result.scalars().all():
        if row.scores_json.get("overall_average", 1.0) < 0.75:
            failed.add(row.test_case_id)
    return failed


async def run_eval_suite(session: AsyncSession | None = None, failed_only: bool = False) -> dict:
    owns_session = session is None
    session = session or AsyncSessionLocal()
    try:
        failed_ids = await _failed_case_ids(session) if failed_only else None
        summary = defaultdict(lambda: {"count": 0, "overall_average": 0.0, "dimensions": defaultdict(float)})
        cases = [case for case in TEST_CASES if not failed_only or case["id"] in failed_ids]

        for case in cases:
            ctx = SharedContext(original_query=case["query"], status="running")
            await run_full_pipeline(ctx)
            ctx.status = "complete"
            scores = score_test_case(ctx, case["expected_answer_keywords"])
            await save_context(session, ctx)

            session.add(EvalRun(
                job_id=ctx.job_id,
                timestamp=datetime.utcnow(),
                test_case_id=case["id"],
                category=case["category"],
                scores_json=scores,
                prompts_json=PROMPTS,
                tool_calls_json=[t.model_dump(mode="json") for t in ctx.tool_call_log],
            ))
            await session.commit()

            bucket = summary[case["category"]]
            bucket["count"] += 1
            bucket["overall_average"] += scores["overall_average"]
            for name, value in scores.items():
                if isinstance(value, dict) and "score" in value:
                    bucket["dimensions"][name] += value["score"]

        normalized = {"case_results": []}
        for category, data in summary.items():
            count = max(data["count"], 1)
            normalized[category] = {
                "count": data["count"],
                "overall_average": data["overall_average"] / count,
                "dimensions": {name: value / count for name, value in data["dimensions"].items()},
            }
        result = await session.execute(select(EvalRun).order_by(EvalRun.timestamp.desc()).limit(len(cases)))
        for row in result.scalars().all():
            normalized["case_results"].append({
                "test_case_id": row.test_case_id,
                "job_id": row.job_id,
                "category": row.category,
                "overall_average": row.scores_json.get("overall_average"),
                "scores": row.scores_json,
            })
        return normalized
    finally:
        if owns_session:
            await session.close()
