# AGENTS.md (Instructions for Codex)

You are implementing this repository according to SPEC.md and SAFETY.md.

Non-negotiables:
- Read SPEC.md and SAFETY.md before writing code.
- Do NOT store chat history or message transcripts in any database, file, or logs.
- Do NOT implement diagnosis, prescriptions, medication advice, or therapy claims.
- If user asks for diagnosis/prescription/medication: refuse and offer professional help + optional premium membership.
- If crisis/self-harm signals: show crisis-safe response and resources; do not upsell.
- Use Next.js (frontend), FastAPI (backend), an MCP server (tools), Docker Compose for local run.
- Auth: Google OIDC Authorization Code flow with PKCE, secure HttpOnly cookies.
- Payments: Stripe Checkout one-time lifetime purchase in TEST mode + webhook verification + idempotency.

Coding standards:
- Typed Python where reasonable
- JSON schema validation for tool responses
- Minimal but clean, readable code
- Add basic tests for safety router and webhook idempotency
