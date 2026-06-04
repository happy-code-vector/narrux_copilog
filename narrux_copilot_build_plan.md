# NARRUX aiTrate Co-Pilot — Local Build Plan
## Complete prompt sequence for scaffolding the project architecture

**How to use this file:**
Read the CONTEXT section first — it tells your AI everything about the project.
Then run each PROMPT in sequence. Each prompt is self-contained and references the context.
Do not skip prompts. Each one builds on the previous.

---

# CONTEXT (read this before running any prompt)

## What this project is

The NARRUX aiTrate Co-Pilot is a RAG-based AI agent embedded in a quantitative crypto/multi-asset trading platform. It is NOT a generic chatbot. It is a domain-specialised co-pilot that compresses institutional trading knowledge into a single queryable interface.

**Role:** Co-pilot, not autopilot. Read-only in v1. Every recommendation requires human confirmation before action.

**v1 delivers five functions:**
- F-01: Strategy explainer — "what does filter D1 do?", "explain BE2 logic"
- F-02: Backtest interpreter — upload xlsx → TSI score + anomalies + commentary
- F-03: TSI auto-grader — compute/store TSI v2.0 CA score per strategy
- F-04: Parameter recommender — class-governed parameter adjustment proposals
- F-05: Drift monitor — compare live vs backtest, flag slippage breaches

**Three non-negotiable values in priority order:**
1. Accuracy — citations-or-silence, no hallucination
2. Auditability — every output permanently reconstructable
3. Time-to-ship — 6–8 weeks

---

## Locked stack (do not propose alternatives)

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Web framework | FastAPI |
| Agent framework | Pydantic AI (orchestration/ only) |
| LLM primary | claude-opus-4-7 (Pillars A/B: F-01, F-02, F-04) |
| LLM secondary | claude-sonnet-4-6 (routing/formatting: F-03, F-05) |
| Embeddings | Voyage AI voyage-3-large |
| Reranker | Voyage AI rerank-2 |
| Vector store | pgvector (PostgreSQL 16) |
| Primary DB | PostgreSQL 16 |
| Cache/broker | Redis |
| Background jobs | Arq |
| Observability | Langfuse + OpenTelemetry |
| Eval | ragas + custom harness |
| Container | Docker |
| Auth | OAuth2/JWT, RBAC |

---

## Three binding rules (enforced by CI)

**Rule 1 — Framework isolation:**
`tools/`, `retrieval/`, `validation/`, `audit/` MUST NOT import from `pydantic_ai`.
`orchestration/` is the ONLY directory permitted to import `pydantic_ai`.
`api/` may import `orchestration/` but not `pydantic_ai` directly.
Enforced by `import-linter`. Build fails on violation.
`orchestration/` LOC budget: ≤ 500 lines.

**Rule 1.5 — Parallel migration test:**
Build `orchestration/direct_adapter.py` (Anthropic SDK directly) alongside `orchestration/pydantic_ai_adapter.py`. Eval harness runs against both. Materially different outputs = abstraction leaking → refactor before merge.

**Rule 2 — No LangGraph:**
Pydantic AI is the framework for v1 and beyond. Do not anticipate LangGraph.

**Rule 3 — KB authoring on critical path:**
Filter glossary F1–F30, parameter class master, edge-case playbook are authored in parallel. If KB slips, ship date slips.

---

## Repo structure (exact — do not deviate)

```
narrux_agent/
├── prompts/
│   ├── system_v1_0.md
│   ├── f01_strategy_explainer.md
│   ├── f02_backtest_interpreter.md
│   ├── f03_tsi_scorer.md
│   ├── f04_parameter_recommender.md
│   ├── f05_drift_monitor.md
│   └── citation_enforcement.md
├── tools/                        # NO pydantic_ai imports
│   ├── schemas.py
│   ├── tsi_engine.py
│   ├── backtest_parser.py
│   ├── trade_db_reader.py
│   ├── leverage_engine.py
│   └── kb_lookup.py
├── retrieval/                    # NO pydantic_ai imports
│   ├── embeddings.py
│   ├── vector_store.py
│   ├── reranker.py
│   ├── citation.py
│   └── ingestion.py
├── validation/                   # NO pydantic_ai imports
│   ├── output_validator.py
│   ├── citation_enforcer.py
│   └── schema_validator.py
├── audit/                        # NO pydantic_ai imports
│   ├── logger.py
│   └── models.py
├── orchestration/                # ONLY layer that may import pydantic_ai
│   ├── agent.py
│   ├── llm_client.py
│   ├── pydantic_ai_adapter.py
│   ├── direct_adapter.py
│   └── lifecycle.py
├── api/                          # FastAPI; imports orchestration only
│   ├── main.py
│   ├── routes/
│   │   ├── chat.py
│   │   ├── backtest.py
│   │   └── health.py
│   ├── auth.py
│   ├── middleware.py
│   └── streaming.py
├── kb_content/
│   ├── filters/                  # F01.md ... F30.md (Frank's deliverables)
│   ├── parameters/               # param_class_master.yaml
│   ├── playbook/
│   └── strategies/
├── eval/
│   ├── pillar_a_questions.yaml
│   ├── pillar_b_questions.yaml
│   ├── pillar_c_questions.yaml
│   ├── retrieval_eval.py
│   ├── e2e_eval.py
│   └── adversarial.py
├── migrations/
│   └── init.sql
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── scripts/
│   └── ingest.py
├── .importlinter
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── .env.example
```

---

## Domain knowledge your AI must not hallucinate

### Parameter governance classes
- **Class A (Set & Forget):** RSI, BB%, ATR, Supertrend, EMA, time filter. Stationary 12+ months. Never propose on single-backtest evidence.
- **Class B (Quarterly drift):** ADX, MACD, BB Width, trailing stop. Require ≥3 backtests before proposing change.
- **Class C (Regime-coupled):** ALL volume-based — CVD, CMF, MFI, volume, spike, momentum-override. Always flag as non-stationary. Strong backtest ≠ forward stability.

### TSI grade → leverage cap (fixed, non-negotiable)
- S → 3.0x, A → 2.0x, B → 1.5x, C → 1.0x (no leverage), D → 0x

### Backtest integrity rules
- Returns against NARRUX capital basis (order_size × 1.10), NOT TradingView initial_capital
- `calc_on_order_fills` MUST be false
- Bar Magnifier exit drift baseline: ~0.19% per exit
- Stop-loss ratio >40% over 20 trades = regime-stress emergency-brake signal

### Alert wire formats
- Alpha v15.9.1: JSON object
- Sentinel v1.9: CSV positional string (e.g. `NARRUX_SENTINEL,long,entry,qty=1.5`)
- Bridge MUST branch on payload shape before parsing — this is code, not documentation

### Document format (important for ingestion pipeline)
All project documents are ZIP archives with .pdf extensions containing:
- N.jpeg files (page images)
- N.txt files (extracted text, one per page)
The ingestion pipeline must detect ZIP magic bytes (PK\x03\x04) and read .txt files, NOT treat them as real PDFs.

---

# PROMPTS

Run these in order. Paste the full prompt text into your local AI each time.

---

## PROMPT 1 — Project scaffold + config

```
You are building the NARRUX aiTrate Co-Pilot, a RAG-based trading strategy co-pilot.

Read the CONTEXT section of the build plan before writing any code.

Your task: create the complete project scaffold.

Create these files with the EXACT content specified:

### 1. pyproject.toml
Python 3.11+. Dependencies:
- fastapi>=0.115.0, uvicorn[standard]>=0.30.0
- pydantic-ai>=0.0.14
- anthropic>=0.36.0
- voyageai>=0.3.0
- pgvector>=0.3.0, psycopg[binary,pool]>=3.2.0
- sqlalchemy>=2.0.0, alembic>=1.13.0
- pydantic>=2.8.0, pydantic-settings>=2.4.0
- redis>=5.0.0, arq>=0.26.0
- openpyxl>=3.1.0, python-docx>=1.1.0
- langfuse>=2.0.0
- opentelemetry-api>=1.27.0, opentelemetry-sdk>=1.27.0
- opentelemetry-instrumentation-fastapi>=0.48b0
- structlog>=24.0.0
- ragas>=0.2.0
- httpx>=0.27.0, tenacity>=9.0.0
- python-multipart>=0.0.12
- python-jose[cryptography]>=3.3.0, passlib[bcrypt]>=1.7.4
- pyyaml>=6.0, tiktoken>=0.7.0
dev extras: pytest>=8.0.0, pytest-asyncio>=0.24.0, pytest-cov>=5.0.0, import-linter>=2.1, ruff>=0.6.0, mypy>=1.11.0

### 2. .importlinter
Enforce Rule 1. Four contracts:
- "framework-isolation": source_modules = tools, retrieval, validation, audit. forbidden = pydantic_ai
- "api-no-framework": source_modules = api. forbidden = pydantic_ai
- "tools-independence": source_modules = tools, retrieval, validation, audit. forbidden = narrux_agent.orchestration
- "retrieval-independence": source_modules = retrieval. forbidden = tools.tsi_engine, tools.backtest_parser, tools.trade_db_reader, tools.leverage_engine

### 3. docker-compose.yml
Services: postgres (pgvector/pgvector:pg16), redis (redis:7-alpine), langfuse (langfuse/langfuse:2), agent.
Postgres healthcheck: pg_isready. Redis healthcheck: redis-cli ping.
Agent mounts kb_content/ and prompts/ as read-only volumes.
Langfuse depends on postgres healthcheck passing.
All credentials from environment variables with dev defaults.

### 4. Dockerfile
Python 3.11-slim. Install libpq-dev. pip install -e . Non-root user narrux uid 1000.

### 5. .env.example
Variables needed:
DATABASE_URL, POSTGRES_USER/PASSWORD/DB, REDIS_URL,
ANTHROPIC_API_KEY, ANTHROPIC_MODEL_PRIMARY=claude-opus-4-7, ANTHROPIC_MODEL_SECONDARY=claude-sonnet-4-6,
VOYAGE_API_KEY, VOYAGE_EMBEDDING_MODEL=voyage-3-large, VOYAGE_RERANK_MODEL=rerank-2,
LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY,
JWT_SECRET_KEY, JWT_ALGORITHM=HS256, JWT_EXPIRE_MINUTES=480,
RETRIEVAL_TOP_K=20, RERANK_TOP_N=5, MIN_RERANK_SCORE=0.3,
CHUNK_SIZE_TOKENS=400, CHUNK_OVERLAP_TOKENS=80,
DAILY_TOKEN_CAP_PER_USER=100000, MAX_TOKENS_PER_RESPONSE=4096

### 6. narrux_agent/config.py
Pydantic BaseSettings. Single lru_cache get_settings() function. All env vars typed. Never hardcode secrets.

### 7. Create all __init__.py files for packages:
narrux_agent/, narrux_agent/tools/, narrux_agent/retrieval/, narrux_agent/validation/,
narrux_agent/audit/, narrux_agent/orchestration/, narrux_agent/api/, narrux_agent/api/routes/

### 8. Create empty placeholder files (just docstrings, no logic yet):
tools/tsi_engine.py, tools/backtest_parser.py, tools/trade_db_reader.py,
tools/leverage_engine.py, tools/kb_lookup.py

Also create directory structure for:
kb_content/filters/, kb_content/parameters/, kb_content/playbook/, kb_content/strategies/
eval/, migrations/, tests/unit/, tests/integration/, scripts/
```

---

## PROMPT 2 — Database schema

```
You are building the NARRUX aiTrate Co-Pilot. Read the CONTEXT from the build plan.

Your task: create migrations/init.sql — the complete PostgreSQL 16 + pgvector database schema.

Requirements:

**Extensions:** vector, uuid-ossp

**Table: kb_documents**
Columns: doc_id (TEXT PK), doc_version, title, scope, strategy (nullable), volume (nullable),
module_id (nullable), owner, last_updated (TIMESTAMPTZ), supersedes (FK to self, nullable),
deprecated (BOOLEAN DEFAULT FALSE), created_at.

**Table: kb_chunks** (the vector store)
Columns: chunk_id (TEXT PK), doc_id (FK → kb_documents CASCADE DELETE), doc_version,
content (TEXT), token_count (INTEGER), embedding VECTOR(1024), metadata JSONB DEFAULT '{}', created_at.
Index: HNSW on embedding using vector_cosine_ops, m=16, ef_construction=64.
Index: GIN on metadata for JSONB filtering.
Index: btree on doc_id.

**Table: audit_log** (APPEND-ONLY — this is critical)
Columns: entry_id (UUID PK DEFAULT uuid_generate_v4()), response_id (UUID), user_id, function_id,
prompt_template_version, system_prompt_hash, user_message, retrieval_query,
retrieval_results (JSONB DEFAULT '[]'), rerank_scores (JSONB DEFAULT '[]'),
llm_model, llm_input_tokens (INTEGER DEFAULT 0), llm_output_tokens (INTEGER DEFAULT 0),
llm_cost_usd (NUMERIC(10,6) DEFAULT 0), raw_llm_response (TEXT), parsed_response (JSONB DEFAULT '{}'),
validator_log (JSONB DEFAULT '{}'), duration_ms (INTEGER DEFAULT 0), timestamp (TIMESTAMPTZ DEFAULT NOW()).
CRITICAL: Add Postgres RULE to deny UPDATE and deny DELETE on audit_log.
This enforces append-only at the database level, not just application level.

**Table: trade_records**
Columns: trade_id (UUID PK), strategy_id, asset, timeframe,
source (TEXT CHECK IN backtest/live), execution_mode (TEXT CHECK IN CLOSED/INTRABAR),
side (TEXT CHECK IN long/short), entry_time/exit_time (TIMESTAMPTZ),
entry_price/exit_price (NUMERIC(18,8)), size, pnl, pnl_pct (NUMERIC(10,6)),
mae/mfe (NUMERIC(10,6) DEFAULT 0), entry_method (nullable), exit_reason (DEFAULT ''),
filters_fired TEXT[] DEFAULT '{}', regime_label (nullable), params_hash (nullable),
capital_basis (NUMERIC(18,8) nullable), created_at.
Indexes: (strategy_id, asset, source), (entry_time DESC).

**Table: tsi_scores**
Columns: score_id (UUID PK), strategy_id, asset, period_start/end (TIMESTAMPTZ),
components (JSONB DEFAULT '{}'), weighted_score (NUMERIC(6,2)), grade (TEXT CHECK IN S/A/B/C/D),
leverage_cap (NUMERIC(4,1)), dq_triggers TEXT[] DEFAULT '{}',
computed_from_raw (BOOLEAN DEFAULT FALSE), computed_at (TIMESTAMPTZ DEFAULT NOW()).
Index: (strategy_id, asset, computed_at DESC).
```

---

## PROMPT 3 — Core schemas (tools/schemas.py)

```
You are building the NARRUX aiTrate Co-Pilot. Read the CONTEXT from the build plan.

Your task: create narrux_agent/tools/schemas.py — all Pydantic contracts.
NO pydantic_ai imports. NO fastapi imports. Pure pydantic v2 + stdlib only.

Create the following models exactly:

**Enums:**
- ParameterClass(str, Enum): A, B, C — with docstring explaining each
- TSIGrade(str, Enum): S, A, B, C, D — with leverage cap in comment
- ConfidenceLevel(str, Enum): high, medium, low, abstain
- FunctionID(str, Enum): F-01 through F-05
- AlertFormat(str, Enum): alpha_json, sentinel_csv
- DocumentScope(str, Enum): governance, strategy, filter_glossary, parameter_master, process, report_template, playbook

**KBDocument:** doc_id (snake_case validated), doc_version, title, scope, strategy|None, volume|None, module_id|None, owner, last_updated, supersedes|None, deprecated=False

**KBChunk:** chunk_id, doc_id, doc_version, content, token_count, embedding list[float]|None=None, metadata dict={}

**Citation:** doc_id, doc_version, chunk_id, source_type Literal[spec/pine/playbook/filter_glossary/param_master/handbook], citation_handle, relevance_score, excerpt (max_length=300)

**TradeRecord:** All fields from spec §4.3 — trade_id UUID, strategy_id, asset, timeframe, source Literal[backtest/live], execution_mode Literal[CLOSED/INTRABAR], side Literal[long/short], entry_time/exit_time datetime, entry_price/exit_price float, size, pnl, pnl_pct, mae=0.0, mfe=0.0, entry_method|None, exit_reason="", filters_fired list[str]=[], regime_label|None, params_hash|None, capital_basis|None.
Add validator comment on pnl_pct explaining NARRUX capital basis rule (order_size × 1.10).

**BacktestSummary:** strategy_id, asset, timeframe, period_start/end, total_trades, win_rate, profit_factor, net_pnl, net_pnl_pct, max_drawdown_pct, sharpe_ratio, stop_loss_count, stop_loss_ratio (flag if >0.40), capital_basis, calc_on_order_fills bool, process_orders_on_close bool, execution_mode.

**TSIResult:** strategy_id, asset, period_start/end, components dict[str,float], weighted_score, grade TSIGrade, leverage_cap float, dq_triggers list[str], reconstruction_tolerance float|None=None, computed_from_raw_csv bool=False. Add method leverage_cap_for_grade() returning correct cap from grade.

**Recommendation:** parameter_name, parameter_class ParameterClass, current_value, recommended_value, within_bounds bool (MUST be True or rejected), bounds tuple|None, evidence_backtest_count=0, regime_label|None, rationale, citations list[Citation]=[], expected_impact, risk_notes, governance_check_passed bool=False.

**DriftStatus(str, Enum):** stable, watch, breach

**DriftReport:** strategy_id, asset, window_trades, avg_exit_slippage_pct, rolling_drift_pct, drift_status DriftStatus, breach_threshold_pct=0.4, stop_loss_ratio, tsi_grade_current|None, tsi_grade_previous|None, grade_transition|None, flags list[str]=[], recommended_action="", authority_role Literal[veto/override/advisory]="advisory"

**AgentResponse:** response_id UUID, function_id FunctionID, content str, citations list[Citation]=[], structured_output dict|None=None, confidence ConfidenceLevel, validator_results dict={}, generated_at datetime.

**AlphaWebhookAlert:** symbol, side, action, qty, price|None, position_size|None, htf_bias|None, reason|None, level|None

**SentinelWebhookAlert:** raw, bot_name, side, action, qty|None, reason|None, level|None. Add classmethod from_csv(payload: str) that parses "botName,side,action[,key=value...]"

**parse_webhook_alert(payload: str):** branches on payload.strip().startswith("{") → AlphaWebhookAlert, else → SentinelWebhookAlert.from_csv(). This routing MUST be in code, not just documentation.

**AuditEntry:** entry_id UUID, response_id UUID, user_id, function_id, prompt_template_version, system_prompt_hash, user_message, retrieval_query, retrieval_results list[Citation]=[], rerank_scores list[float]=[], llm_model, llm_input_tokens=0, llm_output_tokens=0, llm_cost_usd=0.0, raw_llm_response, parsed_response AgentResponse, validator_log dict={}, duration_ms=0, timestamp datetime.
```

---

## PROMPT 4 — RAG pipeline: embeddings + vector store

```
You are building the NARRUX aiTrate Co-Pilot. Read the CONTEXT from the build plan.

Your task: create the retrieval layer. NO pydantic_ai imports anywhere in this layer.

### File 1: narrux_agent/retrieval/embeddings.py

Voyage AI async wrapper. Model: voyage-3-large (1024 dimensions). 

Functions:
- embed_documents(texts: Sequence[str]) -> list[list[float]]: input_type="document", batched at 128 per Voyage limit, @retry 3 attempts exponential backoff
- embed_query(query: str) -> list[float]: input_type="query", single embedding, @retry
- embed_queries(queries: Sequence[str]) -> list[list[float]]: async gather of embed_query calls

Use voyageai.AsyncClient. Client cached with lru_cache(maxsize=1). API key from get_settings().voyage_api_key.

### File 2: narrux_agent/retrieval/vector_store.py

pgvector async operations using psycopg (v3) with AsyncConnectionPool.

Functions:
- init_pool() / close_pool(): called at startup/shutdown
- get_conn(): asynccontextmanager yielding AsyncConnection with dict_row
- upsert_document(doc: KBDocument): INSERT ON CONFLICT DO UPDATE
- mark_document_deprecated(doc_id: str): UPDATE deprecated=TRUE
- upsert_chunks(chunks: list[KBChunk]) -> int: INSERT ON CONFLICT, skip chunks with no embedding, return count
- delete_chunks_for_document(doc_id: str) -> int: DELETE WHERE doc_id=, return rowcount
- similarity_search(query_embedding, top_k, metadata_filter dict|None, exclude_deprecated=True) -> list[KBChunk]:
  Uses cosine distance operator <=> for ORDER BY. Builds WHERE clause dynamically from metadata_filter (JSONB ->> operator). Excludes deprecated docs. Returns KBChunk list with similarity in metadata["_similarity"].
- get_chunk_by_id(chunk_id: str) -> KBChunk|None
- get_stats() -> dict[str, int]: active_documents, total_chunks, deprecated_documents

Embedding upsert: cast as %(embedding)s::vector in the SQL.

### File 3: narrux_agent/retrieval/reranker.py

Voyage rerank-2 wrapper. 

@dataclass RankedChunk: chunk KBChunk, score float, rank int

Functions:
- rerank(query, chunks, top_n=None) -> list[RankedChunk]: calls voyageai AsyncClient rerank(), filters by min_rerank_score from settings. Log chunks dropped by threshold. This threshold IS the citations-or-silence gate — if nothing passes, agent must abstain.
- ranked_chunks_to_citations(ranked) -> list[Citation]: builds Citation objects from RankedChunk. Build citation_handle from chunk metadata: if module_id → "Alpha Handbook §D1 — CVD Filter", if pine_line → "file.pine:L437", if section → "doc §3.2", else fallback.
```

---

## PROMPT 5 — Ingestion pipeline

```
You are building the NARRUX aiTrate Co-Pilot. Read the CONTEXT from the build plan.

Your task: create narrux_agent/retrieval/ingestion.py — the KB document ingestion pipeline.
NO pydantic_ai imports.

CRITICAL FACT: All project documents are ZIP archives with .pdf extensions.
Magic bytes: PK\x03\x04. They contain N.txt files (one per page) and N.jpeg files.
The pipeline must detect this with _is_zip_archive() checking file magic bytes, NOT file extension.

@dataclass IngestionSource:
  path, doc_id, doc_version, title, scope DocumentScope, owner="NARRUX",
  strategy|None, volume|None, module_id|None, supersedes|None,
  module_markers dict[str,str]={} (optional pre-defined section markers)

Text extraction functions:
- extract_text_from_zip(path) -> list[tuple[int, str]]: open ZipFile, find *.txt files, parse page number from filename (int("N.txt".replace(".txt",""))), decode utf-8 errors=replace, call _strip_page_header_footer(), sort by page number
- _strip_page_header_footer(text): remove lines matching these patterns: "^Strictly Confidential", "^NARRUX.*(Strictly Confidential|Handbook|Specification)", "^Confidential — internal use only", "^Page \d+ of \d+$"
- extract_text_from_md(path), extract_text_from_txt(path), extract_text_from_docx(path)

@dataclass RawChunk: content str, metadata dict

Chunking functions:

chunk_by_module_boundaries(pages, source) -> list[RawChunk]:
  Join all page texts. Find module headers with regex: r"^([A-L]\d{1,2})\s*[·•]\s*(.+?)(?:\s*\[([ABC])\])?$" MULTILINE.
  If no matches found → fall back to chunk_sliding_window.
  For each match: extract module_id (group 1), module_name (group 2), param_class (group 3 or None).
  Build metadata: source_type="handbook", strategy, volume, module_id, module_name, doc_id, doc_version. If param_class: add param_class and regime_coupled=(class=="C").
  If section token count > chunk_size * 2: subdivide with chunk_sliding_window(section_text, source, extra_meta=meta).
  Log how many modules were found.

chunk_sliding_window(text, source, extra_meta=None) -> list[RawChunk]:
  Use tiktoken cl100k_base. chunk_size and overlap from settings.
  Encode → slice tokens → decode. Add chunk_index to metadata.

chunk_pages_with_context(pages, source) -> list[RawChunk]:
  One chunk per page if fits in chunk_size. Subdivide with sliding window if too long.
  Add page number to metadata.

make_chunk_id(doc_id, content, index) -> str:
  hashlib.sha256(f"{doc_id}::{index}::{content[:200]}".encode()).hexdigest()[:16]
  Return f"{doc_id}::{hash}"

async ingest_document(source, force_reingest=False) -> int:
  1. Detect file type with _is_zip_archive() first. If ZIP → extract_text_from_zip. Else by suffix.
  2. Choose chunking strategy: handbook (strategy+volume set) → chunk_by_module_boundaries. spec/process scope → chunk_pages_with_context. else → chunk_sliding_window.
  3. Register document via upsert_document.
  4. Delete old chunks via delete_chunks_for_document (always, to handle version upgrades).
  5. Embed with embed_documents.
  6. Build KBChunk objects with make_chunk_id.
  7. Upsert chunks. Return count.

async ingest_all_project_documents(kb_dir: Path) -> dict[str, int]:
  Calls _build_source_registry(kb_dir). For each source: if path doesn't exist, log warning and skip. Try ingest_document, catch exceptions, log error, set count=-1. Return {doc_id: count}.

_build_source_registry(kb_dir: Path) -> list[IngestionSource]:
  project_dir = kb_dir.parent / "project_docs"
  
  Register these documents exactly:
  
  doc_id="aitrate_agent_spec_v1_0", version="1.0", scope=GOVERNANCE, file="aiTrate_AI_Agent_Functional_Spec_v1_0.pdf"
  doc_id="alpha_handbook_v15_9_1_vol_ab", version="15.9.1", scope=STRATEGY, strategy="alpha", volume="AB", file="NARRUX_Alpha_v15_9_1_Handbook_Vol_AB.pdf"
  doc_id="alpha_handbook_v15_9_1_vol_c", version="15.9.1", scope=STRATEGY, strategy="alpha", volume="C", file="NARRUX_Alpha_v15_9_1_Handbook_Vol_C.pdf"
  doc_id="alpha_handbook_v15_9_1_vol_d", version="15.9.1", scope=STRATEGY, strategy="alpha", volume="D", file="NARRUX_Alpha_v15_9_1_Handbook_Vol_D.pdf"
  doc_id="alpha_handbook_v15_9_1_vol_ef", version="15.9.1", scope=STRATEGY, strategy="alpha", volume="EF", file="NARRUX_Alpha_v15_9_1_Handbook_Vol_EF.pdf"
  doc_id="alpha_handbook_v15_9_1_vol_hl", version="15.9.1", scope=STRATEGY, strategy="alpha", volume="HL", file="NARRUX_Alpha_v15_9_1_Handbook_Vol_HL.pdf"
  doc_id="sentinel_handbook_v1_9", version="1.9", scope=STRATEGY, strategy="sentinel", file="NARRUX_Sentinel_v1_9_Handbook.pdf"
  doc_id="backtest_analysis_approach_v1_0", version="1.0", scope=PROCESS, file="NARRUX_Backtest_Analysis_Approach_v1_0.pdf"
  doc_id="copilot_report_template_v1_0", version="1.0", scope=PROCESS, file="NARRUX_CoPilot_Report_Template_v1_0.pdf"
  NOTE: Do NOT register NARRUX_Alpha_v15_9_1_fulldepth_sample.pdf — its content is already in vol_ef.
  
  Then scan kb_content/filters/*.md → FILTER_GLOSSARY, kb_content/parameters/param_class_master.yaml → PARAMETER_MASTER, kb_content/playbook/*.md → PLAYBOOK.

_is_zip_archive(path) -> bool: open rb, read 4 bytes, check == b"PK\x03\x04"
_count_tokens(text) -> int: len(tiktoken cl100k_base encoder.encode(text))
```

---

## PROMPT 6 — Citation layer + validation layer

```
You are building the NARRUX aiTrate Co-Pilot. Read the CONTEXT from the build plan.

Your task: create the citation verification and validation layer. NO pydantic_ai imports.

### File 1: narrux_agent/retrieval/citation.py

async verify_citations(citations: list[Citation]) -> tuple[list[Citation], list[str]]:
  For each citation, call get_chunk_by_id(citation.chunk_id). If None: log warning "hallucinated citation", add to failed list. If doc_id mismatch: log warning "doc_id mismatch", add to failed. Return (verified, failed).

extract_citation_handles_from_text(text: str) -> list[str]:
  Regex: r"[\[\(]([^\]\)]+§[^\]\)]+|[^\]\)]+\.pine:L\d+)[\]\)]" — finds bracketed citation references.

citations_cover_claims(response_text: str, citations: list[Citation]) -> bool:
  Patterns that indicate substantive claims requiring citation:
  - r"\bF\d{1,2}\b" (filter references)
  - r"\bClass [ABC]\b"
  - r"\bTSI\b.{0,20}\b\d+\.?\d*\b"
  - r"\bdefault\b.{0,30}\b[\d.]+\b"
  - r"\b(blocks?|requires?|fires?|activates?)\b"
  - r"\b(Bollinger|Supertrend|MACD|RSI|CVD|ATR|ADX|MFI)\b"
  - r"\b(BE1|BE2|RT-BE|trailing stop|stop.loss)\b"
  
  Abstain patterns (always return True — silence is correct):
  - r"I don.t have", r"I cannot find", r"no citation", r"not in my knowledge base"
  
  Logic: if is_abstaining → True. If has_claims AND not citations → False. Else True.

### File 2: narrux_agent/validation/citation_enforcer.py

ABSTAIN_MESSAGE constant: "I don't have a grounded citation for that in my current knowledge base. I cannot answer without a verified source — providing an ungrounded answer would risk inaccuracy on a financial strategy question."

async enforce_citations(response: AgentResponse) -> AgentResponse:
  Step 1: If citations exist, call verify_citations. If any failed → call _make_abstain(response, reason="hallucinated_citations:{failed}")
  Step 2: Check citations_cover_claims. If fails → _make_abstain(response, reason="claims_without_citations")
  Step 3: If min citation score < 0.3 → downgrade confidence to LOW (not abstain)
  Return modified response.

_make_abstain(response, reason) -> AgentResponse:
  response.model_copy(update={content: ABSTAIN_MESSAGE, citations: [], confidence: ABSTAIN, validator_results: {**existing, citation_enforcer: {passed: False, reason: reason}}})

### File 3: narrux_agent/validation/output_validator.py

validate_response(response: AgentResponse) -> AgentResponse:
  Runs function-specific validators based on response.function_id.
  F-03 → validate_tsi_output
  F-04 → validate_recommendations
  F-02 → validate_backtest_response
  F-05 → validate_drift_response
  All → check_class_c_flagged
  If any validator fails AND confidence==HIGH → downgrade to MEDIUM. Return updated response.

validate_tsi_output(response) -> dict:
  If not computed_from_raw_csv and "±" not in content and "tolerance" not in content: issue "reconstructed_score_without_tolerance_note"
  Check grade implies correct leverage cap (S=3.0, A=2.0, B=1.5, C=1.0, D=0.0) against any cap mentioned in text.

validate_recommendations(response) -> dict:
  For each recommendation in structured_output["recommendations"]:
  - Class A proposal: log warning, add issue "class_a_proposal:{name}"
  - Class B with evidence_count < 3: issue "class_b_insufficient_evidence:{name}:{count}<3"
  - Class C without regime_label: issue "class_c_missing_regime_label:{name}"
  - within_bounds=False: issue "out_of_bounds:{name}"

validate_backtest_response(response) -> dict:
  Check content (lowercased) contains: "tsi"|"grade"|"score", "p&l"|"pnl"|"profit"|"return"|"net", "capital basis"|"initial capital"|"returns basis".
  If stop_loss_ratio in structured_output > 0.40 and "stop.loss ratio"|"sl ratio" not in content: issue "high_sl_ratio_not_flagged".

validate_drift_response(response) -> dict:
  Check "advisory"|"veto"|"override" in content.
  Check "stable"|"watch"|"breach" in content.

check_class_c_flagged(response) -> dict:
  Class C component names to check: cvd, cumulative volume delta, cmf, chaikin money flow, mfi, money flow index, volume exhaustion, spike exit, momentum override.
  If any mentioned AND "regime"|"class c"|"non-stationary"|"regime-coupled"|"volume-based" NOT in content: fail with issues.
```

---

## PROMPT 7 — Audit layer + orchestration

```
You are building the NARRUX aiTrate Co-Pilot. Read the CONTEXT from the build plan.

Your task: create the audit layer and orchestration layer.

### File 1: narrux_agent/audit/models.py

AuditEntry Pydantic model (already defined in tools/schemas.py — just import and re-export, or define a ProvenanceTrace model here for multi-step traces if needed).

### File 2: narrux_agent/audit/logger.py

Uses structlog. NO pydantic_ai imports.

async write_audit_entry(entry: AuditEntry) -> None:
  Insert into audit_log table. Uses get_conn() from vector_store.
  All UUID fields cast to str. JSON fields: model_dump_json() or json.dumps().
  Uses structlog.get_logger() for structured logging after write.
  CRITICAL: This function must raise on failure. The caller must not return a response if audit fails.
  Log fields: entry_id, response_id, function_id, user_id, duration_ms, confidence.

### File 3: narrux_agent/orchestration/llm_client.py

IMPORTANT: This is the ONLY file in the entire project that imports pydantic_ai.

@dataclass LLMRequest: system_prompt, user_message, context_chunks list[str], model|None, max_tokens|None, temperature=0.1

@dataclass LLMResponse: content, model, input_tokens, output_tokens, cost_usd, raw (full serialised for audit)

@runtime_checkable class LLMClient(Protocol):
  async complete(request: LLMRequest) -> LLMResponse
  def system_prompt_hash(prompt: str) -> str

compute_prompt_hash(prompt: str) -> str: sha256 hexdigest[:16]

_COST_PER_1K dict: claude-opus-4-7 input=0.015 output=0.075, claude-sonnet-4-6 input=0.003 output=0.015
estimate_cost(model, input_tokens, output_tokens) -> float

class DirectAnthropicAdapter:
  Uses anthropic.AsyncAnthropic (import inside __init__, not at module level).
  complete(): build context block with _build_context_block(), prepend to user message. Call messages.create with system=system_prompt. Return LLMResponse.
  system_prompt_hash(): compute_prompt_hash

class PydanticAIAdapter:
  Imports pydantic_ai inside __init__ ONLY. Import at module level is FORBIDDEN.
  complete(): create AnthropicModel(model_name), create Agent(model=model, system_prompt=system_prompt). Call agent.run(full_message). Extract usage (result.usage() if hasattr). Return LLMResponse.
  system_prompt_hash(): compute_prompt_hash

get_llm_client(adapter="pydantic_ai") -> LLMClient:
  "direct" → DirectAnthropicAdapter, else → PydanticAIAdapter

_build_context_block(chunks: list[str]) -> str:
  If empty: return "". Else: "<retrieved_context>\n[1] chunk1\n[2] chunk2\n</retrieved_context>"
```

---

## PROMPT 8 — All prompt files

```
You are building the NARRUX aiTrate Co-Pilot. Read the CONTEXT from the build plan.

Your task: create all prompt files in prompts/. These are markdown files, not Python.

### prompts/system_v1_0.md

This is the base system prompt. It must contain:

1. Role declaration: "You are the NARRUX aiTrate Co-Pilot. Co-pilot, not autopilot. Shadow mode — every recommendation advisory."

2. HARD-CODED non-negotiable rules (do not retrieve — always present):
   a. Citations or silence rule — verbatim abstain response if no grounded citation
   b. Class A/B/C governance — exact cadences, evidence requirements, regime requirements
   c. TSI grade → leverage cap table (S=3.0x, A=2.0x, B=1.5x, C=1.0x, D=0x)
   d. Cross-check score against P&L — TSI up with P&L flat = re-adjustment artefact
   e. Reconstruction tolerance — always state ±2–3 pts if not from raw CSV
   f. Versioned KB — never cite deprecated documents
   g. Authority roles — veto (entries), override (exits, earlier only), advisory (risk)

3. Output structure every response must follow:
   Answer → Detail → Cross-check → Caveats → Sources

4. What the agent never does: send orders, modify parameters directly, invent filter names, cite unretrieved documents, give confident wrong answers.

### prompts/f01_strategy_explainer.md

F-01 explains strategy components. Structure:
- Answer: one sentence what it does
- Position in flow: entry-gate/exit/filter/risk + handbook reference
- Logic: plain English + canonical condition in monospace
- Interactions: what it gates/is gated by; flag Class C interactions
- Stability note: class [A/B/C]; if Class C: "regime-coupled, non-stationary, strong backtest ≠ forward stability"
- Sources: handbook chapter IDs

Rules: if asked about non-existent filter (F31, F32): abstain explicitly. Address both Alpha and Sentinel if both relevant. Always state default (ON/OFF). Parameter values include class tag.

### prompts/f02_backtest_interpreter.md

F-02 interprets a backtest. HARD-CODE the full 8-step interpretation workflow:

Step 1: Capital basis normalisation — returns against order_size × 1.10, NOT TV initial_capital
Step 2: Execution flag check — calc_on_order_fills=false required; process_orders_on_close context-dependent
Step 3: TSI grade — compute or read; state reconstruction tolerance if not from raw CSV
Step 4: P&L cross-check — TSI up + P&L flat = re-adjustment artefact, not improvement
Step 5: Stop-loss ratio — >40% over last 20 trades = regime-stress emergency-brake
Step 6: Bar Magnifier drift — baseline ~0.19% per exit; attribute to specific exits
Step 7: Robustness — DSR vs raw Sharpe (high raw + low DSR = overfitting); worst-window
Step 8: Class-aware discount — Class C edges are regime-coupled

HARD-CODE the F-02 flag checklist (raise flag for each true):
☐ Returns vs TV initial capital not capital basis
☐ calc_on_order_fills=true
☐ process_orders_on_close=true without confirmed close-action live parity
☐ TSI rose while absolute P&L did not
☐ SL ratio >40% last 20 trades
☐ Result depends on 1–2 trades or Class C component
☐ High raw Sharpe with low DSR

Response structure: Headline (trustworthy/flagged) → Integrity flags → TSI+tier → Cross-check → Robustness → Class-coupling discount → Sources.

### prompts/f03_tsi_scorer.md

F-03 presents TSI engine output. Structure: Answer (score+tier+cap) → Components → Tolerance note → DQ triggers → Governance. Hard-code: never present reconstructed score as exact. Golden test reference: PLTR 93.99 ±0.02.

### prompts/f04_parameter_recommender.md

F-04 recommends parameter changes. Per-parameter table: name+class, current→proposed, rationale (NOT TSI alone), governance check, index note.
HARD-CODE governance rules: Class A never on single-backtest; Class B needs ≥3 backtests; Class C needs regime label.
HARD-CODE: never recommend within-tier TSI improvement that costs P&L without saying so. Never treat Class C as stationary.

### prompts/f05_drift_monitor.md

F-05 monitors drift. HARD-CODE: baseline ~0.19%/exit, breach threshold >0.40% rolling 20 trades, SL ratio >40% = emergency-brake.
Structure: Status (STABLE/WATCH/BREACH) → Signals → Attribution → Recommended action → Authority role.
MUST state: "This response is exercising advisory authority on risk."
```

---

## PROMPT 9 — CLI ingestion script + FastAPI skeleton

```
You are building the NARRUX aiTrate Co-Pilot. Read the CONTEXT from the build plan.

Your task: create the ingestion CLI and a minimal FastAPI skeleton.

### File 1: scripts/ingest.py

CLI script with argparse. Commands:
- --all: call ingest_all_project_documents(kb_dir=Path("kb_content"), project_docs via --project-docs arg default /mnt/project)
- --doc-id STR: ingest one document by doc_id; list available doc_ids if not found
- --stats: print get_stats() output
- --test-query STR: embed query → similarity_search(top_k=20) → rerank(top_n=5) → print results with scores and citation handles and first 200 chars of content
- --project-docs PATH: default /mnt/project

Startup: asyncio.run(main()). Always call await init_pool() before any DB ops. Always call await close_pool() in finally.

Note about project_docs: create symlink from kb_content/../project_docs → project_docs arg if it doesn't exist, so the source registry can find the files.

### File 2: narrux_agent/api/main.py

Minimal FastAPI app. Lifespan handler: on startup → init_pool() (pgvector), log "DB pool initialised". On shutdown → close_pool().

Routes:
- GET /health: return {"status": "ok", "kb_stats": await get_stats()}
- Include router from api/routes/health.py
- Include router from api/routes/chat.py (stub — returns 501 Not Implemented for now)

CORS: allow all origins in development.
Structlog configuration in startup.

### File 3: narrux_agent/api/routes/health.py

GET /health/kb-stats: return vector store stats
GET /health/ready: check DB connectivity (get_stats()), return 200 or 503

### File 4: narrux_agent/api/routes/chat.py

Stub only. POST /chat endpoint that returns:
{"error": "Chat endpoint not yet implemented", "status": 501}
with HTTP 501. Add TODO comment pointing to orchestration/agent.py which is built next.

### File 5: tests/conftest.py

pytest fixtures:
- settings fixture: returns get_settings()
- sample_trade_record: returns a valid TradeRecord with realistic values (strategy_id="alpha_v15_9_1", asset="TSLA", source="backtest", etc.)
- sample_backtest_summary: returns BacktestSummary with stop_loss_ratio=0.25 (below threshold)
- sample_tsi_result: returns TSIResult with grade=B, weighted_score=72.5, leverage_cap=1.5
```

---

## PROMPT 10 — Verification + test run

```
You are building the NARRUX aiTrate Co-Pilot. Read the CONTEXT from the build plan.

Your task: verify the project is correct and runnable locally.

### Step 1: Run syntax check on all Python files
For every .py file in the project: ast.parse() it. Print OK or ERR for each. Fail if any ERR.

### Step 2: Verify import linter contracts
The following import paths must NOT exist in the source:
- Any import of "pydantic_ai" in tools/, retrieval/, validation/, audit/
- Any import of "narrux_agent.orchestration" in tools/, retrieval/, validation/, audit/
- Any import of "pydantic_ai" in api/

Write a simple script that checks these using ast.walk() on each file's AST and reports violations.

### Step 3: Verify Rule 1 by inspection
Confirm orchestration/llm_client.py is the ONLY file with pydantic_ai imports at the module level. (Note: DirectAnthropicAdapter has "import anthropic" inside __init__ — that's correct, not a violation.)

### Step 4: Run unit tests (no external services required)
Create and run tests/unit/test_schemas.py:
- test_parse_webhook_alert_alpha: parse valid Alpha JSON payload → AlphaWebhookAlert
- test_parse_webhook_alert_sentinel: parse "NARRUX_SENTINEL,long,entry,qty=1.5" → SentinelWebhookAlert
- test_tsi_leverage_cap: for each grade S/A/B/C/D, leverage_cap_for_grade() returns correct value
- test_trade_record_roundtrip: create TradeRecord, dump to dict, reconstruct, assert equal
- test_agent_response_confidence: AgentResponse with ABSTAIN confidence and empty citations is valid
- test_recommendation_governance: Recommendation with parameter_class=C and no regime_label is constructable (governance enforcement is in validator, not model)

Create and run tests/unit/test_ingestion.py (no DB, no Voyage API needed):
- test_strip_page_header_footer: input text with NARRUX header → header stripped
- test_is_zip_archive_true: create a minimal ZIP in memory, check _is_zip_archive returns True
- test_is_zip_archive_false: write "Not a zip" to tmp file, check returns False
- test_chunk_sliding_window: chunk a 1000-token text, verify chunk count and overlap
- test_module_boundary_detection: text with "D1 · CVD Filter [C]" and "D2 · Something [A]" → 2 RawChunks with correct metadata
- test_make_chunk_id_deterministic: same inputs → same id always

### Step 5: Print project structure
Print the full file tree of narrux_agent/ and confirm all expected files exist.

### Step 6: Print startup instructions
Print the exact commands to:
1. Copy .env.example to .env and fill in VOYAGE_API_KEY and ANTHROPIC_API_KEY
2. Start infrastructure: docker-compose up postgres redis -d
3. Run ingestion: python scripts/ingest.py --all --project-docs /path/to/your/project/docs
4. Run test query: python scripts/ingest.py --test-query "what does the CVD filter do"
5. Start the API: uvicorn narrux_agent.api.main:app --reload
6. Check health: curl http://localhost:8000/health
```

---

# WHAT IS NOT IN SCOPE FOR LOCAL BUILD

Do not build these in this session:
- **orchestration/agent.py** — the main RAG loop (F-01 through F-05 wired end-to-end). Built in next session after retrieval quality is validated.
- **tools/tsi_engine.py** — wraps narrux_tsi_v2.py which you don't have yet (Frank's deliverable)
- **tools/backtest_parser.py** — requires sample xlsx files to validate against
- **tools/trade_db_reader.py** — requires unified trade DB schema from Team A
- **tools/leverage_engine.py** — wraps narrux_leverage.py (Frank's deliverable)
- **Frontend / React sidebar** — not in scope for this build
- **Auth / RBAC** — stub only; Anton's integration point
- **Eval harness questions** — Pillar A/B/C YAML files populated after retrieval quality tested
- **Proactive alerts** — v2 feature

---

# SUCCESS CRITERIA FOR LOCAL BUILD

After running all 10 prompts, you should be able to:

1. `docker-compose up postgres redis -d` → services healthy
2. `python scripts/ingest.py --all --project-docs /path/to/docs` → chunks ingested, no errors
3. `python scripts/ingest.py --stats` → shows active_documents > 0, total_chunks > 0
4. `python scripts/ingest.py --test-query "what does the CVD filter do"` → returns ranked results with citation handles like "Alpha Handbook §D1 — CVD Filter"
5. `python -m pytest tests/unit/ -v` → all tests pass (no external services needed)
6. `uvicorn narrux_agent.api.main:app --reload` → starts without error
7. `curl http://localhost:8000/health` → returns `{"status": "ok", ...}`

The vector store is working and retrieval quality can be evaluated before wiring the LLM on top.

---

# NEXT SESSION (after local validation)

Once retrieval quality is confirmed, the next session builds:
- `orchestration/agent.py` — the full RAG loop: retrieve → rerank → build prompt → LLM → validate → audit → respond
- F-01 wired end-to-end with eval harness
- First 20 Pillar A questions run against real retrieval output
- Retrieval recall@5 measured and tuned
