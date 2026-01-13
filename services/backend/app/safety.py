from .schemas import ChatResponse, Exercise, PremiumCta, Resource


CRISIS_KEYWORDS = [
    "suicide",
    "kill myself",
    "self-harm",
    "hurt myself",
    "end my life",
    "ending my life",
    "harm myself"
]

MEDICAL_KEYWORDS = [
    "diagnosis",
    "diagnose",
    "prescription",
    "medication",
    "meds",
    "antidepressant",
    "ssri",
    "adhd",
    "bipolar"
]


def _contains_any(message: str, keywords: list[str]) -> bool:
    message_lower = message.lower()
    return any(keyword in message_lower for keyword in keywords)


def is_crisis(message: str) -> bool:
    return _contains_any(message, CRISIS_KEYWORDS)


def is_medical_request(message: str) -> bool:
    return _contains_any(message, MEDICAL_KEYWORDS)


def route_message(message: str) -> ChatResponse:
    if is_crisis(message):
        return ChatResponse(
            coach_message=(
                "I am really sorry you are feeling this way. If you are in immediate danger, "
                "please call your local emergency number right now. In Sweden, call 112 for emergencies. "
                "If you can, reach out to someone you trust and let them know you need support."
            ),
            resources=[
                Resource(title="Emergency services (Sweden)", url="https://www.112.se/"),
                Resource(title="Find local crisis lines", url="https://www.iasp.info/resources/Crisis_Centres/")
            ]
        )

    if is_medical_request(message):
        return ChatResponse(
            coach_message=(
                "This is beyond my capability. I cannot provide diagnosis, prescriptions, or medication advice. "
                "A licensed professional can help you with that."
            ),
            resources=[
                Resource(title="Find a licensed professional", url="https://www.psychologytoday.com/"),
                Resource(title="Therapy platforms", url="https://www.betterhelp.com/")
            ],
            premium_cta=PremiumCta(
                enabled=True,
                message="If you want extra coaching programs and guided skills, premium unlocks that."
            )
        )

    return ChatResponse(
        coach_message=(
            "Thanks for sharing. Let us slow things down together. Here is a short grounding exercise to try."
        ),
        exercise=Exercise(
            type="5-4-3-2-1 grounding",
            steps=[
                "Name 5 things you can see.",
                "Name 4 things you can feel.",
                "Name 3 things you can hear.",
                "Name 2 things you can smell.",
                "Name 1 thing you can taste."
            ],
            duration_seconds=90
        )
    )
