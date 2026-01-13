# Mental Health Skills Coach (Portfolio Project)

## Run locally (Docker)
1) Install Docker Desktop
2) From repo root:
   docker compose up --build

Expected:
- Frontend: http://localhost:3000
- Backend:  http://localhost:8000
- MCP:      http://localhost:7000

## Notes
- No chat history is stored (by design).
- This is a skills coach, not therapy/medical advice.

## Run backend tests (Docker)
From the repo root:
```
docker compose up -d --build
docker compose exec backend python -m pytest -q
docker compose down
```
