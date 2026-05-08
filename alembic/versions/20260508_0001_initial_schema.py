"""initial schema

Revision ID: 20260508_0001
Revises:
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260508_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("full_context_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_table(
        "eval_runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("test_case_id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("scores_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prompts_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tool_calls_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_eval_runs_job_id", "eval_runs", ["job_id"])
    op.create_table(
        "prompt_rewrites",
        sa.Column("rewrite_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("dimension", sa.String(length=128), nullable=False),
        sa.Column("original_prompt", sa.Text(), nullable=False),
        sa.Column("proposed_prompt", sa.Text(), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("rewrite_id"),
    )
    op.create_table(
        "performance_deltas",
        sa.Column("delta_id", sa.String(length=64), nullable=False),
        sa.Column("rewrite_id", sa.String(length=64), nullable=False),
        sa.Column("before_scores_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after_scores_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("delta_id"),
    )
    op.create_table(
        "agent_prompts",
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("active_prompt", sa.Text(), nullable=False),
        sa.Column("rewrite_id", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("agent_id"),
    )
    op.create_table(
        "execution_logs",
        sa.Column("log_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("output_hash", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("policy_violations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("log_id"),
    )
    op.create_index("ix_execution_logs_job_id", "execution_logs", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_execution_logs_job_id", table_name="execution_logs")
    op.drop_table("execution_logs")
    op.drop_table("agent_prompts")
    op.drop_table("performance_deltas")
    op.drop_table("prompt_rewrites")
    op.drop_index("ix_eval_runs_job_id", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_table("jobs")

