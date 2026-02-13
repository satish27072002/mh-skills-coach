from __future__ import annotations

from fastapi import HTTPException, Request

from app.models import User
from app.safety import is_crisis
from app.schemas import ChatResponse

from .therapist_agent import TherapistSearchAgent


class SafetyGate:
    def __init__(self, *, therapist_agent: TherapistSearchAgent):
        self._therapist_agent = therapist_agent

    def handle(self, *, user: User | None, request: Request, message: str) -> ChatResponse | None:
        if not is_crisis(message):
            return None

        parsed = self._therapist_agent.parse_message(message)
        location = parsed.location_text or self._therapist_agent.get_remembered_location(user=user, request=request)

        therapists = None
        search_available = self._therapist_agent.dev_mode or bool(user and user.is_premium)
        if location and search_available:
            try:
                therapists, _ = self._therapist_agent.search_with_retries(
                    location_text=location,
                    radius_km=parsed.radius_km,
                    specialty=parsed.specialty,
                )
                if therapists:
                    self._therapist_agent.remember_location(user=user, request=request, location=location)
            except HTTPException:
                therapists = None

        if therapists:
            search_hint = "I have also included nearby providers below in case contacting one feels possible."
        elif location:
            search_hint = "If you want, I can keep helping you find nearby providers in the app."
        else:
            search_hint = (
                "If you share your city or postcode, I can help find nearby therapists/clinics in the app."
            )

        return ChatResponse(
            coach_message=(
                "I am really sorry you are feeling this way. You deserve immediate support right now. "
                "If you are in immediate danger or think you might act on these thoughts, call emergency services now "
                "(in Sweden: 112). You can also contact Mind Självmordslinjen (90101) for urgent support, and 1177 "
                "Vårdguiden for healthcare guidance. If you are outside Sweden, please call your local emergency number "
                "or local crisis hotline now. "
                f"{search_hint}"
            ),
            resources=[
                {
                    "title": "Emergency services (Sweden) - 112",
                    "url": "https://www.112.se/",
                },
                {
                    "title": "Mind Självmordslinjen (90101)",
                    "url": "https://mind.se/hitta-hjalp/sjalvmordslinjen/",
                },
                {
                    "title": "1177 Vårdguiden",
                    "url": "https://www.1177.se/",
                },
                {
                    "title": "Find an international crisis line",
                    "url": "https://www.opencounseling.com/suicide-hotlines",
                },
            ],
            therapists=therapists,
            risk_level="crisis",
            premium_cta=None,
        )
