import re
from typing import Literal, Tuple

from .schemas import ChatResponse, Exercise, PremiumCta, Resource


# ---------------------------------------------------------------------------
# CRISIS keywords — genuine acute risk ONLY.
# These must indicate intent to harm or end life.
# DO NOT add generic emotions like "anxious", "stressed", "sad" here.
# ---------------------------------------------------------------------------
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
    "life isn't worth living",
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
    "no reason to live",
    "not worth living",
    "better off dead",
    "take my own life",
    "taking my own life",
]

# Stable order, no duplicates
CRISIS_KEYWORDS = list(dict.fromkeys(CRISIS_KEYWORDS))

# ---------------------------------------------------------------------------
# EMOTIONAL STATE keywords — everyday feelings that route to COACH for
# coping exercises. NOT crisis. NOT emergency numbers.
# ---------------------------------------------------------------------------
EMOTIONAL_STATE_KEYWORDS = [
    "anxious",
    "anxiety",
    "stressed",
    "stress",
    "stressful",
    "worried",
    "worry",
    "overwhelmed",
    "nervous",
    "scared",
    "panicking",
    "panic attack",
    "panic",
    "sad",
    "sadness",
    "depressed",
    "depression",
    "feeling down",
    "feeling low",
    "feel low",
    "feel down",
    "unhappy",
    "upset",
    "frustrated",
    "exhausted",
    "burnt out",
    "burnout",
    "tired",
    "hopeless",
    "helpless",
    "lonely",
    "alone",
    "afraid",
    "fearful",
    "tense",
    "irritable",
    "irritated",
    "angry",
    "anger",
    "can't cope",
    "cannot cope",
    "can't sleep",
    "cannot sleep",
    "trouble sleeping",
    "sleep problems",
    "feeling anxious",
    "feeling stressed",
    "feeling nervous",
    "feeling overwhelmed",
    "feeling sad",
    "i feel anxious",
    "i am anxious",
    "i feel stressed",
    "i am stressed",
    "i feel sad",
    "i am sad",
    "i feel depressed",
    "really stressed",
    "so stressed",
    "very anxious",
    "quite anxious",
    "low mood",
    "bad mood",
    "not feeling well",
    "not feeling great",
    "down today",
    "having a hard time",
    "going through a hard time",
    "going through a tough time",
    "tough day",
    "hard day",
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

# ---------------------------------------------------------------------------
# JAILBREAK patterns — expanded with 20+ patterns
# ---------------------------------------------------------------------------
JAILBREAK_PATTERNS = [
    r"\bignore (all|any|previous|prior) (instructions|rules|policy|guidelines)\b",
    r"\boverride (the )?(system|safety|policy|rules|guidelines)\b",
    r"\breveal (the )?(system prompt|prompt|hidden prompt|instructions)\b",
    r"\bjailbreak\b",
    r"\bdeveloper mode\b",
    r"\bdo anything now\b",
    r"\byou are now (chatgpt|dan|unrestricted|free|unfiltered|uncensored)\b",
    r"\bact as (a|an)? (unrestricted|unfiltered|uncensored|evil|dangerous)\b",
    r"\bpretend (you are|to be) (a|an)? ?(general|unrestricted|free|evil|dangerous|different)\b",
    r"\bforget (all|your|every|the) (rules|instructions|guidelines|training|constraints|limits)\b",
    r"\byou have no (rules|restrictions|limits|guidelines|constraints)\b",
    r"\bno (rules|restrictions|limits|guidelines|constraints) apply\b",
    r"\bdisregard (all|any|your|previous|prior) (instructions|rules|policy|guidelines|safety)\b",
    r"\bbypass (the )?(safety|filter|guardrail|restriction|rule|policy)\b",
    r"\bstop being (a|an)? ?(assistant|coach|bot|ai|mental health)\b",
    r"\byou are (not|no longer) (bound by|restricted by|limited by|following)\b",
    r"\bswitch (to|into) (unrestricted|developer|admin|god|evil) mode\b",
    r"\bprompt injection\b",
    r"\bsystem: (ignore|override|forget|bypass)\b",
    r"\bhuman: (ignore|override|forget|bypass)\b",
    r"\bassistant: (ignore|override|forget|bypass)\b",
    r"\bhelp me (hack|exploit|break|bypass|jailbreak)\b",
    r"\bwrite (me )?(malware|a virus|ransomware|exploit code)\b",
    r"\bact as if (you have|there are) no (restrictions|rules|guidelines|limits)\b",
    r"\bimagine you (have no|are without) (restrictions|rules|guidelines|constraints)\b",
]

# ---------------------------------------------------------------------------
# SCOPE: topics the app handles. Used by scope_check().
# ---------------------------------------------------------------------------
IN_SCOPE_KEYWORDS = [
    # Emotional / mental health topics → COACH
    "anxious", "anxiety", "stress", "stressed", "worried", "worry",
    "overwhelmed", "nervous", "panic", "sad", "sadness", "depressed",
    "depression", "mood", "lonely", "alone", "afraid", "fear", "anger",
    "angry", "frustrated", "exhausted", "burnout", "sleep", "coping",
    "cope", "exercise", "breathing", "grounding", "relax", "calm",
    "mindfulness", "meditation", "feel", "feeling", "emotion", "mental health",
    "wellbeing", "well-being", "therapy", "support", "help me",
    # Therapist search → THERAPIST_SEARCH
    "therapist", "counselor", "counsellor", "psychiatrist", "psychologist",
    "clinic", "provider", "near me", "find", "search", "book",
    # Booking → BOOKING_EMAIL
    "appointment", "email", "schedule", "booking", "contact",
]


def _contains_any(message: str, keywords: list[str]) -> bool:
    message_lower = message.lower()
    return any(keyword in message_lower for keyword in keywords)


def contains_jailbreak_attempt(message: str) -> bool:
    text = message.lower()
    return any(re.search(pattern, text) for pattern in JAILBREAK_PATTERNS)


def contains_medical_advice(text: str) -> bool:
    return _contains_any(text, MEDICAL_ADVICE_OUTPUT_KEYWORDS)


def is_crisis(message: str) -> bool:
    """True only for genuine acute crisis signals. NOT everyday emotions."""
    return _contains_any(message, CRISIS_KEYWORDS)


def is_emotional_state(message: str) -> bool:
    """True for everyday emotional states (anxious, stressed, sad, etc.)
    that should route to COACH for coping exercises — not crisis escalation."""
    return _contains_any(message, EMOTIONAL_STATE_KEYWORDS)


def scope_check(message: str) -> bool:
    """Returns True if the message is within the app's scope.
    Returns False if the user is asking for something completely unrelated
    (e.g. coding help, news, general knowledge, etc.)."""
    # Always in-scope: anything that looks like mental health / therapy / booking
    if _contains_any(message, IN_SCOPE_KEYWORDS):
        return True
    # Very short messages (greetings, affirmations) are in scope
    if len(message.strip().split()) <= 4:
        return True
    # Questions about the user's own feelings are in scope
    lower = message.lower()
    if any(phrase in lower for phrase in ["i feel", "i am feeling", "i'm feeling", "feeling", "help me"]):
        return True
    return False


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
            "I can't help with unsafe instructions or medical treatment advice. "
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


def is_therapist_search(message: str) -> bool:
    if _contains_any(message, THERAPIST_SEARCH_KEYWORDS):
        return True
    message_lower = message.lower()
    has_term = any(term in message_lower for term in ["therapist", "counselor", "counsellor"])
    has_intent = any(term in message_lower for term in ["find", "near me", "book", "search"])
    return has_term and has_intent


def is_prescription_request(message: str) -> bool:
    return _contains_any(message, PRESCRIPTION_KEYWORDS)


Intent = Literal["crisis", "emotional_state", "therapist_search", "prescription", "default"]


def classify_intent(message: str) -> Intent:
    """Tiered classification:
    1. Crisis (acute risk) → crisis response + emergency numbers
    2. Emotional state (everyday feelings) → COACH for coping exercises
    3. Therapist search → THERAPIST_SEARCH agent
    4. Prescription request → blocked
    5. Default → COACH
    """
    if is_crisis(message):
        return "crisis"
    if is_therapist_search(message):
        return "therapist_search"
    if is_prescription_request(message):
        return "prescription"
    if is_emotional_state(message):
        return "emotional_state"
    return "default"


def emotional_state_coach_response(message: str) -> ChatResponse:
    """Return a warm coaching response with coping exercises for everyday emotions."""
    lower = message.lower()

    # Pick a relevant exercise based on the emotion
    if any(w in lower for w in ["panic", "panicking", "panic attack"]):
        exercise = Exercise(
            type="Box Breathing (4-4-4-4)",
            steps=[
                "Breathe in slowly through your nose for 4 counts.",
                "Hold your breath for 4 counts.",
                "Breathe out slowly through your mouth for 4 counts.",
                "Hold for 4 counts. Repeat 4–6 times.",
            ],
            duration_seconds=120,
        )
        intro = "It sounds like you're experiencing a panic attack. Let's try box breathing to calm your nervous system."
    elif any(w in lower for w in ["anxious", "anxiety", "nervous", "worried", "afraid", "fearful"]):
        exercise = Exercise(
            type="4-7-8 Breathing",
            steps=[
                "Breathe in through your nose for 4 counts.",
                "Hold your breath for 7 counts.",
                "Breathe out through your mouth for 8 counts.",
                "Repeat 3–4 times.",
            ],
            duration_seconds=90,
        )
        intro = "Feeling anxious is really tough. Let's try 4-7-8 breathing — it activates your body's calming response."
    elif any(w in lower for w in ["overwhelmed", "stressed", "stress", "burnout", "burnt out", "exhausted"]):
        exercise = Exercise(
            type="5-4-3-2-1 Grounding",
            steps=[
                "Name 5 things you can see right now.",
                "Name 4 things you can physically feel (e.g. feet on floor, air on skin).",
                "Name 3 things you can hear.",
                "Name 2 things you can smell.",
                "Name 1 thing you can taste.",
            ],
            duration_seconds=90,
        )
        intro = "It sounds like you're feeling overwhelmed. Let's ground you in the present moment with this quick exercise."
    elif any(w in lower for w in ["sad", "sadness", "depressed", "depression", "unhappy", "down", "hopeless", "lonely"]):
        exercise = Exercise(
            type="Gratitude & Self-Compassion Pause",
            steps=[
                "Place one hand on your heart and take a slow breath.",
                "Acknowledge: 'I am having a hard time right now, and that's okay.'",
                "Name one small thing that went okay today — even something tiny.",
                "Take 3 slow, deep breaths before continuing your day.",
            ],
            duration_seconds=120,
        )
        intro = "I hear you — feeling sad or low is hard. Let's try a short self-compassion exercise together."
    else:
        exercise = Exercise(
            type="5-4-3-2-1 Grounding",
            steps=[
                "Name 5 things you can see.",
                "Name 4 things you can feel.",
                "Name 3 things you can hear.",
                "Name 2 things you can smell.",
                "Name 1 thing you can taste.",
            ],
            duration_seconds=90,
        )
        intro = "Thanks for sharing how you're feeling. Let's try a grounding exercise to help you feel more settled."

    return ChatResponse(
        coach_message=(
            f"{intro}\n\n"
            "After trying this, feel free to share how it went — I'm here to help you work through this."
        ),
        exercise=exercise,
        risk_level="normal",
    )


def route_message(message: str) -> ChatResponse:
    if is_crisis(message):
        return ChatResponse(
            coach_message=(
                "I am really glad you reached out. Please seek immediate support right now. "
                "If you might act on these thoughts or are in immediate danger, call 112 immediately. "
                "You can also contact Mind Självmordslinjen at 90101 (chat/phone) for urgent emotional support, "
                "and use 1177 Vårdguiden for healthcare guidance and where to get care."
            ),
            resources=[
                Resource(title="Emergency services (Sweden) - 112", url="https://www.112.se/"),
                Resource(title="Mind Självmordslinjen - 90101", url="https://mind.se/hitta-hjalp/sjalvmordslinjen/"),
                Resource(title="1177 Vårdguiden", url="https://www.1177.se/"),
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

    # Emotional states → coping exercises
    if is_emotional_state(message):
        return emotional_state_coach_response(message)

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
