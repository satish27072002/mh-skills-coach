from typing import Literal

from .schemas import ChatResponse, Exercise, PremiumCta, Resource


CRISIS_KEYWORDS = [
    "suicide",
    "kill myself",
    "self-harm",
    "hurt myself",
    "end my life",
    "ending my life",
    "harm myself",
    "suicidal",
    "i want to die",
    "want to die",
    "end it all",
    "can't go on",
    "cannot go on",
    "life isn't worth living"
]

THERAPIST_SEARCH_KEYWORDS = [
    "find therapist",
    "find a therapist",
    "therapist near me",
    "book therapist",
    "book a therapist",
    "counsellor near me",
    "counselor near me",
    "find me a therapist"
]

PRESCRIPTION_KEYWORDS = [
    "prescribe",
    "prescription",
    "medication",
    "medicine",
    "meds",
    "mg",
    "pill",
    "pills",
    "tablet",
    "capsule",
    "dose",
    "dosage",
    "side effect",
    "side effects",
    "withdrawal",
    "taper",
    "tapering",
    "overdose",
    "antidepressant",
    "ssri",
    "benzodiazepine",
    "benzo",
    "xanax",
    "diazepam",
    "prozac",
    "sertraline",
    "zoloft",
    "citalopram",
    "escitalopram",
    "fluoxetine",
    "venlafaxine",
    "duloxetine",
    "sleeping pill",
    "sleeping pills",
    "painkiller",
    "ibuprofen",
    "paracetamol",
    "acetaminophen",
    "antibiotic",
    "opioid",
    "adderall",
    "ritalin",
    "vyvanse",
    "diagnosis",
    "diagnose"
]


def _contains_any(message: str, keywords: list[str]) -> bool:
    message_lower = message.lower()
    return any(keyword in message_lower for keyword in keywords)


def is_crisis(message: str) -> bool:
    return _contains_any(message, CRISIS_KEYWORDS)


def is_therapist_search(message: str) -> bool:
    if _contains_any(message, THERAPIST_SEARCH_KEYWORDS):
        return True
    message_lower = message.lower()
    has_term = any(term in message_lower for term in ["therapist", "counselor", "counsellor"])
    has_intent = any(term in message_lower for term in ["find", "near me", "book", "search"])
    return has_term and has_intent


def is_prescription_request(message: str) -> bool:
    return _contains_any(message, PRESCRIPTION_KEYWORDS)


Intent = Literal["crisis", "therapist_search", "prescription", "default"]


def classify_intent(message: str) -> Intent:
    if is_crisis(message):
        return "crisis"
    if is_therapist_search(message):
        return "therapist_search"
    if is_prescription_request(message):
        return "prescription"
    return "default"


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
            ],
            risk_level="crisis"
        )

    if is_prescription_request(message):
        return ChatResponse(
            coach_message=(
                "This is beyond my capability. I can't help with prescriptions, dosing, or medication changes. "
                "Please contact a licensed clinician or pharmacist. If you think you may be in danger "
                "(e.g., overdose, severe reaction), call your local emergency number now (Sweden: 112)."
            ),
            resources=[
                Resource(title="Emergency services (Sweden)", url="https://www.112.se/"),
                Resource(title="Healthcare advice (Sweden)", url="https://www.1177.se/"),
                Resource(title="Mindler", url="https://www.mindler.se/"),
                Resource(title="Kry", url="https://www.kry.se/"),
                Resource(title="Psychology Today", url="https://www.psychologytoday.com/")
            ],
            premium_cta=PremiumCta(
                enabled=True,
                message="Premium unlocks extra coaching features and therapist directory access."
            ),
            risk_level="crisis"
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
