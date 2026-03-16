"""
Intent detection tests — tiered emotional classification.

Verifies:
1. Everyday emotions → is_emotional_state() returns True
2. Crisis signals → is_crisis() returns True
3. Everyday emotions do NOT trigger is_crisis()
4. Crisis signals do NOT match is_emotional_state() alone
5. Therapist-intent messages with emotional words route correctly
6. classify_intent() returns the correct Intent for each category

Run with:
    pytest tests/test_intent_detection.py -v
"""
from __future__ import annotations

import pytest

from app.safety import (
    is_crisis,
    is_emotional_state,
    is_prescription_request,
    is_therapist_search,
    classify_intent,
)


# ---------------------------------------------------------------------------
# Everyday emotions → is_emotional_state() == True
# ---------------------------------------------------------------------------

EVERYDAY_EMOTIONS = [
    "I feel anxious",
    "I am feeling anxious",
    "I'm stressed about work",
    "I feel really stressed today",
    "I've been feeling sad lately",
    "I'm so overwhelmed right now",
    "I feel nervous about my presentation",
    "I'm worried about the future",
    "I feel kind of down today",
    "I feel lonely",
    "I'm exhausted and burnt out",
    "I feel frustrated with everything",
    "I can't sleep because of anxiety",
    "I'm having a hard time coping",
]


@pytest.mark.parametrize("message", EVERYDAY_EMOTIONS)
def test_everyday_emotion_detected(message: str) -> None:
    """Everyday emotional states must be detected by is_emotional_state()."""
    assert is_emotional_state(message), (
        f"Emotional state NOT detected for: {message!r}"
    )


@pytest.mark.parametrize("message", EVERYDAY_EMOTIONS)
def test_everyday_emotion_not_crisis(message: str) -> None:
    """Everyday emotional states must NOT trigger crisis detection."""
    assert not is_crisis(message), (
        f"Everyday emotion incorrectly flagged as crisis: {message!r}"
    )


# ---------------------------------------------------------------------------
# Crisis signals → is_crisis() == True
# ---------------------------------------------------------------------------

CRISIS_SIGNALS = [
    "I want to kill myself",
    "I want to die",
    "I'm going to end my life",
    "I am suicidal",
    "I want to hurt myself",
    "I've been thinking about suicide",
    "I can't see a reason to keep going",
    "Life isn't worth living",
    "I'm better off dead",
    "I want to take my own life",
]


@pytest.mark.parametrize("message", CRISIS_SIGNALS)
def test_crisis_signal_detected(message: str) -> None:
    """Crisis signals must be detected by is_crisis()."""
    assert is_crisis(message), (
        f"Crisis NOT detected for: {message!r}"
    )


# ---------------------------------------------------------------------------
# Therapist-intent with emotional keywords → is_emotional_state() == False
# ---------------------------------------------------------------------------

THERAPIST_WITH_EMOTION = [
    "Find a therapist for anxiety near Stockholm",
    "Book a counselor for my depression",
    "I need a clinic for stress near me",
    "Find me a psychiatrist for my anxiety",
    "Schedule an appointment for help with burnout",
]


@pytest.mark.parametrize("message", THERAPIST_WITH_EMOTION)
def test_therapist_intent_overrides_emotional_state(message: str) -> None:
    """Messages with therapist/booking intent should NOT be intercepted by is_emotional_state()."""
    assert not is_emotional_state(message), (
        f"Therapist-intent message incorrectly flagged as emotional state: {message!r}"
    )


# ---------------------------------------------------------------------------
# classify_intent() — correct classification
# ---------------------------------------------------------------------------

INTENT_CASES = [
    ("I want to kill myself", "crisis"),
    ("I feel anxious", "emotional_state"),
    ("Find a therapist near Stockholm", "therapist_search"),
    ("I need some breathing exercises", "default"),
    ("hello", "default"),
]


@pytest.mark.parametrize("message,expected_intent", INTENT_CASES)
def test_classify_intent(message: str, expected_intent: str) -> None:
    """classify_intent() must return the correct Intent for each category."""
    result = classify_intent(message)
    assert result == expected_intent, (
        f"classify_intent({message!r}) = {result!r}, expected {expected_intent!r}"
    )


# ---------------------------------------------------------------------------
# Prescription detection
# ---------------------------------------------------------------------------

PRESCRIPTION_MESSAGES = [
    "Can you prescribe me something for anxiety?",
    "What medication should I take?",
    "Is 50mg of sertraline enough?",
    "Should I take Xanax for my panic attacks?",
]


@pytest.mark.parametrize("message", PRESCRIPTION_MESSAGES)
def test_prescription_detected(message: str) -> None:
    """Prescription-related messages must be detected."""
    assert is_prescription_request(message), (
        f"Prescription NOT detected for: {message!r}"
    )


# ---------------------------------------------------------------------------
# Therapist search detection
# ---------------------------------------------------------------------------

THERAPIST_SEARCH_MESSAGES = [
    "Find a therapist near me",
    "Find me a therapist in Malmö",
    "Book a therapist for anxiety",
    "Therapist near Stockholm",
]


@pytest.mark.parametrize("message", THERAPIST_SEARCH_MESSAGES)
def test_therapist_search_detected(message: str) -> None:
    """Therapist search messages must be detected."""
    assert is_therapist_search(message), (
        f"Therapist search NOT detected for: {message!r}"
    )
