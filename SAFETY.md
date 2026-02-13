# Safety Policy

## Positioning
MH Skills Coach is a mental-health support and navigation app.  
It is **not** a medical service and does **not** replace licensed professional care.

## Core Guardrails
- No diagnosis.
- No prescriptions or medication instructions.
- No clinical treatment claims.

If a user asks for diagnosis/prescription/medication guidance, the app responds with refusal language and directs the user to licensed care/resources.

## Crisis / Self-Harm Handling
If user text indicates self-harm or suicide risk (for example: “I want to die”, “kill myself”), chat flow is interrupted by a safety gate.

Expected behavior:
- Return a supportive, non-judgmental crisis response.
- Recommend immediate emergency help (local emergency number).
- Include helpline guidance (including Sweden-specific references used by the app).
- Do not continue normal coaching/booking flow in that turn.
- When appropriate, include therapist search suggestions/results as a safer next action.

## How Safety Is Enforced in Code
- `POST /chat` runs `SafetyGate` before normal routing.
- `SafetyGate` checks crisis intent and short-circuits to a crisis-safe response.
- Prescription/diagnosis requests are routed to refusal messaging.
- Router/agent flow prevents unsafe branch execution after crisis gating.

## Verification
Safety behavior is covered by backend tests, including:
- `services/backend/tests/test_crisis_guardrail.py`
- `services/backend/tests/test_safety.py`
- `services/backend/tests/test_chat_prescription.py`

## Privacy Notes
- Local development uses local Docker services (frontend/backend/mcp/postgres).
- Do not commit secrets or real credentials; use `.env` with placeholders from `.env.example`.
- Keep logs and stored data minimal and aligned with safety/privacy goals.
