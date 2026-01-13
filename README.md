# Mental Health Skills Coach (Portfolio Project)

## Run locally
From the repo root:
```
docker compose up --build
```
URLs:
- Frontend: http://localhost:3000
- Backend:  http://localhost:8000
- MCP:      http://localhost:7000

## Run tests
From the repo root:
```
docker compose up -d --build
docker compose exec backend python -m pytest -q
docker compose down
```

## Google login (local)
Set these env vars (backend):
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- GOOGLE_REDIRECT_URI (default: http://localhost:8000/auth/google/callback)
- FRONTEND_URL (default: http://localhost:3000)

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
