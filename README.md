# MH Skills Coach

**Live Application:** [https://mh-skills-coach.francecentral.cloudapp.azure.com/](https://mh-skills-coach.francecentral.cloudapp.azure.com/)

A safety-first mental health support application that provides evidence-based coping skills coaching and streamlines the path to professional care. **This is not clinical care, therapy, or a medical service** — it's a navigation and skills-training tool.

---

## 🎯 Problem Statement

People experiencing mental health challenges often face a **two-phase need**:

1. **Immediate support**: Actionable coping skills for emotional regulation in the moment
2. **Access to care**: A fast, low-friction path to finding and contacting licensed providers

Traditional solutions address these separately, creating gaps in the support journey. Users often struggle to navigate from "I need help now" to "I'm connected with a professional."

## 💡 What This App Solves

MH Skills Coach **reduces friction in the mental health support journey** by combining both phases in a single, coherent workflow:

- **Immediate relief**: Users get evidence-based coping techniques (breathing exercises, grounding, cognitive reframing) instantly through conversational AI
- **Streamlined care access**: Integrated therapist search and booking email assistance removes barriers to reaching out to providers
- **Safety-first design**: Crisis detection with immediate escalation to emergency resources ensures users in danger get appropriate help

The app acts as a **bridge between self-help and professional care**, meeting users where they are and guiding them forward.

---

## ✨ Key Features

### Multi-Agent Architecture
- **SafetyGate**: Crisis detection and emergency resource routing (runs before all other agents)
- **Router**: Intelligent intent classification directing to appropriate specialized agents
- **TherapistSearchAgent**: Provider discovery with location-based search and premium gating
- **BookingEmailAgent**: Multi-turn conversation state management for appointment scheduling
- **Coach Agent**: RAG-enabled skills coaching with contextual guidance

### Core Capabilities
- **RAG-enabled coaching**: Retrieval-augmented generation pulls from evidence-based mental health resources (pgvector embeddings)
- **Therapist search**: Location-based provider discovery via MCP tool integration
- **Booking email assistant**: 
  - Collects required information (therapist email, date/time)
  - Generates professional booking email
  - Requires **explicit YES confirmation** before sending
  - Supports multi-turn pending state (15-minute expiry)
- **Safety guardrails**: 
  - No diagnosis or prescriptions
  - Crisis keyword detection
  - Prescription request blocking with referral to licensed care
  - Sweden-specific emergency resources (112, 1177 Vårdguiden, Mind Självmordslinjen)
- **Premium gating**: Stripe test-mode checkout and webhook handling for therapist search feature
- **Authentication**: Google OAuth integration

---

## 🛠 Tech Stack

### Frontend
- **Next.js 14** (App Router)
- **TypeScript**
- **Tailwind CSS** + Radix UI components
- **React 18** with Server Components

### Backend
- **FastAPI** (Python)
- **LangGraph** for multi-agent orchestration
- **SQLAlchemy** ORM
- **Pydantic** for validation

### Data & Storage
- **PostgreSQL** with **pgvector** extension
- Vector embeddings for RAG retrieval
- User data, pending actions, Stripe event idempotency

### AI & Tools
- **LLM Providers**: OpenAI or Mock (configurable)
- **Embedding Providers**: OpenAI
- **MCP (Model Context Protocol)**: HTTP-based tool service
  - `therapist_search` tool
  - `send_email` tool (SMTP)

### Infrastructure
- **Docker Compose** for local orchestration
- **Caddy** as reverse proxy (handles HTTPS, routing)
- **Azure VM** for production deployment

---

## 🏗 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         CLIENT                              │
│                      (Web Browser)                          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    CADDY PROXY                              │
│              (Reverse Proxy + TLS)                          │
│   Routes:                                                   │
│   • / → Frontend (Next.js)                                  │
│   • /api/* → Backend (FastAPI)                              │
└────────────┬────────────────────────────┬───────────────────┘
             │                            │
             ▼                            ▼
┌─────────────────────┐      ┌──────────────────────────────┐
│   FRONTEND          │      │        BACKEND               │
│   (Next.js 14)      │      │       (FastAPI)              │
│                     │      │                              │
│ • UI/UX             │      │ • Multi-agent routing        │
│ • Auth pages        │      │ • Safety enforcement         │
│ • Payment flow      │      │ • LLM orchestration          │
│ • Chat client       │      │ • RAG retrieval              │
└─────────────────────┘      │ • OAuth/Stripe handling      │
                              └──────┬───────────┬───────────┘
                                     │           │
                    ┌────────────────┘           └────────────┐
                    ▼                                         ▼
        ┌────────────────────┐                   ┌──────────────────┐
        │   POSTGRES         │                   │   MCP SERVICE    │
        │   (+ pgvector)     │                   │   (Tool Layer)   │
        │                    │                   │                  │
        │ • Users            │                   │ • therapist_search│
        │ • Pending actions  │                   │ • send_email      │
        │ • Embeddings       │                   └──────────────────┘
        │ • Stripe events    │
        └────────────────────┘
```

### Request Flow

1. **User** sends message via frontend
2. **Caddy** routes to backend at `/api/chat`
3. **Backend** runs multi-agent pipeline:
   - **SafetyGate** → Crisis check (can short-circuit)
   - **Prescription check** → Blocks medical advice requests
   - **Router** → Classifies intent (THERAPIST_SEARCH | BOOKING_EMAIL | COACH)
   - **Specialized agent** executes based on route
4. **Agent** may call:
   - **Postgres** for RAG context retrieval
   - **MCP service** for external tools
   - **LLM provider** for response generation
5. **Response** returned to frontend for display

---

## 🤖 Multi-Agent Design

### Agent Responsibilities

| Agent | Trigger | Function |
|-------|---------|----------|
| **SafetyGate** | All messages | Detects crisis keywords (suicide, self-harm), returns emergency resources |
| **Prescription Blocker** | Medical keywords | Blocks diagnosis/medication requests, redirects to licensed care |
| **Router** | Non-crisis messages | Classifies intent using rules + LLM fallback |
| **TherapistSearchAgent** | "find therapist", location queries | Parses location/radius/specialty, calls MCP tool, returns provider list |
| **BookingEmailAgent** | "book", "send email", confirmation replies | Manages pending state, collects missing fields, drafts email, handles YES/NO |
| **Coach** | Default/fallback | RAG-enabled coping skills coaching (breathing, grounding, CBT techniques) |

### Routing Policy

```python
if is_crisis(message):
    return SafetyGate()  # Short-circuit with emergency resources

if is_prescription_request(message):
    return RefusalMessage()  # Short-circuit with referral

route = Router.classify(message)

if route == "THERAPIST_SEARCH":
    return TherapistSearchAgent()
elif route == "BOOKING_EMAIL":
    return BookingEmailAgent()
else:
    return CoachAgent()  # RAG + LLM
```

---

## 📡 API Endpoints

### Backend Routes (FastAPI)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/chat` | Main chat endpoint, routes to multi-agent pipeline |
| `POST` | `/therapists/search` | Direct therapist search (premium required) |
| `POST` | `/payments/create-checkout-session` | Create Stripe checkout session for premium |
| `POST` | `/payments/webhook` | Stripe webhook handler for payment events |
| `GET` | `/health` | Health check (returns `{"status": "ok"}`) |
| `GET` | `/status` | Detailed system status (LLM, DB, MCP connectivity) |
| `GET` | `/auth/google/start` | Initiate Google OAuth flow |
| `GET` | `/auth/google/callback` | OAuth callback handler |
| `GET` | `/me` | Get current user info |
| `POST` | `/logout` | Clear session cookie |

### Frontend API Routes (Next.js)

All frontend API calls are proxied through `/api/*` which routes to backend.

Example: `POST /api/chat` → Backend `POST /chat`

---

## 📊 System Flows

### Flow 1: Chat + RAG Coaching

```
┌─────────┐
│  User   │ "I'm feeling anxious"
└────┬────┘
     │
     ▼
┌────────────────┐
│  POST /chat    │
└────┬───────────┘
     │
     ▼
┌──────────────────┐
│  SafetyGate      │ ──┐ (if crisis detected)
└────┬─────────────┘   │
     │                 ▼
     │            ┌─────────────────────┐
     │            │ Crisis Response     │
     │            │ + Emergency Hotlines│
     │            └─────────────────────┘
     │ (no crisis)
     ▼
┌──────────────────┐
│  Router          │ → Route: COACH
└────┬─────────────┘
     │
     ▼
┌──────────────────┐
│  Coach Agent     │
└────┬─────────────┘
     │
     ├─→ Query pgvector for similar chunks
     │   (RAG context retrieval)
     │
     └─→ Call LLM with system prompt + context
         │
         ▼
    ┌─────────────────────────────────┐
    │ Response: "Try box breathing:   │
    │ in for 4, hold 4, out 4, hold 4"│
    └─────────────────────────────────┘
```

### Flow 2: Therapist Search + Booking

```
┌─────────┐
│  User   │ "find therapist near Stockholm"
└────┬────┘
     │
     ▼
┌────────────────┐
│  POST /chat    │
└────┬───────────┘
     │
     ▼
┌──────────────────┐
│  SafetyGate      │ (pass)
└────┬─────────────┘
     │
     ▼
┌──────────────────┐
│  Router          │ → Route: THERAPIST_SEARCH
└────┬─────────────┘
     │
     ▼
┌─────────────────────────┐
│ TherapistSearchAgent    │
└────┬────────────────────┘
     │
     ├─→ Premium check (in prod)
     ├─→ Parse location: "Stockholm"
     ├─→ Extract radius: 25km (default)
     │
     └─→ Call MCP tool: POST /tools/therapist_search
         │
         ▼
    ┌─────────────────────────────────┐
    │ Response: [                     │
    │   {name: "Dr. X", address: ...},│
    │   {name: "Clinic Y", ...}       │
    │ ]                               │
    └─────────────────────────────────┘
         │
         ▼
    User selects provider
         │
         ▼
┌─────────┐
│  User   │ "book appointment with dr.x@clinic.se tomorrow at 3pm"
└────┬────┘
     │
     ▼
┌────────────────┐
│  POST /chat    │
└────┬───────────┘
     │
     ▼
┌──────────────────┐
│  Router          │ → Route: BOOKING_EMAIL
└────┬─────────────┘
     │
     ▼
┌─────────────────────────┐
│ BookingEmailAgent       │
└────┬────────────────────┘
     │
     ├─→ Parse email: dr.x@clinic.se
     ├─→ Parse datetime: 2026-02-15 15:00
     ├─→ Generate email draft
     │
     └─→ Save to DB (pending_actions)
         │
         ▼
    ┌─────────────────────────────────┐
    │ Response: Booking proposal      │
    │ requires_confirmation: true     │
    │ "Reply YES to send or NO"       │
    └─────────────────────────────────┘
         │
         ▼
    User: "YES"
         │
         ▼
┌─────────────────────────┐
│ BookingEmailAgent       │
└────┬────────────────────┘
     │
     └─→ Call MCP tool: POST /tools/send_email
         │
         ▼
    Email sent via SMTP
         │
         ▼
    Clear pending_actions row
```

---

## 🛡 Safety & Compliance

### Core Boundaries

This application **strictly prohibits**:
- ❌ **Diagnosis**: No diagnostic interpretations or condition labeling
- ❌ **Prescriptions**: No medication recommendations or dosing advice
- ❌ **Clinical treatment**: No therapy, counseling, or clinical interventions

### What We Provide Instead

✅ **Evidence-based coping skills**: Breathing exercises, grounding techniques, cognitive reframing  
✅ **Provider navigation**: Help users find licensed therapists and clinics  
✅ **Administrative support**: Draft booking emails professionally  
✅ **Crisis resources**: Immediate escalation with emergency contacts  

### Crisis Handling

When crisis keywords are detected (`suicide`, `self-harm`, `kill myself`, etc.):

1. **Immediate response** with validation and empathy
2. **Emergency services** (Sweden: 112)
3. **Crisis hotlines**:
   - Mind Självmordslinjen: 90101
   - 1177 Vårdguiden
4. **Optional therapist search** if location available and user has premium
5. **No normal coaching flow** until crisis is addressed

### Compliance Testing

Safety behavior verified via:
- `services/backend/tests/test_crisis_guardrail.py`
- `services/backend/tests/test_safety.py`
- `services/backend/tests/test_chat_prescription.py`

---

## 🚀 Local Development

### Prerequisites

- Docker & Docker Compose
- (Optional) Node.js 18+ for local frontend dev
- (Optional) Python 3.11+ for local backend dev

### Quick Start

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd mh-skills-coach

# 2. Copy environment file
cp .env.example .env

# 3. Configure .env (see Secrets section below)

# 4. Start all services
docker compose up -d --build

# 5. Ingest RAG data (optional, for coaching responses)
docker compose exec backend python -m app.ingest --path /data/papers --reset

# 6. Verify health
curl http://localhost:8000/health    # Backend
curl http://localhost:7001/health    # MCP service
curl http://localhost:3000           # Frontend
```

### Service URLs (Local)

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| Backend Status | http://localhost:8000/status |
| MCP Tools | http://localhost:7001 |
| Postgres | localhost:5432 |

### Health Checks

```bash
# Backend
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/status

# MCP
curl -fsS http://localhost:7001/health

# Check logs
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f mcp
```

---

## 🌐 Production Deployment (Azure VM)

### Live URLs

| Resource | URL |
|----------|-----|
| **Application** | [https://mh-skills-coach.francecentral.cloudapp.azure.com/](https://mh-skills-coach.francecentral.cloudapp.azure.com/) |
| **Status Endpoint** | [https://mh-skills-coach.francecentral.cloudapp.azure.com/status](https://mh-skills-coach.francecentral.cloudapp.azure.com/status) |
| **API Health** | [https://mh-skills-coach.francecentral.cloudapp.azure.com/api/health](https://mh-skills-coach.francecentral.cloudapp.azure.com/api/health) |
| **Stripe Webhook** | [https://mh-skills-coach.francecentral.cloudapp.azure.com/api/payments/webhook](https://mh-skills-coach.francecentral.cloudapp.azure.com/api/payments/webhook) |

### Deployment Steps

```bash
# 1. Prepare production environment
cp .env.prod.example .env

# 2. Edit .env with production values (see below)

# 3. Deploy
./scripts/deploy_vm.sh

# Or manually:
docker compose -f docker-compose.prod.yml up -d --build

# 4. Verify deployment
curl https://mh-skills-coach.francecentral.cloudapp.azure.com/status
```

---

## 🗺 Roadmap

### Testing & Quality
- [ ] End-to-end integration tests for multi-agent flows
- [ ] Continuous safety auditing and false positive/negative tracking
- [ ] Load testing for production readiness
- [ ] Automated regression testing in CI/CD

### Features
- [ ] Enhanced provider filtering and ranking (specialty, availability, insurance, language)
- [ ] User feedback collection for continuous improvement
- [ ] Conversation history and progress tracking
- [ ] Mobile app (React Native or Flutter)

### Operations
- [ ] Automated deployment pipelines (GitHub Actions)
- [ ] Monitoring and observability (Prometheus, Grafana, Sentry)
- [ ] Database backup and disaster recovery procedures
- [ ] Rate limiting and abuse prevention
- [ ] Internationalization (i18n) beyond Sweden

### Safety Enhancements
- [ ] LLM-based crisis detection backup (complement keyword matching)
- [ ] Output content filtering (detect medical advice in responses)
- [ ] Conversation-level risk assessment
- [ ] Human review queue for flagged conversations

---

## ⚖️ Legal Disclaimer

**This application is not a substitute for professional mental health care.**

MH Skills Coach provides educational information and self-help tools only. It does not:
- Diagnose mental health conditions
- Prescribe medications or treatments
- Provide therapy or clinical counseling
- Offer medical advice

If you are experiencing a mental health crisis, please:
- Call your local emergency number (Sweden: 112)
- Contact a crisis helpline (Sweden: Mind Självmordslinjen 90101, 1177 Vårdguiden)
- Visit the nearest emergency room

Always consult with licensed healthcare professionals for medical decisions.

---

**Built with ❤️ for mental health support accessibility**
