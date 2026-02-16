# MH Skills Coach — Claude Code Context

## What This Project Is
A **production-grade, safety-first mental health coaching web app**.
It helps users:
1. Practice coping skills via AI coaching (RAG-backed)
2. Discover nearby therapists
3. Draft and confirm booking emails to providers

This is NOT a therapy replacement. It is a coaching + navigation tool.

---

## Current Mission
**Transform this into a portfolio-defining, production-ready AI system.**

Priority order (do in this sequence):
1. Add LangSmith LLM call tracing
2. Add structured logging with request correlation IDs
3. Add rate limiting on `/chat` endpoint
4. Add retry logic + fallback responses
5. Build evaluation framework (safety tests, routing accuracy, LLM-as-judge)
6. Build metrics dashboard
7. Add CI/CD with GitHub Actions
8. Update README with evaluation results and architecture diagram

---

## Repository & Workflow
- **GitHub**: https://github.com/satish27072002/mh-skills-coach
- **Local path (Mac)**: `/Users/satish/Downloads/mh-skills-coach`
- **Deployment**: Azure VM — `git pull` + `docker compose -f docker-compose.prod.yml up -d --build`
- **Workflow**: Edit on Mac → push to GitHub → pull on Azure VM → docker compose up

---

## Tech Stack

### Backend (`services/backend/`)
- **Framework**: FastAPI (Python)
- **LLM**: OpenAI / Azure OpenAI — `gpt-4o-mini` for chat, `text-embedding-3-small` for embeddings
- **Agent Framework**: LangGraph (`langgraph==0.2.39`)
- **Database**: PostgreSQL + pgvector (for RAG embeddings)
- **Config**: `services/backend/app/config.py` (Pydantic settings loaded from `.env`)

### Frontend (`apps/frontend/`)
- **Framework**: Next.js (App Router) + TypeScript
- **Styling**: Tailwind CSS + shadcn/ui
- **Auth**: Google OAuth (session cookie: `mh_session`)

### Infrastructure
- **Containers**: Docker Compose (local) + docker-compose.prod.yml (Azure)
- **Reverse Proxy**: Caddy
- **Payment**: Stripe (test mode)
- **Email**: SMTP via MCP service

---

## Architecture

```
[User Browser]
      |
[Next.js Frontend: apps/frontend/]
      |
[POST /chat → FastAPI Backend: services/backend/app/main.py]
      |
[SafetyGate] ──crisis──> [Crisis response + 112/1177/90101 resources]
      |
[ChatRouter: agents/router.py]
      |
      ├──> [COACH] ──> RAG on pgvector ──> LLM (gpt-4o-mini)
      ├──> [THERAPIST_SEARCH] ──> TherapistSearchAgent ──> MCP therapist_search
      └──> [BOOKING_EMAIL] ──> BookingEmailAgent ──> MCP send_email
                |
[MCP Service: services/mcp/]
  ├── therapist_search.py — OpenStreetMap/Overpass API
  └── send_email.py       — SMTP email delivery
```

---

## Key Files

| File | Purpose |
|------|---------|
| `services/backend/app/main.py` | ALL API endpoints (939 lines) |
| `services/backend/app/safety.py` | Crisis/jailbreak/prescription detection |
| `services/backend/app/agents/router.py` | Routes to COACH/THERAPIST/BOOKING |
| `services/backend/app/agents/booking_agent.py` | Multi-turn booking flow |
| `services/backend/app/agents/therapist_agent.py` | Therapist search + location memory |
| `services/backend/app/config.py` | All settings (Pydantic, loaded from .env) |
| `services/backend/app/llm/provider.py` | LLM provider abstraction |
| `services/backend/app/agent_graph.py` | LangGraph orchestration |
| `services/backend/tests/` | 20+ existing pytest tests |
| `TODO.md` | Original backlog — rate limiting, logging, dashboard are P1/P2 |

---

## What Already Works ✅

- Multi-agent routing: SafetyGate → Router → Coach/Therapist/Booking
- Crisis detection with Swedish emergency numbers (112, 1177, 90101)
- Jailbreak detection (`JAILBREAK_PATTERNS` in `safety.py`)
- Prescription request blocking
- RAG-backed coaching responses (pgvector)
- Therapist search via OpenStreetMap/Overpass
- Multi-turn booking email with confirmation flow
- Google OAuth + session management
- Stripe payment integration (test mode)
- Azure VM deployment (live at francecentral.cloudapp.azure.com)
- 20+ pytest tests (crisis, booking, routing, auth, safety, webhooks)
- GitHub Actions CI (`ci.yml` exists but needs improvement)

---

## What Is MISSING ❌

### Week 1 — Observability
- **LangSmith tracing**: No LLM call tracing exists at all
  - Add to: `config.py`, `llm/provider.py`, and each agent
  - Needs new env vars: `LANGSMITH_API_KEY`, `LANGCHAIN_TRACING_V2`, `LANGCHAIN_PROJECT`
- **Structured logging**: Only basic `logging.getLogger` — no JSON, no correlation IDs
  - Create: `services/backend/app/monitoring/logger.py`
  - Log events: agent_routing, llm_call, safety_trigger, error
  - Add correlation ID (UUID) to every `/chat` request
- **Metrics dashboard**: Mentioned in TODO.md P2 — not built
  - Create: `services/backend/app/monitoring/dashboard.py` (Streamlit)

### Week 2 — Security & Resilience
- **Rate limiting**: Explicitly in TODO.md P1 — not implemented
  - Create: `services/backend/app/security/rate_limiter.py`
  - Apply to: `/chat` endpoint (10 req/min per session/IP)
- **Retry logic**: No exponential backoff on LLM calls
  - Add `tenacity` retries to `llm/provider.py`
  - 3 retries, exponential backoff (2s → 4s → 8s)
- **Fallback responses**: No graceful degradation when OpenAI API is down
- **Timeout protection**: No timeout on LLM calls (can hang forever)

### Week 3 — Evaluation Framework
- **Expanded safety tests**: `test_crisis_guardrail.py` exists but needs 20+ scenarios
- **LLM-as-judge evaluation**: No response quality scoring exists
  - Create: `services/backend/evals/response_quality_eval.py`
- **Routing accuracy tests**: No automated accuracy measurement
  - Create: `services/backend/tests/test_routing_accuracy.py` (40+ cases, target >90%)
- **Evaluation report**: No published metrics anywhere
  - Create: `EVALUATION_REPORT.md`

### Week 4 — Polish
- **README**: No evaluation results, no architecture diagram, no demo link
- **CI/CD**: `ci.yml` exists but doesn't gate on evaluation thresholds
- **Demo video**: Nothing recorded

---

## Environment Variables

### Already in `.env`:
```
LLM_PROVIDER=openai
EMBED_PROVIDER=openai
OPENAI_API_KEY=<azure-openai-key>
DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/mh
MCP_BASE_URL=http://mcp:7000
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
STRIPE_SECRET_KEY=...
SMTP_HOST=...
```

### ADD These to `.env` (Week 1 — do this first):
```
LANGSMITH_API_KEY=<your-langsmith-api-key>
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=mh-skills-coach
```

### ADD These to `config.py` (Week 1):
```python
langsmith_api_key: str | None = None
langchain_tracing_v2: str = "false"
langchain_project: str = "mh-skills-coach"
```

---

## Running Locally

```bash
cd /Users/satish/Downloads/mh-skills-coach
docker compose up -d --build
curl http://localhost:8000/health
curl http://localhost:8000/status
```

## Running Tests

```bash
# All tests
docker compose exec backend pytest -v

# Safety tests only
docker compose exec backend pytest services/backend/tests/test_crisis_guardrail.py -v

# With coverage
docker compose exec backend pytest --cov=app --cov-report=term-missing
```

## Deploying to Azure VM

```bash
git add . && git commit -m "your message" && git push origin main
ssh <username>@<vm-ip>
cd mh-skills-coach && git pull origin main
docker compose -f docker-compose.prod.yml up -d --build
```

---

## Safety Rules — NEVER Violate

1. **Never diagnose**: App must never say a user has a mental illness
2. **Always escalate crisis**: Any `CRISIS_KEYWORDS` match → return crisis response with 112/1177/90101
3. **Never prescribe**: Any `PRESCRIPTION_KEYWORDS` match → blocked
4. **Never act as therapist**: Always refer to professionals
5. **100% safety test pass rate is non-negotiable**

---

## Code Style Rules

- Use Pydantic models for all request/response schemas (see `schemas.py`)
- All new settings → `config.py` as `Settings` fields (never hardcode)
- Tests use `pytest` + `TestClient` + `monkeypatch` (follow existing patterns)
- Type hints required on all new functions
- Never commit secrets — use `settings.*` from `config.py`
- Follow existing file structure — don't reorganise unless asked

---

## Missing Test Files to Create

| File | What to test |
|------|-------------|
| `tests/test_rate_limiting.py` | Rate limit enforcement on /chat |
| `tests/test_input_validation.py` | Prompt injection detection |
| `tests/test_retry_logic.py` | Resilience under API failure |
| `tests/test_routing_accuracy.py` | 40+ routing cases, >90% accuracy |
| `evals/test_response_quality.py` | LLM-as-judge scoring |

---

## Week-by-Week Goals

### Week 1 (START HERE)
1. Add `LANGSMITH_API_KEY`, `LANGCHAIN_TRACING_V2`, `LANGCHAIN_PROJECT` to `config.py`
2. Add LangSmith env vars to `.env` and `.env.example`
3. Wrap LLM calls in `llm/provider.py` with `@traceable` decorator
4. Create `services/backend/app/monitoring/logger.py` — structured JSON logger
5. Add correlation ID + structured logging to `/chat` endpoint in `main.py`
6. Create `services/backend/app/monitoring/dashboard.py` — Streamlit metrics

### Week 2
1. Create `services/backend/app/security/rate_limiter.py`
2. Apply rate limiter to `/chat` in `main.py`
3. Add `tenacity` to `requirements.txt` and retry logic to `llm/provider.py`
4. Add 30s timeout to all LLM calls
5. Add fallback responses in `main.py` for API failures

### Week 3
1. Expand `tests/test_crisis_guardrail.py` with 20+ scenarios
2. Create `evals/response_quality_eval.py` with LLM-as-judge
3. Create `tests/test_routing_accuracy.py` with 40+ cases
4. Run evaluations and write `EVALUATION_REPORT.md`

### Week 4
1. Rewrite `README.md` with metrics, architecture diagram, demo link
2. Improve `.github/workflows/ci.yml` to gate on test pass rates
3. Record 2-3 min demo video
4. Final deploy + verify on Azure VM
