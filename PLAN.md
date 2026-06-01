# aiTrate AI Agent v1 — Implementation Plan

## Overview
Build the aiTrate Co-Pilot v1: a RAG + Tool Use agent for the NARRUX trading platform. Following Claude's recommendation: **Pydantic AI + FastAPI** with framework-agnostic architecture.

## Architecture Decision
- **Framework**: Pydantic AI (fallback: Direct Build with Anthropic SDK)
- **Pattern**: Framework-agnostic core with adapter layer (`orchestration/` ≤ 400 LOC)
- **Timeline**: 8 weeks (6-week stretch goal)

---

## Project Structure

```
aiTrate-agent/
├── pyproject.toml                  # Project config, dependencies
├── .env.example                    # Environment variables template
├── .gitignore
├── README.md
│
├── prompts/                        # Versioned prompt templates (text files)
│   ├── system_v1.0.md              # System prompt
│   ├── f01_strategy_explainer.md
│   ├── f02_backtest_interpreter.md
│   ├── f03_tsi_grader.md
│   ├── f04_parameter_recommender.md
│   └── f05_drift_monitor.md
│
├── tools/                          # Pure Python, Pydantic schemas — NO framework imports
│   ├── __init__.py
│   ├── schemas.py                  # Pydantic models for all tool I/O
│   ├── tsi_engine.py               # Adapter for narrux_tsi_v2.py
│   ├── backtest_parser.py          # xlsx parser → trade record schema
│   ├── trade_db_reader.py          # Read-only PostgreSQL queries
│   ├── leverage_engine.py          # Adapter for narrux_leverage.py
│   └── knowledge_base.py           # KB lookup tools (parameter class, filter info)
│
├── retrieval/                      # Pure Python — NO framework imports
│   ├── __init__.py
│   ├── embeddings.py               # Voyage AI embedding client
│   ├── vector_store.py             # pgvector queries
│   ├── reranker.py                 # Voyage rerank-2 integration
│   ├── ingestion.py                # Document ingestion pipeline (parse → chunk → embed → store)
│   └── citation.py                 # Citation extraction + validation
│
├── validation/                     # Pure Python — NO framework imports
│   ├── __init__.py
│   ├── output_validator.py         # Cross-check claims against KB (param class, ranges)
│   └── citation_enforcer.py        # Citations-or-silence rule
│
├── audit/                          # Pure Python middleware
│   ├── __init__.py
│   └── logger.py                   # structlog → Postgres append-only table
│
├── orchestration/                  # ← ONLY framework-coupled code (≤400 LOC)
│   ├── __init__.py
│   ├── agent.py                    # Pydantic AI agent definition
│   ├── llm_client.py               # LLMClient protocol (interface)
│   ├── pydantic_ai_adapter.py      # Pydantic AI implementation of LLMClient
│   └── lifecycle.py                # Request → response loop
│
├── api/                            # FastAPI web layer
│   ├── __init__.py
│   ├── main.py                     # FastAPI app entry point
│   ├── routes.py                   # Chat, file upload, health endpoints
│   ├── auth.py                     # OAuth2/JWT + RBAC
│   └── streaming.py                # SSE streaming for LLM responses
│
├── db/                             # Database layer
│   ├── __init__.py
│   ├── models.py                   # SQLAlchemy models (audit log, conversations, trade DB)
│   ├── migrations/                 # Alembic migrations
│   └── session.py                  # Database session management
│
├── eval/                           # Evaluation harness
│   ├── __init__.py
│   ├── benchmark.py                # Eval runner (ragas + custom metrics)
│   ├── questions/                  # 200+ eval questions per pillar
│   │   ├── pillar_a.json           # Strategy knowledge questions
│   │   ├── pillar_b.json           # Backtest analysis questions
│   │   └── pillar_c.json           # Live oversight questions
│   └── metrics.py                  # Retrieval recall@k, faithfulness, answer relevancy
│
├── config/                         # Configuration
│   ├── __init__.py
│   └── settings.py                 # Pydantic Settings (env vars, feature flags)
│
├── tests/                          # Test suite
│   ├── test_tools/
│   ├── test_retrieval/
│   ├── test_validation/
│   ├── test_api/
│   └── test_orchestration/
│
└── scripts/                        # Utility scripts
    ├── ingest_kb.py                # Run KB ingestion pipeline
    ├── run_eval.py                 # Run evaluation harness
    └── seed_data.py                # Seed test data
```

---

## Implementation Phases

### Phase 1: Foundation (Week 1-2)
**Goal**: RAG pipeline working, can answer questions about strategies

1. **Project scaffolding**
   - `pyproject.toml` with dependencies
   - `.env.example` with all required env vars
   - `config/settings.py` with Pydantic Settings
   - Database models and migrations

2. **Retrieval layer** (`retrieval/`)
   - `embeddings.py` — Voyage AI client
   - `vector_store.py` — pgvector queries
   - `ingestion.py` — Parse .docx, .pine, .yaml → chunks → embeddings → store
   - `reranker.py` — Voyage rerank-2
   - `citation.py` — Extract and validate citations

3. **Knowledge base tools** (`tools/knowledge_base.py`)
   - Query parameter class (A/B/C)
   - Query filter info (F1-F30)
   - Query strategy specs

4. **Validation layer** (`validation/`)
   - `citation_enforcer.py` — Citations-or-silence rule
   - `output_validator.py` — Cross-check against KB

5. **Audit logger** (`audit/logger.py`)
   - Append-only log to Postgres
   - structlog integration

### Phase 2: Agent Core + F-01 (Week 3)
**Goal**: Agent can answer strategy questions with citations

1. **LLM client abstraction** (`orchestration/llm_client.py`)
   - Protocol/interface definition
   - Pydantic AI adapter

2. **Agent definition** (`orchestration/agent.py`)
   - System prompt
   - Tool registration
   - Citation enforcement

3. **F-01 Strategy Explainer** — end-to-end
   - User asks "What does F19 do?"
   - Agent queries KB → retrieves relevant chunks → reranks → generates cited answer
   - Audit log entry created

### Phase 3: Tool Layer (Week 4-5)
**Goal**: F-02, F-03, F-04, F-05 working

1. **Backtest parser** (`tools/backtest_parser.py`)
   - Parse TradingView xlsx exports
   - Normalize to trade record schema
   - Detect anomalies (PF<1.3, MDD>20%, SL ratio>40%)

2. **TSI engine adapter** (`tools/tsi_engine.py`)
   - Call narrux_tsi_v2.py
   - Return structured TSI score + grade

3. **Trade DB reader** (`tools/trade_db_reader.py`)
   - Read-only PostgreSQL queries
   - Compare backtest vs live trades

4. **Parameter recommender** (`tools/leverage_engine.py` + KB lookup)
   - Retrieve Class A/B/C info
   - Recommend adjustments within bounds

5. **F-02 through F-05** — wire tools into agent

### Phase 4: API + Integration (Week 6-7)
**Goal**: Production-ready API with UI integration

1. **FastAPI endpoints** (`api/`)
   - Chat endpoint (with SSE streaming)
   - File upload (xlsx, .pine, .json)
   - Health check
   - RBAC middleware

2. **Conversation state** (`db/`)
   - Store conversation history
   - Per-user context

3. **Sidebar UI integration**
   - Stable internal API for React frontend
   - Citation rendering format
   - File upload handling

### Phase 5: Eval + Polish (Week 8)
**Goal**: Evaluation harness passes, ready for shadow mode

1. **Evaluation harness** (`eval/`)
   - 200+ questions across Pillars A/B/C
   - Retrieval recall@k metrics
   - Faithfulness and answer relevancy
   - Regression gate (block release on failure)

2. **Production hardening**
   - Error handling and retry logic (tenacity)
   - Rate limiting
   - Graceful degradation (cached responses for FAQ)

---

## Dependencies (pyproject.toml)

```toml
[project]
name = "aitrate-agent"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
    # Web framework
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sse-starlette>=2.0.0",

    # LLM
    "anthropic>=0.40.0",
    "pydantic-ai>=0.0.14",

    # Embeddings & retrieval
    "voyageai>=0.3.0",
    "pgvector>=0.3.0",

    # Database
    "sqlalchemy[asyncio]>=2.0.0",
    "alembic>=1.14.0",
    "asyncpg>=0.30.0",
    "psycopg2-binary>=2.9.0",

    # Cache & background jobs
    "redis>=5.0.0",
    "arq>=0.26.0",

    # Data processing
    "openpyxl>=3.1.0",
    "pandas>=2.2.0",
    "numpy>=1.26.0",

    # Validation & schemas
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",

    # Observability
    "langfuse>=2.50.0",
    "structlog>=24.0.0",
    "opentelemetry-api>=1.28.0",

    # Evaluation
    "ragas>=0.2.0",

    # Utilities
    "tenacity>=9.0.0",
    "httpx>=0.28.0",
    "python-multipart>=0.0.18",
    "python-jose[cryptography]>=3.3.0",
]
```

---

## Key Design Decisions

### 1. LLMClient Protocol (Framework Independence)
```python
# orchestration/llm_client.py
from typing import Protocol
from pydantic import BaseModel

class LLMClient(Protocol):
    async def complete(
        self,
        prompt: str,
        tools: list[Tool],
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse: ...
```

### 2. Import Rules (Enforced in CI)
```
tools/          ← may NOT import from pydantic_ai
retrieval/      ← may NOT import from pydantic_ai
validation/     ← may NOT import from pydantic_ai
audit/          ← may NOT import from pydantic_ai
orchestration/  ← the ONLY module allowed to import pydantic_ai
```

### 3. Citation-or-Silence Flow
```
User query
    → Retrieval (top-50 chunks from pgvector)
    → Reranker (top-5-10 chunks)
    → LLM generates answer with citations
    → Citation enforcer validates:
        - Every claim has a source
        - Sources exist in KB
        - If no source → "I don't have enough information"
    → Output validator cross-checks facts against KB
    → Audit log entry
```

---

## Critical Dependencies (External)

| Dependency | Owner | Status | Blocks |
|------------|-------|--------|--------|
| Filter glossary F1-F30 | Frank | Not started | F-01 quality |
| Parameter class master (YAML) | Frank | Not started | F-04 quality |
| narrux_tsi_v2.py | Team A | Exists | F-03 |
| Unified trade DB | Team A | Needed | F-05 |
| TradingView xlsx exports | Manual | Available | F-02 |

---

## First Steps (What to Build Now)

1. Create project directory structure
2. Write `pyproject.toml` with dependencies
3. Write `.env.example` with all required env vars
4. Create `config/settings.py` with Pydantic Settings
5. Create database models (`db/models.py`)
6. Create the retrieval layer foundation (`retrieval/`)
7. Create the LLMClient protocol (`orchestration/llm_client.py`)
