from datetime import datetime
from enum import Enum
from typing import Any, Optional
import uuid

from pydantic import BaseModel, Field


class AgentID(str, Enum):
    ORCHESTRATOR = "orchestrator"
    DECOMPOSITION = "decomposition"
    RETRIEVAL = "retrieval"
    CRITIQUE = "critique"
    SYNTHESIS = "synthesis"
    COMPRESSION = "compression"
    META = "meta"


class SubTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    depends_on: list[str] = Field(default_factory=list)
    status: str = "pending"
    result: Optional[Any] = None
    assigned_agent: Optional[AgentID] = None


class ToolCall(BaseModel):
    tool_name: str
    input: dict
    output: Optional[Any] = None
    latency_ms: Optional[float] = None
    accepted: Optional[bool] = None
    retry_count: int = 0
    failure_reason: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ClaimScore(BaseModel):
    claim_text: str
    confidence: float
    flagged: bool = False
    flag_reason: Optional[str] = None


class AgentOutput(BaseModel):
    agent_id: AgentID
    output: Any
    token_count: int = 0
    tool_calls: list[ToolCall] = Field(default_factory=list)
    claim_scores: list[ClaimScore] = Field(default_factory=list)
    provenance: dict[str, str] = Field(default_factory=dict)


class BudgetState(BaseModel):
    agent_id: AgentID
    max_tokens: int
    used_tokens: int = 0
    violations: list[str] = Field(default_factory=list)


class SharedContext(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_query: str
    subtasks: list[SubTask] = Field(default_factory=list)
    agent_outputs: dict[str, AgentOutput] = Field(default_factory=dict)
    tool_call_log: list[ToolCall] = Field(default_factory=list)
    budget_states: dict[str, BudgetState] = Field(default_factory=dict)
    routing_log: list[dict] = Field(default_factory=list)
    final_answer: Optional[str] = None
    provenance_map: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "pending"

