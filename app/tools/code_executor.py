import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path


FORBIDDEN_IMPORT_RE = re.compile(
    r"^\s*(import\s+(os|sys|subprocess)(\s|,|$)|from\s+(os|sys|subprocess)\s+import\s+.*)$",
    re.MULTILINE,
)


def _strip_forbidden_imports(python_code: str) -> str:
    return FORBIDDEN_IMPORT_RE.sub("", python_code)


async def run_python_code(python_code: str) -> dict:
    start = time.time()
    if not isinstance(python_code, str):
        return {"error": "invalid_input", "code": "TOOL_MALFORMED", "stdout": "", "stderr": "", "exit_code": -1}

    sanitized = _strip_forbidden_imports(python_code)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "snippet.py"
            path.write_text(sanitized, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(path)],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=tmpdir,
            )
            latency_ms = (time.time() - start) * 1000
            return {
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "exit_code": completed.returncode,
                "latency_ms": latency_ms,
            }
    except subprocess.TimeoutExpired:
        return {
            "error": "timeout",
            "code": "TOOL_TIMEOUT",
            "stdout": "",
            "stderr": "Execution timed out",
            "exit_code": -1,
            "latency_ms": (time.time() - start) * 1000,
        }
    except Exception as exc:
        return {
            "error": "execution_error",
            "code": "TOOL_ERROR",
            "stdout": "",
            "stderr": str(exc),
            "exit_code": -1,
            "latency_ms": (time.time() - start) * 1000,
        }

