# TODO (Prioritized)

## P0 - Search Quality
- Improve therapist result filtering/ranking to reduce non-therapy business matches from OSM/Overpass data.
- Add stricter category heuristics and optional exclusion rules.

## P1 - Booking UX
- Improve booking proposal presentation in UI (clearer status, expiry visibility, and confirmation affordances).
- Add clearer inline guidance for missing booking fields.

## P1 - Operational Hardening
- Add explicit API rate limiting for chat and MCP tool endpoints.
- Improve structured logging and request correlation IDs.

## P2 - Environment & Delivery
- Strengthen environment separation (local/staging/prod) while keeping `.env.example` non-secret.
- Add a production OAuth + Stripe readiness checklist for release gating.

## P2 - Observability
- Add a lightweight monitoring dashboard (service health/status, tool success/error rates, queue/backlog signals).
