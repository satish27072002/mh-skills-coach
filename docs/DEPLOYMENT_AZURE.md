# Azure VM Deployment

This guide deploys MH Skills Coach on an Azure VM with Caddy-managed HTTPS.

## Domain
- `mh-skills-coach.francecentral.cloudapp.azure.com`

## Prerequisites
- Ubuntu VM with public IP + DNS label configured.
- Ports `80` and `443` open in NSG/firewall.
- Docker Engine + Docker Compose plugin installed.

### Install Docker on Ubuntu 24.04
```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### Verify install
```bash
docker --version
docker compose version
```

## Deploy Steps
1. Clone and switch to the deployment branch:
```bash
git clone <your-repo-url>
cd mh-skills-coach
git checkout deploy/azure-vm
```

2. Create runtime env file:
```bash
cp .env.prod.example .env
```

3. Edit `.env` and fill real secrets (`GOOGLE_*`, `STRIPE_*`, `OPENAI_API_KEY`, `SMTP_*`, DB password).

4. Start production stack:
```bash
docker compose -f docker-compose.prod.yml up -d --build
```

### Proxy behavior (important)
- Public path prefix `/api/*` is stripped by Caddy before forwarding to backend.
- Example mappings:
  - `/api/health` -> backend `/health`
  - `/api/payments/webhook` -> backend `/payments/webhook`

## Verify
```bash
curl -f https://mh-skills-coach.francecentral.cloudapp.azure.com/status
curl -f https://mh-skills-coach.francecentral.cloudapp.azure.com/api/health
```

Then open:
- `https://mh-skills-coach.francecentral.cloudapp.azure.com/`

## Stripe Webhook Setup
- Endpoint URL:
  - `https://mh-skills-coach.francecentral.cloudapp.azure.com/api/payments/webhook`
- Event source:
  - `Your account` (not Connect).
- Required event:
  - `checkout.session.completed`
- Payload style:
  - `Snapshot`

After adding the webhook in Stripe, copy the signing secret into:
- `STRIPE_WEBHOOK_SECRET` in `.env`
