# Deployment (Optional / Future)

This guide covers the optional Path A deployment: frontend on Cloudflare Pages at `https://app.<domain>` and backend exposed from your machine via Cloudflare Tunnel at `https://api.<domain>`. It is designed for a free hosting footprint and can be migrated later to a VM or managed service without changing URLs.

## Prerequisites
- A custom domain with DNS managed in Cloudflare.
- Cloudflare Pages enabled for the frontend.
- Cloudflare Zero Trust enabled for Tunnel creation.
- Google OAuth client and Stripe test-mode credentials.

## Environment configuration
Copy `.env.example` to `.env` and set values:
- `FRONTEND_URL=https://app.<domain>`
- `NEXT_PUBLIC_API_BASE_URL=https://api.<domain>`
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI=https://api.<domain>/auth/google/callback`
- `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`
- `CLOUDFLARED_TOKEN=...`
- `COOKIE_SECURE=true`

## Cloudflare Pages (frontend)
1) Create a Pages project from this repo.
2) Build command: `npm run build`
3) Framework preset: Next.js (or auto-detect).
4) Add environment variable: `NEXT_PUBLIC_API_BASE_URL=https://api.<domain>`
5) Add custom domain: `app.<domain>`

## Cloudflare Tunnel (backend)
1) Create a named tunnel in Cloudflare Zero Trust.
2) Add a public hostname:
   - Hostname: `api.<domain>`
   - Service: `http://backend:8000`
3) Copy the tunnel token into `CLOUDFLARED_TOKEN`.

## Google OAuth
Update your OAuth client redirect URI to:
```
https://api.<domain>/auth/google/callback
```

## Stripe (test mode)
1) Create a one-time price in Stripe.
2) Add a webhook endpoint:
```
https://api.<domain>/payments/webhook
```
3) Copy the webhook secret to `STRIPE_WEBHOOK_SECRET`.

## Run commands
Local only (no tunnel):
```
docker compose up --build
```
With Cloudflare Tunnel:
```
docker compose --profile tunnel up --build
```

## Security posture
- HTTPS enforced by Cloudflare on both `app` and `api` domains.
- Secure HttpOnly cookies with `COOKIE_SECURE=true` in deployed mode.
- CORS allowlist includes `FRONTEND_URL` and localhost dev origins with credentials enabled.
- Backend binds to `127.0.0.1` and is only exposed via Cloudflare Tunnel.
