# Mental Health Skills Coach

## What it is
A safety-gated mental health skills coach that guides grounding and coping exercises, with premium therapist discovery for users who want to go further.

## Key features
- Crisis and self-harm safety routing with immediate resources
- Diagnosis/prescription refusal flow with professional help guidance
- Google OIDC Authorization Code flow with PKCE and HttpOnly cookies
- Stripe test-mode one-time lifetime checkout + webhook idempotency
- Premium-gated therapist search

## Tech stack
Next.js (App Router), FastAPI, MCP server, Postgres/pgvector, Stripe (test mode), Docker Compose.

## Architecture services
- `proxy` (Caddy)
- `frontend` (Next.js)
- `backend` (FastAPI)
- `mcp` (tool service)
- `postgres` (pgvector)

## Therapist search via MCP
- Therapist lookup is now handled by MCP tool `therapist_search` (`services/mcp`) and called from backend via HTTP client.
- Backend no longer performs direct Nominatim/Overpass calls in the chat or `/therapists/search` path.

## Email tool setup (MCP)
- The MCP service exposes `POST /tools/send_email` and sends mail via SMTP.
- Test providers:
  - Mailtrap SMTP (recommended for local testing)
  - Gmail SMTP with an App Password (do not use account password)
- Required env vars:
  - `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`
  - Optional: `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS` (default `true`)
- Verify:
  - `curl -X POST http://localhost:7000/tools/send_email -H "Content-Type: application/json" -d "{\"to\":\"you@example.com\",\"subject\":\"Test\",\"body\":\"Hello\"}"`

## Embeddings provider switching (backend)
- Key env vars:
  - `EMBED_PROVIDER=ollama|openai`
  - `OPENAI_API_KEY` (required when `EMBED_PROVIDER=openai`)
  - `OPENAI_EMBED_MODEL` (default `text-embedding-3-small`)
  - `EMBEDDING_DIM` (optional; auto-detected on startup when omitted and `EMBED_PROVIDER=openai`)
- Check backend status:
  - `GET /status` returns `llm_provider`, `embed_provider`, and `embed_dim`.
- Ingest 3 test docs:
  - Put 3 `.txt`/`.pdf` files under `data/papers/`
  - Run: `python -m app.ingest --path /data/papers --reset`
- If you switch embedding provider/model and dimension changes:
  1. Apply migration:
     - `psql "$DATABASE_URL" -v target_dim=1536 -f services/backend/sql/alter_chunks_embedding_dim.sql`
  2. Reindex vectors:
     - `python -m app.scripts.reindex_embeddings`

## Local dev
1. Set env values in `.env` (see `.env.example`).
2. Start stack:
   - `docker compose up -d --build`
3. Open:
   - Frontend: `http://localhost:3000`
   - Backend API docs: `http://localhost:8000/docs`
   - MCP health: `http://localhost:7000/health`
   - Caddy entrypoint: `http://localhost`

## VM prod (Azure)
1. Assign a DNS label to the VM Public IP in Azure (for example `your-app.region.cloudapp.azure.com`).
2. In the VM Network Security Group, allow inbound TCP `80` and `443`.
3. Set env vars in `.env`:
   - `APP_DOMAIN=<your-hostname>`
   - `FRONTEND_URL=https://<your-hostname>`
   - `GOOGLE_REDIRECT_URI=https://<your-hostname>/auth/google/callback`
   - `NEXT_PUBLIC_API_BASE_URL=https://<your-hostname>`
4. Start stack:
   - `docker compose up -d --build`
5. Configure external providers:
   - Google OAuth redirect URL: `https://<your-hostname>/auth/google/callback`
   - Stripe webhook URL: `https://<your-hostname>/payments/webhook`
6. Caddy hostname:
   - `docker-compose.yml` passes `APP_DOMAIN` to Caddy using `Caddyfile.oracle`.
   - Caddy terminates TLS for `https://<your-hostname>`.

## Notes
- Do not commit secrets to git.
- Keep credentials in `.env` only (`GOOGLE_CLIENT_SECRET`, `STRIPE_SECRET_KEY`, `OPENAI_API_KEY`, `SMTP_PASSWORD`, etc.).

## Live URL
<URL>
