# Deployment Guide

This document describes how to deploy MH Skills Coach safely for production-like environments.

## Overview
Current stack:
- `proxy` (Caddy)
- `frontend` (Next.js)
- `backend` (FastAPI)
- `mcp` (tool service)
- `postgres` (pgvector)

Production deployment should keep this topology (or equivalent managed services) and enforce HTTPS.

## Production Essentials

### 1) Domain + HTTPS
- Set `APP_DOMAIN` to your real hostname.
- Use HTTPS termination at the reverse proxy (Caddy is already in the stack).
- Ensure DNS points to the host running the proxy.

### 2) Database
- Use either:
  - managed Postgres with pgvector enabled, or
  - containerized Postgres + pgvector with reliable backups.
- Set `DATABASE_URL` to the production database.

### 3) Cookie Security
- Set:
  - `COOKIE_SECURE=true`
  - `COOKIE_SAMESITE=lax` for same-site flows, or `none` when cross-site cookie behavior is required with HTTPS.

### 4) Google OAuth
- Configure Google OAuth client for deployed domain.
- Set `GOOGLE_REDIRECT_URI` to deployed callback endpoint (same route used by backend).
- Confirm frontend/backend URLs match the deployed host.

### 5) Stripe
- Configure production/test keys appropriately via env vars.
- Set webhook endpoint to your deployed domain:
  - `POST /payments/webhook`
- Verify signature secret is configured.

### 6) SMTP (MCP send_email)
- Use real SMTP provider credentials in production.
- Mailtrap can be used for non-production/testing environments.
- Set `SMTP_*` env vars on the `mcp` service.

## Local vs Production Differences
- **Auth/Premium behavior**:
  - `DEV_MODE=true` allows therapist-search testing without strict premium/auth gating.
  - Production should run with `DEV_MODE=false`.
- **Security**:
  - Local may use `COOKIE_SECURE=false`; production should use `true`.
- **Ingress**:
  - Local usually uses `localhost` and mapped ports.
  - Production uses real domain + HTTPS through proxy.
- **Secrets**:
  - Local may use placeholders.
  - Production must provide real credentials via environment/secret manager.

## Sanity Checks
Run after deployment:

### Service health
```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/status
curl -fsS http://localhost:7001/health
```

### Therapist search smoke test (MCP)
```bash
curl -fsS -X POST http://localhost:7001/tools/therapist_search \
  -H "Content-Type: application/json" \
  -d '{"location_text":"Stockholm","radius_km":25,"limit":5}'
```

### Email tool smoke test (MCP)
```bash
curl -fsS -X POST http://localhost:7001/tools/send_email \
  -H "Content-Type: application/json" \
  -d '{"to":"dummy@example.com","subject":"SMTP smoke","body":"test"}'
```

### Compose status
```bash
docker compose ps
```

## Notes
- Do not commit secrets to git.
- Keep `.env.example` as non-secret documentation only.
- Use `.env` or a secret manager for real credentials.
