# MH Skills Coach

MH Skills Coach is a safety-first mental-health support product that helps users:
- practice practical coping skills in chat,
- discover nearby therapists/clinics,
- prepare and confirm booking emails to providers.

It is designed as a coaching and navigation tool, not a replacement for licensed clinical care.

## Problem This Product Solves
People often need support in two phases:
- Immediate emotional support and actionable self-regulation skills.
- A fast path to finding professional care and contacting providers.

MH Skills Coach combines both in one workflow: guided coaching + therapist discovery + booking email assistance.

## Key Features
- RAG-enabled coaching responses for grounded, contextual skill guidance.
- Multi-agent chat orchestration:
  - `TherapistSearchAgent` for provider lookup.
  - `EmailBookingAgent` (implemented in code as `BookingEmailAgent`) for booking email proposals and confirmation flow.
- MCP tool integration:
  - `therapist_search` for provider discovery.
  - `send_email` for booking email delivery.
- Safety guardrails with crisis detection and escalation guidance.
- Premium gating for therapist search and premium features in non-dev mode.
- Payment flow with Stripe test-mode checkout and webhook handling.

## Tech Stack
- Frontend: Next.js (App Router)
- Backend: FastAPI
- Tool Service: MCP (HTTP tools)
- Data: Postgres + pgvector
- Reverse Proxy: Caddy
- Local Orchestration: Docker Compose

## High-Level Architecture
- `frontend` sends user interactions to backend APIs.
- `backend` routes chat intent and coordinates safety, agents, and business logic.
- `backend` calls `mcp` tools for therapist search and email sending.
- `backend` reads/writes app state in `postgres` (including vector-backed retrieval paths).
- `proxy` (Caddy) fronts frontend/backend for unified ingress.

## Multi-Agent Design
Backend chat routing is explicit and agent-based:
- `SafetyGate` runs first and can short-circuit normal flow for crisis handling.
- `Router` selects one route:
  - `THERAPIST_SEARCH`
  - `BOOKING_EMAIL`
  - `COACH`
- Specialized agents execute:
  - `TherapistSearchAgent`: parses location/radius/specialty/limit, calls MCP therapist search, returns `ChatResponse.therapists`.
  - `EmailBookingAgent`: manages pending booking state, collects missing fields, issues booking proposal, handles `YES`/`NO`, sends email via MCP.

## API Endpoints (Current)
- `POST /chat`
- `POST /therapists/search`
- `POST /payments/create-checkout-session`
- `POST /payments/webhook`
- `GET /health`
- `GET /status`

## Data Flow Diagrams

### 1) Chat + RAG Flow
```text
[User]
   |
   v
[Frontend (Next.js)]
   |
   v
[POST /chat -> Backend Router]
   |
   +--> [SafetyGate] --(crisis)--> [Crisis response + guidance]
   |
   +--> [COACH route] --> [RAG/LLM path]
                            |
                            v
                      [Postgres + pgvector]
                            |
                            v
                       [ChatResponse]
```

### 2) Therapist Search + Booking Email Flow
```text
[User chat intent]
   |
   v
[POST /chat]
   |
   +--> [TherapistSearchAgent]
   |        |
   |        v
   |   [MCP therapist_search]
   |        |
   |        v
   |   [therapists[] in ChatResponse]
   |
   +--> [EmailBookingAgent]
            |
            v
   [Pending proposal in DB -> requires_confirmation=true]
            |
            +-- "YES" --> [MCP send_email] --> [clear pending]
            +-- "NO"  --> [clear pending]
```

## Safety & Compliance
- This app does **not** provide diagnosis, prescriptions, or medication instructions.
- It is **not medical advice** and does not replace licensed care.
- If self-harm/suicide intent is detected:
  - The app provides supportive crisis guidance.
  - Recommends contacting local emergency services and helplines.
  - In Sweden context, messaging includes emergency/support references (for example 112, 1177, and suicide support lines).
  - Suggests therapist search as next-step support when appropriate.

## Quickstart (Local)
```bash
docker compose up -d --build
docker compose exec backend python -m app.ingest --path /data/papers --reset
```

## Deployment (Azure VM)
1. Prepare production environment values:
```bash
cp .env.prod.example .env
```
2. Edit `.env` with real secrets (OAuth, Stripe, SMTP, OpenAI) and keep:
- `FRONTEND_URL=https://mh-skills-coach.francecentral.cloudapp.azure.com`
- `APP_BASE_URL=https://mh-skills-coach.francecentral.cloudapp.azure.com`
- `GOOGLE_REDIRECT_URI=https://mh-skills-coach.francecentral.cloudapp.azure.com/auth/google/callback`
- `NEXT_PUBLIC_API_BASE_URL=/api`
3. Deploy on VM:
```bash
./scripts/deploy_vm.sh
```
Equivalent command:
```bash
docker compose -f docker-compose.prod.yml up -d --build
```
Production ingress files:
- `docker-compose.prod.yml`
- `Caddyfile.prod`
Proxy rule:
- public `/api/*` is stripped before forwarding to backend routes (for example, `/api/health` -> `/health`).
4. Validate:
- `https://mh-skills-coach.francecentral.cloudapp.azure.com/`
- `https://mh-skills-coach.francecentral.cloudapp.azure.com/status`
- `https://mh-skills-coach.francecentral.cloudapp.azure.com/api/health`
- Stripe webhook endpoint: `https://mh-skills-coach.francecentral.cloudapp.azure.com/api/payments/webhook`

## Additional Docs
- `SPEC.md`
- `SAFETY.md`
- `TODO.md`
- `docs/DEPLOYMENT.md`
- `docs/DEPLOYMENT_AZURE.md`

## Secrets & Environment
- Copy `.env.example` to `.env` and configure values for your environment.
- Never commit secrets (API keys, OAuth secrets, SMTP credentials, Stripe keys).
- Keep all sensitive values in `.env` only.

Common variables (see `.env.example`):
- App URLs: `FRONTEND_URL`, `NEXT_PUBLIC_API_BASE_URL`, `API_BASE_URL`, `APP_DOMAIN`
- OAuth: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`
- Payments: `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`
- Backend/tooling: `DEV_MODE`, `DATABASE_URL`, `MCP_BASE_URL`, `LLM_PROVIDER`, `EMBED_PROVIDER`
- SMTP tool config: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS`

## Roadmap
- Production deployment hardening and release automation.
- Better provider filtering/ranking (specialty, availability, insurance/language options).
- Product analytics for safety outcomes and conversion funnels.

## Development Notes
- Use `docker compose ps` to confirm healthy services.
- Backend health/status checks:
  - `curl -fsS http://localhost:8000/health`
  - `curl -fsS http://localhost:8000/status`
- MCP health check:
  - `curl -fsS http://localhost:7001/health`

## Screenshots / Demo
- Placeholder: add chat, therapist-search, and booking-proposal screenshots here.
