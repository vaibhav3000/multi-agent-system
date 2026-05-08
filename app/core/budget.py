import tiktoken

from app.core.context_schema import AgentID, BudgetState, SharedContext
from app.core.logger import structured_log


AGENT_BUDGETS = {
    AgentID.ORCHESTRATOR: 4000,
    AgentID.DECOMPOSITION: 3000,
    AgentID.RETRIEVAL: 5000,
    AgentID.CRITIQUE: 4000,
    AgentID.SYNTHESIS: 6000,
    AgentID.COMPRESSION: 3000,
    AgentID.META: 4000,
}

encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(encoder.encode(text))


def register_agent_budget(ctx: SharedContext, agent_id: AgentID):
    if agent_id.value not in ctx.budget_states:
        ctx.budget_states[agent_id.value] = BudgetState(
            agent_id=agent_id,
            max_tokens=AGENT_BUDGETS[agent_id],
        )


def check_remaining_budget(ctx: SharedContext, agent_id: AgentID) -> int:
    state = ctx.budget_states.get(agent_id.value)
    if not state:
        raise ValueError(f"Agent {agent_id} has no registered budget")
    return state.max_tokens - state.used_tokens


def consume_budget(ctx: SharedContext, agent_id: AgentID, text: str) -> bool:
    tokens = count_tokens(text)
    state = ctx.budget_states.get(agent_id.value)
    if not state:
        raise ValueError(f"Agent {agent_id} has no registered budget")
    if state.used_tokens + tokens > state.max_tokens:
        violation_msg = (
            f"Agent {agent_id} attempted to use {tokens} tokens "
            f"but only {state.max_tokens - state.used_tokens} remain"
        )
        state.violations.append(violation_msg)
        structured_log(
            agent_id=agent_id.value,
            event_type="budget_violation",
            message=violation_msg,
            job_id=ctx.job_id,
        )
        return False
    state.used_tokens += tokens
    return True


def needs_compression(ctx: SharedContext, agent_id: AgentID, threshold: float = 0.85) -> bool:
    state = ctx.budget_states.get(agent_id.value)
    if not state:
        return False
    return (state.used_tokens / state.max_tokens) >= threshold

