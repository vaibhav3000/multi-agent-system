from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import ExecutionLog, get_session, init_db

app = FastAPI(title="Log UI")


@app.on_event("startup")
async def startup() -> None:
    await init_db()


@app.get("/logs")
async def logs(job_id: str | None = None, limit: int = 100, session: AsyncSession = Depends(get_session)):
    query = select(ExecutionLog).order_by(ExecutionLog.timestamp.desc()).limit(limit)
    if job_id:
        query = select(ExecutionLog).where(ExecutionLog.job_id == job_id).order_by(ExecutionLog.timestamp.desc()).limit(limit)
    result = await session.execute(query)
    return [
        {
            "log_id": row.log_id,
            "job_id": row.job_id,
            "agent_id": row.agent_id,
            "event_type": row.event_type,
            "latency_ms": row.latency_ms,
            "token_count": row.token_count,
            "timestamp": row.timestamp,
        }
        for row in result.scalars().all()
    ]

