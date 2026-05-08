import json
import os

from anthropic import Anthropic

from app.core.budget import consume_budget, register_agent_budget
from app.core.context_schema import AgentID, AgentOutput, SharedContext
from app.core.logger import structured_log

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", "missing"))

COMPRESSION_SYSTEM = """Compress shared context for downstream agents.
Preserve open tasks, key claims, citations, budget state, and unresolved critique flags.
Return JSON with keys: summary, preserved_claims, dropped_details.
"""


async def run_compression(ctx: SharedContext) -> dict:
    register_agent_budget(ctx, AgentID.COMPRESSION)
    prompt = json.dumps(ctx.model_dump(mode="json"), default=str)[:6000]
    if not consume_budget(ctx, AgentID.COMPRESSION, prompt):
        result = {"summary": "Compression budget exceeded", "preserved_claims": [], "dropped_details": []}
    else:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1200,
            system=COMPRESSION_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            result = json.loads(response.content[0].text)
        except json.JSONDecodeError:
            result = {"summary": response.content[0].text, "preserved_claims": [], "dropped_details": []}
    structured_log(
        agent_id=AgentID.COMPRESSION.value,
        event_type="compression_complete",
        output_data=result,
        job_id=ctx.job_id,
    )
    ctx.agent_outputs[AgentID.COMPRESSION.value] = AgentOutput(
        agent_id=AgentID.COMPRESSION,
        output=result,
    )
    return result
