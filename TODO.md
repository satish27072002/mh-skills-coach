# TODO.md

## Milestone 1 — Skeleton
- [ ] Next.js app with simple chat UI
- [ ] FastAPI backend with /health
- [ ] MCP server with stub tools
- [ ] Docker Compose runs all services

## Milestone 2 — Auth (Google OIDC + PKCE)
- [ ] /auth/google/start + /auth/google/callback
- [ ] Session via HttpOnly cookie
- [ ] /me endpoint

## Milestone 3 — Chat + Safety Router
- [ ] POST /chat
- [ ] diagnosis/prescription refusal path
- [ ] crisis-safe path (no upsell)
- [ ] basic skills templates

## Milestone 4 — Premium (Stripe test mode)
- [ ] create checkout session
- [ ] webhook verify + idempotency
- [ ] set is_premium true

## Milestone 5 — Therapist Directory (Level 1)
- [ ] curated JSON list + filters
- [ ] MCP tool booking.suggest_providers
- [ ] UI renders links

## Milestone 6 — Knowledge Base (RAG-lite)
- [ ] knowledge cards
- [ ] citations panel (even if internal)
- [ ] swap to pgvector later

## Testing
- [ ] unit tests for safety router
- [ ] integration test for webhook idempotency
- [ ] basic e2e Playwright flow (optional)
