# aiTrate Co-Pilot

AI Agent for the NARRUX trading platform — strategy explanation, backtest interpretation, TSI grading, parameter recommendations, and drift detection.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI + React UI                     │
└─────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────────┐
│                   Agent Orchestrator                      │
│  (Pydantic AI — only framework-coupled code)            │
└─────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────────┐
│  Tools Layer          │  Retrieval Layer  │  Validation  │
│  (Pure Python)        │  (Pure Python)    │  (Pure Python)│
│  - Backtest Parser    │  - Voyage AI      │  - Citation   │
│  - TSI Engine         │  - pgvector       │  - Output     │
│  - Trade DB           │  - Reranker       │    Validator  │
│  - Knowledge Base     │  - Ingestion      │               │
└─────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────────┐
│              PostgreSQL + pgvector + Redis                │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Install Dependencies

```bash
cd aitrate-agent
pip install -e ".[dev]"
```

### 2. Set Up Environment

```bash
cp .env.example .env
# Edit .env with your API keys and database credentials
```

### 3. Set Up Database

```bash
# Create PostgreSQL database with pgvector extension
createdb aitrate
psql aitrate -c "CREATE EXTENSION vector;"

# Run migrations
alembic upgrade head
```

### 4. Ingest Knowledge Base

```bash
# Ingest NARRUX documentation
python scripts/ingest_kb.py --dir /path/to/narrux/docs --owner "Frank Zielkowski"
```

### 5. Start the Server

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### 6. Run Evaluation

```bash
python scripts/run_eval.py --all
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/chat` | POST | Chat with the agent (F-01) |
| `/api/v1/backtest/upload` | POST | Upload backtest xlsx (F-02) |
| `/api/v1/strategies/{id}/info` | GET | Get strategy info |
| `/health` | GET | Health check |

## Project Structure

```
aitrate-agent/
├── prompts/            # Versioned prompt templates
├── tools/              # Pure Python tools (NO framework imports)
├── retrieval/          # Embeddings, vector store, reranker
├── validation/         # Citation enforcement, output validation
├── audit/              # Append-only audit log
├── orchestration/      # Agent definition (ONLY framework-coupled code)
├── api/                # FastAPI endpoints
├── db/                 # SQLAlchemy models, migrations
├── eval/               # Evaluation harness
├── config/             # Pydantic Settings
├── tests/              # Test suite
└── scripts/            # Utility scripts
```

## Key Design Decisions

1. **Framework-agnostic core** — only `orchestration/` imports Pydantic AI
2. **Citations-or-silence** — every claim must cite a source
3. **Shadow mode** — read-only in v1, no live actions
4. **Append-only audit log** — every output logged for compliance

## v1 Functions

| Function | ID | Description |
|----------|-----|-------------|
| Strategy Explainer | F-01 | Answer questions about strategies with citations |
| Backtest Interpreter | F-02 | Parse xlsx, compute TSI, surface anomalies |
| TSI Auto-Grading | F-03 | Compute TSI v2.0 CA score |
| Parameter Recommender | F-04 | Recommend adjustments within Class A/B/C bounds |
| Drift Monitor | F-05 | Compare backtest vs live performance |

## Development

### Running Tests

```bash
pytest
```

### Code Quality

```bash
ruff check .
mypy .
```

### Import Rules (Enforced in CI)

```
tools/          ← may NOT import from pydantic_ai
retrieval/      ← may NOT import from pydantic_ai
validation/     ← may NOT import from pydantic_ai
audit/          ← may NOT import from pydantic_ai
orchestration/  ← the ONLY module allowed to import pydantic_ai
```

## License

Proprietary — NARRUX Group
