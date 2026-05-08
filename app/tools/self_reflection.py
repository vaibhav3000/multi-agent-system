from app.core.context_schema import AgentID, SharedContext


async def run_self_reflection(ctx: SharedContext, agent_id: AgentID | str):
    try:
        key = agent_id.value if isinstance(agent_id, AgentID) else str(agent_id)
        outputs = []
        for existing_agent_id, agent_output in ctx.agent_outputs.items():
            if existing_agent_id == key:
                output = agent_output.output
                outputs.append(output if isinstance(output, str) else str(output))
        if not outputs:
            return {"error": "no_prior_outputs", "code": "TOOL_EMPTY"}
        return outputs
    except Exception as exc:
        return {"error": "reflection_error", "code": "TOOL_ERROR", "detail": str(exc)}

