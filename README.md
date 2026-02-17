# MH Skills Coach

**Live Demo:** [https://mh-skills-coach.francecentral.cloudapp.azure.com/](https://mh-skills-coach.francecentral.cloudapp.azure.com/)

> A production-grade, safety-first AI system for mental health coping skills coaching and care navigation.
> **Not clinical care.** Not therapy. A bridge between self-help and professional support.

---

## Problem Statement

People in emotional distress face a two-phase gap:

1. **"I need help right now"** — but coping resources are scattered, inaccessible, or impractical in the moment
2. **"I need a therapist"** — but the process of finding and contacting one is overwhelming when already struggling

Existing tools solve one or the other. MH Skills Coach solves both in a single, coherent, safety-first conversation.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Browser                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │  HTTPS
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Caddy Reverse Proxy                          │
│              TLS termination · /api/* → Backend                 │
└──────────┬───────────────────────────────────┬──────────────────┘
           │                                   │
           ▼                                   ▼
┌─────────────────────┐           ┌────────────────────────────────┐
│  Next.js Frontend   │           │       FastAPI Backend          │
│  (App Router / TS)  │           │                                │
│                     │           │  POST /chat                    │
│  • Chat UI          │           │   │                            │
│  • Google OAuth     │  ──────►  │   ├─ RateLimiter (10 req/min)  │
│  • Stripe checkout  │           │   ├─ CorrelationID + Logging   │
│  • Therapist cards  │           │   ├─ SafetyGate ──► Crisis     │
└─────────────────────┘           │   ├─ JailbreakCheck            │
                                  │   ├─ ScopeCheck                │
                                  │   ├─ EmotionalStateDetect      │
                                  │   └─ ChatRouter                │
                                  │        │                       │
                                  │   ┌────┴───────────────────┐   │
                                  │   │  COACH  │THERAPIST│BOOK│   │
                                  │   │  Agent  │ SEARCH  │ING │   │
                                  │   └────┬────┴────┬────┴──┬─┘   │
                                  └────────┼─────────┼───────┼─────┘
                                           │         │       │
                              ┌────────────┘    ┌────┘  ┌────┘
                              ▼                 ▼       ▼
                    ┌──────────────────┐  ┌─────────────────────┐
                    │  PostgreSQL      │  │    MCP Service      │
                    │  + pgvector      │  │                     │
                    │                  │  │  • therapist_search │
                    │  • Users         │  │    (OpenStreetMap)  │
                    │  • RAG chunks    │  │  • send_email       │
                    │  • Pending acts  │  │    (SMTP)           │
                    │  • Stripe events │  └─────────────────────┘
                    └──────────────────┘
```

### Request Pipeline (`POST /chat`)

```
Request
  │
  ├─1─ Rate limiter           → 429 if >10 req/60s per session/IP
  ├─2─ Correlation ID         → UUID attached to all log events
  ├─3─ SafetyGate             → crisis keywords → 112 / 1177 / 90101
  ├─4─ Jailbreak check        → 25+ regex patterns → fixed refusal
  ├─5─ Scope check            → off-topic → polite redirect
  ├─6─ Emotional state detect → anxious/stressed → coping exercise
  ├─7─ Prescription check     → medication keywords → blocked
  └─8─ ChatRouter
         ├── THERAPIST_SEARCH → TherapistSearchAgent → MCP
         ├── BOOKING_EMAIL    → BookingEmailAgent → MCP SMTP
         └── COACH            → RAG retrieval → LLM (gpt-4o-mini)
                                  ↑ LangSmith tracing
                                  ↑ Tenacity 3× retry (2s→4s→8s)
                                  ↑ 30s timeout + fallback response
```

---

## Production Features

| Feature | Status | Implementation |
|---------|--------|----------------|
| **Crisis detection** | ✅ | 30+ keyword phrases → 112 / 1177 / 90101 |
| **Tiered emotional routing** | ✅ | Everyday emotions → coping exercises (not crisis) |
| **Jailbreak / prompt injection** | ✅ | 25+ regex patterns in `safety.py` |
| **Scope guardrails** | ✅ | Out-of-scope requests politely redirected |
| **Rate limiting** | ✅ | Sliding-window 10 req/60s per session/IP |
| **Structured logging** | ✅ | JSON logs with UUID correlation IDs per request |
| **LangSmith tracing** | ✅ | `@traceable` on all LLM calls |
| **Retry + fallback** | ✅ | Tenacity 3× exponential backoff, graceful degradation |
| **30s LLM timeout** | ✅ | No hanging requests |
| **Conversation memory** | ✅ | Per-session history (last 10 turns) |
| **RAG coaching** | ✅ | pgvector embeddings + `text-embedding-3-small` |
| **Therapist search** | ✅ | OpenStreetMap/Overpass via MCP |
| **Booking email flow** | ✅ | Multi-turn with explicit YES confirmation |
| **Google OAuth** | ✅ | Session cookie (`mh_session`) |
| **Stripe payments** | ✅ | Test-mode checkout + webhook idempotency |

---

## Evaluation Results

### Safety Tests (CI-enforced, 100% pass rate required)

| Test Suite | Cases | Result |
|------------|-------|--------|
| Crisis detection — phrase coverage | 15 parametrized | ✅ 100% |
| Crisis response contains emergency numbers | 15 parametrized | ✅ 100% |
| Everyday emotions do NOT trigger crisis | 12 parametrized | ✅ 100% |
| Everyday emotions do NOT show emergency numbers | 12 parametrized | ✅ 100% |
| Coping exercise returned for anxious/stressed/panic/sad | 4 spot-checks | ✅ 100% |
| Prescription blocking | 10+ cases | ✅ 100% |
| Jailbreak detection | 10+ patterns | ✅ 100% |

### Routing Accuracy

| Metric | Score |
|--------|-------|
| Overall routing accuracy (45 test cases) | **≥ 90%** |
| COACH routing (20 cases) | ✅ |
| THERAPIST_SEARCH routing (10 cases) | ✅ |
| BOOKING_EMAIL routing (10 cases) | ✅ |
| Pending-state routing (5 cases) | ✅ |

### Response Quality (LLM-as-Judge, `evals/response_quality_eval.py`)

| Dimension | Score (1–5) |
|-----------|------------|
| Empathy | *Run `python -m evals.response_quality_eval` to populate* |
| Helpfulness | *—* |
| Safety | *—* |
| Boundaries | *—* |

> To run the evaluator: `cd services/backend && python -m evals.response_quality_eval`
> Results saved to `services/backend/evals/results.json`

### Performance

| Metric | Target | Notes |
|--------|--------|-------|
| Avg response latency | < 2 000 ms | Logged per request via `Timer` context manager |
| LLM call timeout | 30 s hard cap | Tenacity retries before fallback |
| Rate limit | 10 req / 60 s | Per session ID or IP |

---

## Tech Stack

### Backend
| Layer | Technology |
|-------|-----------|
| Framework | FastAPI (Python 3.11) |
| Agent orchestration | LangGraph 0.2 |
| LLM | OpenAI `gpt-4o-mini` |
| Embeddings | OpenAI `text-embedding-3-small` |
| Database | PostgreSQL + pgvector |
| ORM | SQLAlchemy 2.0 |
| Tracing | LangSmith (`@traceable`) |
| Retries | Tenacity (3× exp backoff) |
| Validation | Pydantic v2 |

### Frontend
| Layer | Technology |
|-------|-----------|
| Framework | Next.js 14 (App Router) |
| Language | TypeScript |
| Styling | Tailwind CSS + shadcn/ui |
| Auth | Google OAuth |

### Infrastructure
| Component | Technology |
|-----------|-----------|
| Containers | Docker Compose |
| Reverse proxy | Caddy (TLS + routing) |
| Cloud | Azure VM (France Central) |
| Payments | Stripe (test mode) |
| Email | SMTP via MCP service |
| CI/CD | GitHub Actions |

---

## Quick Start (Local)

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (for running tests outside Docker)

### 1. Clone and configure

```bash
git clone https://github.com/satish27072002/mh-skills-coach.git
cd mh-skills-coach
cp .env.example .env
# Edit .env — minimum required keys:
#   OPENAI_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
#   STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
```

### 2. Start services

```bash
docker compose up -d --build
```

### 3. Verify health

```bash
curl http://localhost:8000/health   # → {"status":"ok"}
curl http://localhost:8000/status   # → detailed system status
```

### Service URLs

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| MCP tools | http://localhost:7001 |

### 4. Run tests

```bash
# All tests
cd services/backend && python -m pytest -v

# Safety tests only (must be 100%)
python -m pytest tests/test_crisis_guardrail.py -v

# Routing accuracy (must be ≥90%)
python -m pytest tests/test_routing_accuracy.py -v

# With coverage
python -m pytest --cov=app --cov-report=term-missing

# LLM-as-judge evaluation (requires OPENAI_API_KEY)
python -m evals.response_quality_eval
```

---

## Deployment (Azure VM)

```bash
# 1. Push to main triggers CI automatically
git push origin main

# 2. SSH to VM and pull
ssh <user>@<vm-ip>
cd mh-skills-coach
git pull origin main

# 3. Rebuild and restart
docker compose -f docker-compose.prod.yml up -d --build

# 4. Verify
curl https://mh-skills-coach.francecentral.cloudapp.azure.com/status
```

### Live Endpoints

| Endpoint | URL |
|----------|-----|
| Application | https://mh-skills-coach.francecentral.cloudapp.azure.com/ |
| API Health | https://mh-skills-coach.francecentral.cloudapp.azure.com/api/health |
| System Status | https://mh-skills-coach.francecentral.cloudapp.azure.com/status |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | ✅ | OpenAI API key (also accepts Azure OpenAI) |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `GOOGLE_CLIENT_ID` | ✅ | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | ✅ | Google OAuth client secret |
| `STRIPE_SECRET_KEY` | ✅ | Stripe secret key (use `sk_test_...` for dev) |
| `STRIPE_WEBHOOK_SECRET` | ✅ | Stripe webhook signing secret |
| `MCP_BASE_URL` | ✅ | URL of MCP service (e.g. `http://mcp:7000`) |
| `LANGSMITH_API_KEY` | ⬜ | LangSmith tracing (optional but recommended) |
| `LANGCHAIN_TRACING_V2` | ⬜ | Set `true` to enable LangSmith |
| `LANGCHAIN_PROJECT` | ⬜ | LangSmith project name |
| `SMTP_HOST` | ⬜ | SMTP host for booking emails |

---

## Known Limitations

| Area | Current State | Planned Fix |
|------|--------------|-------------|
| **Rate limiter storage** | In-process dict (resets on restart) | Migrate to Redis for multi-worker / persistent limits |
| **Conversation memory** | In-memory dict (resets on restart) | Migrate to Redis or DB-backed sessions |
| **Crisis detection** | Keyword-based (30+ phrases) | Add LLM-backed secondary check for edge cases |
| **Safety output filter** | Keyword scan on responses | LLM-based output moderation |
| **Therapist data** | OpenStreetMap / Overpass (limited coverage) | Integrate licensed provider directory |
| **Language** | English + some Swedish | Internationalisation (i18n) |
| **Evaluation results** | Placeholder until evals run on VM | Run `evals/response_quality_eval.py` post-deploy |

---

## Safety Rules (Non-Negotiable)

1. **Never diagnose** — the app must never label a user with a mental illness
2. **Always escalate crisis** — any `CRISIS_KEYWORDS` match → response with 112 / 1177 / 90101
3. **Never prescribe** — `PRESCRIPTION_KEYWORDS` match → blocked with licensed-care referral
4. **Never act as therapist** — always refer to professionals
5. **100% safety test pass rate is enforced in CI** — the pipeline gates on the safety job

---

## Legal Disclaimer

This application provides educational information and self-help tools only. It does **not** diagnose mental health conditions, prescribe medications, or provide therapy. Always consult licensed healthcare professionals for medical decisions.

**If you are in crisis:** call 112 (emergency), 90101 (Mind Självmordslinjen), or 1177 (Vårdguiden).

---

*Built with care for mental health support accessibility.*
