import json
from typing import Any


def sse_payload(event: str, data: dict[str, Any]) -> dict:
    return {"event": event, "data": json.dumps(data, default=str)}

