# Architecture

## Runtime Flow

```text
Client
  |
  | POST /query (SSE)
  v
FastAPI API -------------------- GET /jobs/{job_id}/trace
  |
  | enqueue Celery task
  v
Redis broker
  |
  v
Celery worker
  |
  v
SharedContext
  |
  +--> Orchestrator: decides dynamic route
  +--> Decomposition: builds dependency graph when useful
  +--> Retrieval: performs two-hop retrieval via web_search
  +--> Critique: scores claims and flags weak spans
  +--> Synthesis: resolves flags and emits final answer + provenance
  |
  v
PostgreSQL: jobs, eval runs, prompt rewrites, logs
```

## Agent Boundaries

- `orchestrator`: routing only. It should not answer the user directly.
- `decomposition`: task graph only. It should not retrieve evidence.
- `retrieval`: evidence gathering and cited intermediate answer.
- `critique`: claim-level confidence and flagging.
- `synthesis`: final answer, contradiction resolution, and provenance.
- `meta`: post-eval prompt rewrite proposals only. It never auto-applies rewrites.

## Data Model

`SharedContext` is the canonical in-memory handoff object. It stores the original query, subtasks, agent outputs, tool call log, budget state, routing log, final answer, and provenance map. Jobs persist the whole context as JSON so traces can be reconstructed.

## Evaluation Loop

The harness runs 15 cases across baseline, ambiguous, and adversarial categories. Each run is scored across correctness, citation accuracy, contradiction resolution, tool efficiency, budget compliance, and critique/synthesis agreement.

