# Mental Health Skills Coach (Portfolio Project)

## Path A deployment (Cloudflare Pages + Tunnel)
This setup hosts the frontend on Cloudflare Pages at `https://app.<domain>` while the backend stays on your machine and is exposed via Cloudflare Tunnel at `https://api.<domain>`. It keeps hosting free, avoids public backend ports, and is easy to migrate later by moving the backend container to a VM or managed service in AWS/GCP.

## Deployment steps (Path A)
1) Cloudflare Pages (frontend)
   - Create a Pages project from this repo.
   - Framework preset: Next.js.
   - Build command: `npm run build`
   - Output directory: `.next` (or leave default for Next.js).
   - Set environment variable: `NEXT_PUBLIC_API_BASE_URL=https://api.<domain>`
   - Add custom domain: `app.<domain>`
2) Cloudflare Tunnel (backend)
   - In Cloudflare Zero Trust, create a named tunnel.
   - Add a public hostname: `api.<domain>` with service `http://backend:8000`.
   - Copy the tunnel token.
3) Backend environment variables
   - Copy `.env.example` to `.env` and fill in values:
     - `FRONTEND_URL=https://app.<domain>`
     - `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
     - `GOOGLE_REDIRECT_URI=https://api.<domain>/auth/google/callback`
     - `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`
     - `COOKIE_SECURE=true`
     - `CLOUDFLARED_TOKEN=...`
4) Google OAuth
   - Update the OAuth client redirect URI to `https://api.<domain>/auth/google/callback`.
5) Stripe (test mode)
   - Create a one-time price.
   - Add webhook endpoint: `https://api.<domain>/payments/webhook`.
   - Copy `STRIPE_WEBHOOK_SECRET`.
6) Run the stack
   - Local only (no tunnel): `docker compose up --build`
   - With tunnel: `docker compose --profile tunnel up --build`

## Security posture
- HTTPS enforced by Cloudflare on both app and api domains.
- Secure HttpOnly cookies with `COOKIE_SECURE=true` in deployed mode.
- CORS allowlist includes `FRONTEND_URL` and localhost dev origins with credentials enabled.
- Backend port binds to `127.0.0.1` and is only exposed via Cloudflare Tunnel.

## Run locally
From the repo root:
```
docker compose up --build
```
URLs:
- Frontend: http://localhost:3000
- Backend:  http://localhost:8000
- MCP:      http://localhost:7000
- Frontend API base: set `NEXT_PUBLIC_API_BASE_URL` (docker default http://backend:8000; local default http://localhost:8000)

## Run tests
From the repo root:
```
docker compose up -d --build
docker compose exec backend python -m pytest -q
docker compose exec frontend npm test -- --run
docker compose down
```

## Status endpoint
`GET /status` reports whether the backend is running in deterministic mode or ready for LLM+RAG. When Ollama is off or pgvector is unavailable, the mode stays deterministic.
- The frontend header shows the agent mode pill and model name based on `/status` (polled every 10s).

## Paper sources
Source metadata lives in `data/ingest_sources.json`. Local PDFs should be placed in `data/papers/` (gitignored); PDFs are not committed.

## Ollama (local)
Start services with Docker Compose, then pull the model:
```
docker compose up -d --build
docker compose exec ollama ollama pull gemma2:2b
```

## Embeddings + ingestion (local)
Pull the embeddings model:
```
docker compose exec ollama ollama pull nomic-embed-text
```
Set env vars:
- `OLLAMA_EMBED_MODEL=nomic-embed-text`
- `EMBEDDING_DIM` must match the embedding model dimension.

Ingest local papers (PDF/TXT) from `data/papers/`:
```
docker compose exec backend python -m app.ingest --path /data/papers --reset
```

Quick retrieval sanity check:
```
docker compose exec backend python -c "from app.db import retrieve_similar_chunks; print(retrieve_similar_chunks('stress'))"
```

## Demo chat (local)
1) `docker compose up --build`
2) Open http://localhost:3000
3) Enter a prompt like "I feel anxious right now" and click "Send"
4) You should see the coach message, exercise steps, and agent mode badge

## Stripe Checkout (sandbox)
Env placeholders live in `.env.example`. Set them in `.env`:
- `STRIPE_SECRET_KEY=__PASTE_SK_TEST__`
- `STRIPE_PRICE_ID=__PASTE_PRICE_ID__`
- `STRIPE_WEBHOOK_SECRET=__PASTE_WHS__`
- `FRONTEND_URL=http://localhost:3000`

Stripe CLI webhook listener:
```
stripe listen --forward-to http://localhost:8000/payments/webhook
```

Manual verification:
1) Start services: `docker compose up --build`
2) In the UI, click "Get Premium" and complete the Stripe test checkout.
3) After redirect to `/premium/success`, refresh the app and confirm "Premium Active".

## Therapist search (premium)
- Therapist search is gated behind premium. In chat, ask for a therapist and the UI will show a "Find me a therapist" button.
- Mark a local user as premium, then use the UI button:
```
docker compose exec backend python -c "from app.db import SessionLocal; from app.models import User; s=SessionLocal(); u=s.query(User).first(); u.is_premium=True; s.commit()"
```
- The modal submits `POST /therapists/search` and renders returned providers.

## Google login (local)
Set these env vars (backend):
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI` (default: http://localhost:8000/auth/google/callback)
- `FRONTEND_URL` (default: http://localhost:3000)
Note: If you cancel Google consent, you'll be returned to the app with an error banner.

## Demo script
Copy-paste prompts and expected behavior:
1) "I feel anxious right now"
   - Normal coaching with a grounding/breathing exercise.
2) "Can you diagnose me with ADHD?"
   - Refusal + suggest professional help + premium CTA.
3) "I want to end my life"
   - Crisis-safe response with emergency guidance; no upsell.
4) "What do I get with premium?"
   - Premium CTA and brief benefits (no medical claims).
5) "Find a therapist in Stockholm who speaks English"
   - Returns curated provider links with brief rationale.
