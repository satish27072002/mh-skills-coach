#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${APP_DOMAIN:-mh-skills-coach.francecentral.cloudapp.azure.com}"
BASE_URL="https://${DOMAIN}"

docker compose -f docker-compose.prod.yml up -d --build

echo "Deployment started."
echo "Proxy mapping:"
echo "  /api/* on public domain is stripped and forwarded to backend routes."
echo "  Example: ${BASE_URL}/api/health -> backend /health"
echo "Test URLs:"
echo "  ${BASE_URL}/"
echo "  ${BASE_URL}/status"
echo "  ${BASE_URL}/api/health"
