# Oracle VM Deployment (Docker Compose)

This project is designed to run on a single Oracle Cloud VM with Docker Compose and Caddy as reverse proxy.
No Vercel is required.

## 1) Provision VM

- Create an Ubuntu VM (recommended: 2 vCPU, 4+ GB RAM).
- Attach a public IP.
- Open inbound ports in Oracle Security List / NSG:
  - `22` (SSH)
  - `80` (HTTP)
  - `443` (HTTPS)
- Point DNS `A` record for your domain to the VM public IP.

## 2) Install Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
```

Re-login to apply group membership.

## 3) App configuration

Clone the repo and create `.env` from `.env.example`.

Required production values:
- `APP_DOMAIN=your-domain.com`
- `FRONTEND_URL=https://your-domain.com`
- `NEXT_PUBLIC_API_BASE_URL=https://your-domain.com`
- `GOOGLE_REDIRECT_URI=https://your-domain.com/auth/google/callback`
- `COOKIE_SECURE=true`
- `COOKIE_SAMESITE=lax`
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`

Do not commit `.env`.

## 4) Google OAuth setup

In Google Cloud Console for your OAuth client:
- Authorized JavaScript origin: `https://your-domain.com`
- Authorized redirect URI: `https://your-domain.com/auth/google/callback`

## 5) Stripe setup (test mode)

- Create a one-time price and set `STRIPE_PRICE_ID`.
- Add webhook endpoint:
  - `https://your-domain.com/payments/webhook`
- Listen at minimum to `checkout.session.completed`.
- Copy signing secret into `STRIPE_WEBHOOK_SECRET`.

## 6) Start services

From repository root:

```bash
docker compose -f infra/docker-compose.oracle.yml up -d --build
```

This uses:
- `Caddyfile.oracle` for TLS termination and path routing
- backend auth cookies (`HttpOnly`, `Secure`) over HTTPS
- backend Stripe checkout + webhook idempotency for entitlement updates

## 7) Verify deployment

Run these checks:

```bash
curl -i https://your-domain.com/health
curl -i https://your-domain.com/status
curl -i https://your-domain.com/me
```

Expected:
- `/health` -> `200`
- `/status` -> `200`
- `/me` -> `401` before login, `200` after Google login

Premium verification:
1. Login with Google.
2. Start checkout from UI.
3. Complete Stripe test payment.
4. Confirm webhook delivery success in Stripe dashboard.
5. Reload app and verify premium-only therapist flow unlocks.

## 8) Operations

- View logs:
```bash
docker compose -f infra/docker-compose.oracle.yml logs -f
```
- Restart:
```bash
docker compose -f infra/docker-compose.oracle.yml restart
```
- Update:
```bash
git pull
docker compose -f infra/docker-compose.oracle.yml up -d --build
```
