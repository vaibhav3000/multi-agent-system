import hashlib
import json
from datetime import datetime
from typing import Any, Optional


def hash_content(content: Any) -> str:
    serialized = json.dumps(content, default=str, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def structured_log(
    agent_id: str,
    event_type: str,
    input_data: Optional[Any] = None,
    output_data: Optional[Any] = None,
    latency_ms: Optional[float] = None,
    token_count: Optional[int] = None,
    policy_violations: Optional[list] = None,
    message: Optional[str] = None,
    job_id: Optional[str] = None,
) -> dict:
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "agent_id": agent_id,
        "event_type": event_type,
        "job_id": job_id,
        "input_hash": hash_content(input_data) if input_data else None,
        "output_hash": hash_content(output_data) if output_data else None,
        "latency_ms": latency_ms,
        "token_count": token_count,
        "policy_violations": policy_violations or [],
        "message": message,
    }
    print(json.dumps(entry), flush=True)
    return entry

