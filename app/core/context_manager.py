from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context_schema import SharedContext
from app.core.database import Job


async def save_context(session: AsyncSession, ctx: SharedContext) -> None:
    data = ctx.model_dump(mode="json")
    job = await session.get(Job, ctx.job_id)
    if job is None:
        job = Job(
            job_id=ctx.job_id,
            query=ctx.original_query,
            status=ctx.status,
            full_context_json=data,
        )
        session.add(job)
    else:
        job.status = ctx.status
        job.full_context_json = data
        if ctx.status in {"complete", "failed"}:
            job.completed_at = datetime.utcnow()
    await session.commit()


async def load_context(session: AsyncSession, job_id: str) -> SharedContext | None:
    result = await session.execute(select(Job).where(Job.job_id == job_id))
    job = result.scalar_one_or_none()
    if not job or not job.full_context_json:
        return None
    return SharedContext.model_validate(job.full_context_json)

