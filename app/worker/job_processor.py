import asyncio
import os

from celery import Celery

from app.core.context_manager import save_context
from app.core.context_schema import SharedContext
from app.core.database import AsyncSessionLocal
from app.worker.pipeline import run_full_pipeline


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0") or "redis://localhost:6379/0"

celery_app = Celery(
    "multi_agent_system",
    broker=REDIS_URL,
    backend=REDIS_URL,
)


@celery_app.task(name="app.worker.job_processor.process_query")
def process_query(job_id: str, query: str) -> dict:
    async def _run() -> dict:
        ctx = SharedContext(job_id=job_id, original_query=query, status="running")
        async with AsyncSessionLocal() as session:
            await save_context(session, ctx)
        try:
            await run_full_pipeline(ctx)
            ctx.status = "complete"
        except Exception as exc:
            ctx.status = "failed"
            ctx.final_answer = f"Pipeline failed: {exc}"
        async with AsyncSessionLocal() as session:
            await save_context(session, ctx)
        return ctx.model_dump(mode="json")

    return asyncio.run(_run())
