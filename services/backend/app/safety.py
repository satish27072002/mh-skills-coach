import re
from typing import Literal, Tuple

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

ADDITIONAL_CRISIS_KEYWORDS = [
    "i want to kill myself",
    "i will kill myself",
    "i'm going to kill myself",
    "i am going to kill myself",
    "i will end my life",
    "i'm going to end my life",
    "i am going to end my life",
    "i want to end my life",
    "i will hurt myself",
    "i'm going to hurt myself",
    "i am going to hurt myself",
]

# Merge with stable order and without duplicates.
CRISIS_KEYWORDS = list(dict.fromkeys([*CRISIS_KEYWORDS, *ADDITIONAL_CRISIS_KEYWORDS]))

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

MEDICAL_ADVICE_OUTPUT_KEYWORDS = [
    "take ",
    "dosage",
    "dose",
    "mg",
    "tablet",
    "capsule",
    "prescribe",
    "prescription",
    "medication",
    "medicine",
    "ssri",
    "benzodiazepine",
    "xanax",
    "sertraline",
    "fluoxetine",
]

JAILBREAK_PATTERNS = [
    r"\bignore (all|any|previous|prior) (instructions|rules|policy)\b",
    r"\boverride (the )?(system|safety|policy|rules)\b",
    r"\breveal (the )?(system prompt|prompt|hidden prompt)\b",
    r"\bjailbreak\b",
    r"\bdeveloper mode\b",
    r"\bdo anything now\b",
    r"\byou are now (chatgpt|dan|unrestricted)\b",
]


def _contains_any(message: str, keywords: list[str]) -> bool:
    message_lower = message.lower()
    return any(keyword in message_lower for keyword in keywords)


def contains_jailbreak_attempt(message: str) -> bool:
    text = message.lower()
    return any(re.search(pattern, text) for pattern in JAILBREAK_PATTERNS)


def contains_medical_advice(text: str) -> bool:
    return _contains_any(text, MEDICAL_ADVICE_OUTPUT_KEYWORDS)


def filter_unsafe_response(response: ChatResponse) -> ChatResponse:
    if not response or not response.coach_message:
        return response
    unsafe = contains_jailbreak_attempt(response.coach_message) or contains_medical_advice(response.coach_message)
    if not unsafe:
        return response

    safe_resources = response.resources or [
        Resource(title="Healthcare advice (Sweden)", url="https://www.1177.se/"),
        Resource(title="Emergency services (Sweden)", url="https://www.112.se/"),
    ]
    return ChatResponse(
        coach_message=(
            "I can’t help with unsafe instructions or medical treatment advice. "
            "I can help with coping skills and suggest contacting a licensed clinician for medical decisions."
        ),
        resources=safe_resources,
        premium_cta=response.premium_cta,
        risk_level=response.risk_level,
    )


def assess_conversation_risk(conversation_history: list[dict[str, str]]) -> Tuple[str, str | None]:
    if not conversation_history:
        return "normal", None
    # Prioritize the latest user messages.
    for turn in reversed(conversation_history):
        text = (turn.get("content") or "").strip()
        if not text:
            continue
        if contains_jailbreak_attempt(text):
            return "jailbreak", text
        if is_crisis(text):
            return "crisis", text
        if is_prescription_request(text):
            return "medical", text
    return "normal", None


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
