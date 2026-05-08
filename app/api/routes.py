import asyncio
import json
import uuid

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agents.meta import handle_rewrite_action
from app.api.sse import sse_payload
from app.core.context_manager import save_context
from app.core.context_schema import SharedContext
from app.core.database import AsyncSessionLocal, Job, get_latest_eval_summary, get_session, init_db
from app.eval.harness import run_eval_suite
from app.worker.job_processor import process_query
from app.worker.pipeline import run_full_pipeline

app = FastAPI(title="Multi-Agent LLM System")


class QueryRequest(BaseModel):
    query: str
    use_celery: bool = True


class RewriteAction(BaseModel):
    action: str


@app.on_event("startup")
async def startup() -> None:
    await init_db()


@app.post("/query")
async def query(request: QueryRequest):
    job_id = str(uuid.uuid4())

    async def event_generator():
        if request.use_celery:
            async with AsyncSessionLocal() as session:
                ctx = SharedContext(job_id=job_id, original_query=request.query, status="queued")
                await save_context(session, ctx)
            process_query.delay(job_id, request.query)
            yield sse_payload("agent_start", {"job_id": job_id, "agent_id": "orchestrator", "mode": "celery"})
            last_status = None
            while True:
                async with AsyncSessionLocal() as session:
                    job = await session.get(Job, job_id)
                    status = job.status if job else "queued"
                    context = job.full_context_json if job else {}
                if status != last_status:
                    yield sse_payload("context_budget_update", {"job_id": job_id, "status": status})
                    last_status = status
                if status in {"complete", "failed"}:
                    final_answer = (context or {}).get("final_answer")
                    yield sse_payload("pipeline_complete", {"job_id": job_id, "status": status, "final_answer": final_answer})
                    break
                await asyncio.sleep(1)
            return

        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def callback(event_type: str, payload: dict):
            await queue.put(sse_payload(event_type, payload))

        async def run_local():
            ctx = SharedContext(job_id=job_id, original_query=request.query, status="running")
            await run_full_pipeline(ctx, callback)
            async with AsyncSessionLocal() as session:
                await save_context(session, ctx)

        task = asyncio.create_task(run_local())
        while not task.done() or not queue.empty():
            try:
                yield await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
        if task.exception():
            yield sse_payload("pipeline_complete", {"job_id": job_id, "status": "failed", "error": str(task.exception())})

    return EventSourceResponse(event_generator())


@app.get("/jobs/{job_id}/trace")
async def job_trace(job_id: str, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.job_id,
        "query": job.query,
        "status": job.status,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
        "context": job.full_context_json,
    }


@app.get("/evals/latest")
async def latest_evals(session: AsyncSession = Depends(get_session)):
    return await get_latest_eval_summary(session)


@app.post("/rewrites/{rewrite_id}")
async def rewrite_action(rewrite_id: str, body: RewriteAction, session: AsyncSession = Depends(get_session)):
    if body.action not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Action must be approve or reject")
    return await handle_rewrite_action(session, rewrite_id, body.action)


@app.post("/evals/rerun")
async def rerun_evals(session: AsyncSession = Depends(get_session)):
    return await run_eval_suite(session=session, failed_only=True)

