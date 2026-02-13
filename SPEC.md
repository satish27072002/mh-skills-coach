# System Specification

## Product Summary
MH Skills Coach provides:
- conversational coping-skills support,
- therapist discovery,
- booking email preparation/sending with explicit confirmation.

## Architecture Overview

### Services
- `apps/frontend` (Next.js): UI, chat client, auth/payment pages.
- `services/backend` (FastAPI): API, routing, agents, safety enforcement, payment/auth orchestration.
- `services/mcp` (FastAPI tool service): external tool endpoints.
- `postgres` (pgvector): relational data + vector storage.
- `proxy` (Caddy): reverse proxy/TLS entrypoint.

### Communication Paths
- Frontend -> Backend HTTP APIs.
- Backend -> MCP tools over HTTP:
  - `POST /tools/therapist_search`
  - `POST /tools/send_email`
- Backend -> Postgres/pgvector for users, payments, pending actions, and embeddings/chunks flows.
- Backend -> LLM provider (`openai`, `ollama`, or `mock` depending on env).

## Backend Endpoints
- `POST /chat`
- `POST /therapists/search`
- `POST /payments/create-checkout-session`
- `POST /payments/webhook`
- `GET /health`
- `GET /status`

Also present for auth/session:
- `GET /auth/google/start`
- `GET /auth/google/callback`
- `GET /me`
- `POST /logout`

## Chat Routing and Agents

### Order of execution (`POST /chat`)
1. Safety gate checks crisis/self-harm intent.
2. Prescription/diagnosis refusal path.
3. Router selects one route:
   - `THERAPIST_SEARCH`
   - `BOOKING_EMAIL`
   - `COACH`

### Therapist search behavior
- Intent routes to `TherapistSearchAgent`.
- Inputs parsed from message:
  - `location_text` (required to run search)
  - `radius_km` (default `25`, clamped to `1..50`)
  - `limit` (default `10`, clamped to `1..10`)
  - `specialty` optional
- If location is missing:
  - Responds: **“Please share a city or postcode so I can search nearby providers.”**
  - Stores pending location state and waits for next short location reply.
- Specialty handling:
  - Specialty is optional.
  - Backend omits `specialty` in MCP payload unless non-empty.

### Booking/email behavior
- Booking intent routes to `BookingEmailAgent`.
- Collects required fields:
  - therapist email
  - requested datetime
- When complete:
  - creates booking proposal
  - returns `requires_confirmation=true`
- On `YES`:
  - sends email via MCP `send_email`
  - clears pending booking state
- On `NO`:
  - clears pending booking state
- Supports multiple sequential booking emails (each with independent confirmation).

## MCP Tools

### therapist_search
- Endpoint: `POST /tools/therapist_search`
- Input: `location_text`, optional `radius_km`, optional `specialty`, optional `limit`
- Returns normalized provider results:
  - `name`, `address`, `distance_km`, `phone`, `email`, `source_url`

### send_email
- Endpoint: `POST /tools/send_email`
- Uses SMTP env vars for delivery.
- Validates payload and returns structured success/error JSON.

## Auth and Premium Rules
- In non-dev mode:
  - `/therapists/search` requires authenticated premium user.
  - chat therapist search is premium-gated.
- In `DEV_MODE=true`:
  - therapist search is allowed without premium/auth for local testing.

## Data and Persistence
- Postgres stores:
  - users
  - Stripe event idempotency records
  - pending booking actions
  - outbound email audit rows
- pgvector used for embedding/chunk retrieval paths.

## Environment Variables (high level)
Use `.env.example` for the full list. Key groups:
- Runtime mode: `DEV_MODE`
- URLs/networking: `FRONTEND_URL`, `NEXT_PUBLIC_API_BASE_URL`, `API_BASE_URL`, `APP_DOMAIN`, `MCP_BASE_URL`
- Database: `DATABASE_URL`, `POSTGRES_*`
- LLM/embeddings: `LLM_PROVIDER`, `EMBED_PROVIDER`, `OPENAI_API_KEY`, `OLLAMA_*`, `EMBEDDING_DIM`
- Auth: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`
- Payments: `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`
- Email/SMTP: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS`
- Cookies: `COOKIE_SECURE`, `COOKIE_SAMESITE`
