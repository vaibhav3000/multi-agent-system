import os
import uuid
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import DateTime, Float, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://user:pass@localhost:5432/agentdb",
) or "postgresql+asyncpg://user:pass@localhost:5432/agentdb"


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    full_context_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    run_id: Mapped[str] = mapped_column(String(64), default=lambda: str(uuid.uuid4()), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    test_case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    scores_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    prompts_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_calls_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)


class PromptRewrite(Base):
    __tablename__ = "prompt_rewrites"

    rewrite_id: Mapped[str] = mapped_column(String(64), default=lambda: str(uuid.uuid4()), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension: Mapped[str] = mapped_column(String(128), nullable=False)
    original_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    diff: Mapped[str] = mapped_column(Text, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PerformanceDelta(Base):
    __tablename__ = "performance_deltas"

    delta_id: Mapped[str] = mapped_column(String(64), default=lambda: str(uuid.uuid4()), primary_key=True)
    rewrite_id: Mapped[str] = mapped_column(String(64), nullable=False)
    before_scores_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    after_scores_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    log_id: Mapped[str] = mapped_column(String(64), default=lambda: str(uuid.uuid4()), primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_violations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_latest_eval_summary(session: AsyncSession) -> dict:
    result = await session.execute(select(EvalRun).order_by(EvalRun.timestamp.desc()).limit(50))
    rows = result.scalars().all()
    grouped: dict[str, dict] = {}
    for row in rows:
        category = row.category
        grouped.setdefault(category, {"count": 0, "overall_average": 0.0, "dimensions": {}})
        grouped[category]["count"] += 1
        grouped[category]["overall_average"] += row.scores_json.get("overall_average", 0.0)
        for name, value in row.scores_json.items():
            if isinstance(value, dict) and "score" in value:
                grouped[category]["dimensions"].setdefault(name, []).append(value["score"])
    for category, data in grouped.items():
        count = max(data["count"], 1)
        data["overall_average"] = data["overall_average"] / count
        data["dimensions"] = {
            name: sum(scores) / len(scores)
            for name, scores in data["dimensions"].items()
        }
    return grouped
