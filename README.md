# Multi-Agent LLM System

A FastAPI + Celery + PostgreSQL + Redis scaffold for a multi-agent LLM pipeline using DeepSeek by default, with optional Groq, Gemini, or mock providers, SSE streaming, explicit tool failure contracts, and an evaluation-driven prompt rewrite loop.

## Setup Instructions

1. Copy environment variables:

```bash
cp .env.example .env
```

2. Choose an LLM provider in `.env`.

DeepSeek is the primary/default provider:

```env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_key
DEEPSEEK_MODEL=deepseek-chat
```

For Groq:

```env
LLM_PROVIDER=groq
GROQ_API_KEY=your_key
GROQ_MODEL=llama-3.3-70b-versatile
```

For a no-credit plumbing test:

```env
LLM_PROVIDER=mock
```

For Gemini:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-1.5-flash
```

Then adjust database or Redis URLs if needed.

3. Start the stack:

```bash
docker compose up --build
```

4. API runs on `http://localhost:8000`; log UI runs on `http://localhost:8001`.

## Architecture Diagram

```text
User
  |
  v
FastAPI /query (SSE)
  |
  v
Redis + Celery worker
  |
  v
DeepSeek -> Orchestrator -> Decomposition -> Retrieval -> Critique -> Synthesis
                     |              |
                     |              +-> web_search tool
                     |
                     +-> SharedContext
  |
  v
PostgreSQL trace, eval, rewrite, and log tables
```

## Agent Descriptions and Decision Boundaries

- `orchestrator` chooses the next agents and execution order from the current context.
- `decomposition` creates subtasks and dependency relationships.
- `retrieval` performs two-hop retrieval and maps claims to chunks.
- `critique` scores claims, flags unsupported or contradictory spans, and avoids blanket rejection.
- `synthesis` resolves flagged claims and writes the final answer with provenance.
- `compression` can summarize context when budgets become tight.
- `meta` inspects poor eval runs and stores prompt rewrite proposals with `pending` status.

## API Routes

- `POST /query`: streams SSE events while a query job runs.
- `GET /jobs/{job_id}/trace`: returns the persisted execution trace.
- `GET /evals/latest`: returns latest eval summary grouped by category.
- `POST /rewrites/{rewrite_id}`: approve or reject a proposed prompt rewrite.
- `POST /evals/rerun`: reruns evals on previously failed cases.

## Known Limitations

- The default web search tool returns structured stub results unless `SEARCH_API_URL` is provided.
- `LLM_PROVIDER=mock` verifies application plumbing but does not produce factual model answers.
- The prompt rewrite approval flow records approval, stores the approved prompt in the prompt registry, and reruns failed eval cases.
- SSE token streaming is event-level rather than true model token passthrough.
- The code executor uses basic import stripping and is not a production security sandbox.

## What the Self-Improving Loop Does and Does Not Do

It finds the lowest-scoring eval run, identifies the weakest scoring dimension, maps that dimension to the likely responsible agent, asks the configured LLM (DeepSeek by default) for a structured prompt rewrite, and stores the rewrite as `pending`.

It does not automatically change live prompts. Approval is explicit; approved rewrites are stored as active prompts and before/after eval deltas are recorded.

## What to Build Next

- Replace stub search with a production search API.
- Add authentication and tenant boundaries before exposing this outside local development.
