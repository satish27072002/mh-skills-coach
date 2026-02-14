#!/usr/bin/env bash
set -euo pipefail

APP_DOMAIN="${APP_DOMAIN:-mh-skills-coach.francecentral.cloudapp.azure.com}"
BASE_URL="https://${APP_DOMAIN}"

docker compose -f docker-compose.prod.yml ps
echo "Verifying Caddy /api strip-prefix routing..."
echo "  ${BASE_URL}/api/health should map to backend /health"
curl -f "${BASE_URL}/status"
curl -f "${BASE_URL}/api/health"

echo
echo "Production verification checks passed for ${BASE_URL}"
