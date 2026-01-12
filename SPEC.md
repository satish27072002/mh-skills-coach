# SPEC.md — Mental Health Skills Coach (Portfolio Project)

## Goal (Demo Flow)
1) User signs in with Google.
2) User chats: "I feel anxious right now" → coach suggests a grounding exercise + timer card.
3) User asks for diagnosis/prescription → coach refuses safely + suggests professional help + offers premium membership.
4) User clicks "Go Premium" → Stripe Checkout (test mode) → premium unlocks extra coaching programs.
5) User asks to find therapist → show curated legit platforms/providers with filters and links.

## Non-goals (V1)
- No saving chat transcripts/history
- No in-app telehealth sessions
- No scraping random therapist sites
- No diagnosis/prescription/medication advice

## Stack
Frontend: Next.js (App Router) + Tailwind
Backend: FastAPI (Python)
Tool layer: MCP Server (remote HTTP transport)
DB: Postgres (Supabase free tier OK) — store users + entitlement + minimal audit
Cache/session: Redis (optional; can start without)
Payments: Stripe Checkout one-time payment (test mode) + webhooks
Local dev: Docker Compose

## Services
1) apps/frontend
2) services/backend
3) services/mcp
4) postgres (container for local dev)

## Auth (Option B)
- Google OIDC Authorization Code flow + PKCE
- Backend verifies ID token
- Backend uses HttpOnly Secure cookies for session
Endpoints:
- GET /auth/google/start
- GET /auth/google/callback
- GET /me
- POST /logout

## Premium Model (Model A)
- One-time lifetime purchase
- Stripe Checkout session creation endpoint
- Stripe webhook endpoint:
  - verify signature
  - idempotent processing (store stripe_event_id)
Entitlement:
- users.is_premium boolean

## Therapist Directory (Level 1)
- Curated list of legit platforms/providers (stored as JSON or DB)
- Filter fields: city/region, language, online/in-person
- Output: name + link + short rationale
No scraping.

## Chat Orchestration
- Backend exposes POST /chat
- Safety router runs first:
  - crisis → crisis response
  - diagnosis/prescription/medication → refusal + professional help + premium offer
  - else → skills coach response
- Response should be structured JSON:
  - coach_message
  - exercise(optional): {type, steps, duration_seconds}
  - resources(optional): [{title, url}]
  - premium_cta(optional): {enabled, message}

## MCP Tools (initial)
- kb.search(query, filters, top_k)
- kb.get_chunk(chunk_id)
- premium.check_entitlement(user_id)
- booking.suggest_providers(filters)
- payments.create_checkout_session(user_id)
- audit.log(event)

In V1, kb tools can be stubbed with a small "knowledge cards" list; later swap to pgvector.

## Docker
- docker compose up --build should start:
  - frontend on :3000
  - backend on :8000
  - mcp server on :7000
  - postgres on :5432
