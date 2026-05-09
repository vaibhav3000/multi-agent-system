# Multi-Agent LLM System

## 1. Overview
This is a production-grade multi-agent LLM system designed to tackle complex, multi-step user queries by coordinating specialized sub-agents. It breaks down tasks, retrieves necessary context, drafts responses, and critiques its own work before presenting the final answer. The system is designed to be provider-agnostic but primarily uses DeepSeek as the default LLM provider, while also supporting Groq, Gemini, and a Mock provider for testing. The goal is to create a robust, observable, and self-improving cognitive architecture.

## 2. Setup Instructions
To run this project locally, you will need Docker and Docker Compose installed.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/vaibhav3000/multi-agent-system.git
   cd multi-agent-system
   ```

2. **Configure environment variables:**
   Copy `.env.example` to `.env` and fill in your details:
   ```bash
   cp .env.example .env
   ```
   **Minimum Required Configuration:**
   - `LLM_PROVIDER`: Set to `deepseek`, `groq`, `gemini`, or `mock`.
   - Based on your choice, set the corresponding API key:
     - `DEEPSEEK_API_KEY=your_key_here`
     - `GROQ_API_KEY=your_key_here`
     - `GEMINI_API_KEY=your_key_here`
   - Database, Redis, and Chroma configuration are already provided in the `.env.example` and are ready for the docker stack.

3. **Start the system:**
   ```bash
   docker compose up --build -d
   ```
   - The API will be available on **port 8000** (`http://localhost:8000`).
   - The Log Viewer UI will be available on **port 8001** (`http://localhost:8001`).

## 3. Architecture Diagram
```ascii
          User Query
               |
         [ FastAPI (8000) ] 
          /           \
     SSE Stream     Celery Worker (async)
          \           /
        [ Orchestrator ] 
        /     |     \     \
   Decomp. Retrieve Synth. Critique
       \      |      |      /
      [ Shared Context / DB ] 
              |
       [ PostgreSQL ] --- [ Meta Agent (Self-Improving Loop) ]
              |
         [ Tools ] (Web Search, Code Executor, Data Lookup, Reflection)
              |
        [ LLM Provider ] (Deepseek, Groq, Gemini, Mock)
```

## 4. Agent Descriptions
- **Orchestrator**: The primary entry point for a user query. It decides which sub-agent should run next based on the current context state and the user's initial request. It operates with a moderate token budget and if it exceeds its budget, it is forced to synthesize whatever it has gathered to avoid looping infinitely.
- **Decomposition**: Takes a complex query and breaks it down into a list of simpler, actionable sub-tasks. Its decision boundary is strictly limited to task planning and does not execute the tasks itself. It has a strict token budget and will truncate context if exceeded.
- **Retrieval**: Responsible for gathering external information required to solve the sub-tasks by calling tools. It makes decisions purely on what information is missing. If it runs out of budget, it halts retrieval and passes the incomplete information back to the orchestrator.
- **Critique**: Reviews the drafted response against the original query to ensure all constraints and requirements are met. It decides whether the draft is sufficient or needs revision. If it exceeds its budget, the current draft is considered final by default to prevent analysis paralysis.
- **Synthesis**: Aggregates all gathered information and draft critiques into a final, coherent answer. Its boundary is strictly generating the final response. Exceeding its token budget results in aggressive summarization of the context.
- **Compression**: Analyzes the shared context when it grows too large and summarizes older or less relevant information. It runs continuously to keep the context window manageable for other agents.
- **Meta**: Observes the performance of all other agents by reviewing evaluation metrics and execution logs. It proposes prompt rewrites for underperforming agents to improve future performance. It does not execute queries directly and operates asynchronously from the main user flow.

## 5. Tool Descriptions
- **web_search**: Simulates or performs a web search to find current information on a given topic. On timeout, it returns a simulated error message; on empty results, it returns a message stating no results were found; on malformed input, it returns an error explaining the expected format.
- **code_executor**: Executes a small snippet of Python code in a controlled environment to perform calculations or logic. On timeout, it returns a "Timeout Exception"; on empty output, it returns "No output"; on malformed input, it returns a syntax error message.
- **data_lookup**: Retrieves structured data from a simulated internal database or vector store. On timeout, it returns a data retrieval timeout error; on empty, it returns "Data not found"; on malformed input, it returns an invalid query error.
- **self_reflection**: Allows an agent to pause and evaluate its own recent thoughts or actions. On timeout, it returns a reflection timeout; on empty, it returns a generic self-affirmation; on malformed input, it returns a formatting error.

## 6. API Reference
- **POST /query**
  - **Body**: `{"query": "string", "use_celery": boolean}`
  - **Success**: SSE Event stream yielding `{"event": "...", "payload": {"job_id": "...", ...}}`
  - **Error**: `{"error_code": "...", "message": "...", "job_id": "..."}`
- **GET /jobs/{job_id}/trace**
  - **Body**: None
  - **Success**: `{"job_id": "...", "query": "...", "status": "...", "created_at": "...", "completed_at": "...", "context": {...}}`
  - **Error**: `{"error_code": "JOB_NOT_FOUND", "message": "Job not found", "job_id": "..."}`
- **GET /evals/latest**
  - **Body**: None
  - **Success**: `{"total_runs": int, "average_scores": {...}, ...}`
  - **Error**: `{"error_code": "...", "message": "..."}`
- **POST /rewrites/{rewrite_id}**
  - **Body**: `{"action": "approve" | "reject"}`
  - **Success**: `{"status": "success", "message": "..."}`
  - **Error**: `{"error_code": "INVALID_REWRITE_ACTION", "message": "..."}`
- **POST /evals/rerun**
  - **Body**: None
  - **Success**: `{"status": "eval_suite_completed", "total_runs": int, "average_scores": {...}}`
  - **Error**: `{"error_code": "...", "message": "..."}`
- **GET /health**
  - **Body**: None
  - **Success**: `{"status": "ok"}`
  - **Error**: N/A

## 7. Evaluation Pipeline
The system includes 15 curated test cases:
- **5 Baseline**: Straightforward queries with clear, expected answers.
- **5 Ambiguous**: Queries lacking context, requiring the system to make reasonable assumptions or ask for clarification.
- **5 Adversarial**: Queries designed to trick the system, prompt-inject, or request impossible guarantees.

These are scored across 6 dimensions:
1. Answer Correctness
2. Citation Accuracy
3. Contradiction Resolution
4. Tool Efficiency
5. Budget Compliance
6. Critique Agreement

Eval runs are persisted in PostgreSQL, allowing for historical comparisons. Performance deltas are calculated between runs, making diffs visible to track regression or improvement over time.

## 8. Self-Improving Loop
The Meta-Agent runs periodically to analyze system performance.
1. It queries the `eval_runs` table to find the worst performing evaluation case.
2. It identifies the worst-scoring dimension for that case.
3. It maps the poor dimension to the responsible agent (e.g., poor Tool Efficiency maps to Retrieval).
4. It proposes a prompt rewrite for that agent to address the deficiency.
5. The rewrite is stored in the `prompt_rewrites` table as `pending`.
6. A human must manually approve the rewrite via the API.
7. Upon approval, the rewrite is applied to the `agent_prompts` table, and agents dynamically load it at runtime via `get_active_prompt`.
8. The system reruns the failed test cases to measure improvement.
9. A performance delta is logged.

**What it does not do:** It does NOT auto-apply rewrites, it does NOT retrain the base LLM model, and it does NOT continuously loop and mutate prompts without human involvement.

## 9. Known Limitations
- The system uses a stub search implementation unless `SEARCH_API_URL` is configured.
- The SSE endpoint uses event-level streaming, not true granular token streaming.
- The `code_executor` tool relies on python's `eval`/`exec` locally and is **not** a production-safe secure sandbox.
- There is currently no authentication or authorization on any endpoint.
- Execution logs are written synchronously to PostgreSQL, which could bottleneck response times under high concurrency loads.

## 10. What to Build Next
1. **Secure Sandbox**: Implement a Firecracker microVM or gVisor for the code executor tool.
2. **True Token Streaming**: Refactor the agent loops to yield token-by-token for a better UX.
3. **Authentication**: Add JWT or API Key based auth middleware to secure all endpoints.
4. **Live Web Search**: Integrate Tavily or Serper API for real-time, accurate web search.
5. **Asynchronous Logging**: Move `execution_logs` writes to a background queue or Kafka to improve API latency.
6. **Advanced Meta-Agent Analysis**: Implement clustering on user queries to find patterns in edge-case failures.
7. **Frontend Dashboard**: Build a React/Next.js dashboard to manage rewrites and view traces visually.

## 11. AI Collaboration Notes
AI assistance was kept to an absolute minimum throughout this project. AI tools were strictly used for debugging complex issues and resolving runtime errors, while all core logic, orchestration, and architectural designs were completed manually.
