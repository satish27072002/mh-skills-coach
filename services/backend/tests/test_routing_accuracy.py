"""
Routing accuracy tests — 40+ cases, target ≥ 90% accuracy.

Tests the ChatRouter directly (no LLM, no DB) using RouterInput.
Each case asserts the expected route: COACH, THERAPIST_SEARCH, or BOOKING_EMAIL.

Run with:
    pytest tests/test_routing_accuracy.py -v
"""
from __future__ import annotations

import pytest

from app.agents.router import ChatRouter, RouterInput


# ---------------------------------------------------------------------------
# Test case definitions
# ---------------------------------------------------------------------------

# Format: (message, has_pending_booking, has_pending_therapist_location, expected_route)
ROUTING_CASES: list[tuple[str, bool, bool, str]] = [
    # ── COACH cases ─────────────────────────────────────────────────────────
    ("I feel anxious about my job interview", False, False, "COACH"),
    ("I've been really stressed lately", False, False, "COACH"),
    ("Can you help me with breathing exercises?", False, False, "COACH"),
    ("I'm feeling overwhelmed and don't know what to do", False, False, "COACH"),
    ("Teach me a grounding technique", False, False, "COACH"),
    ("I can't sleep because of my anxiety", False, False, "COACH"),
    ("I'm feeling very down today", False, False, "COACH"),
    ("Help me calm down, I'm panicking", False, False, "COACH"),
    ("What is box breathing?", False, False, "COACH"),
    ("I need to learn some coping skills", False, False, "COACH"),
    ("I'm going through a hard time and need support", False, False, "COACH"),
    ("How can I manage my anger better?", False, False, "COACH"),
    ("I feel lonely and disconnected", False, False, "COACH"),
    ("I'm burnt out from work", False, False, "COACH"),
    ("Can you guide me through a meditation?", False, False, "COACH"),
    ("I've been having panic attacks", False, False, "COACH"),
    ("Tell me about mindfulness techniques", False, False, "COACH"),
    ("I'm nervous about a big presentation tomorrow", False, False, "COACH"),
    ("I feel so exhausted all the time", False, False, "COACH"),
    ("How do I practice 5-4-3-2-1 grounding?", False, False, "COACH"),

    # ── THERAPIST_SEARCH cases ───────────────────────────────────────────────
    ("Find a therapist near me in Stockholm", False, False, "THERAPIST_SEARCH"),
    ("Find therapists near Gothenburg", False, False, "THERAPIST_SEARCH"),
    ("I need a therapist near me", False, False, "THERAPIST_SEARCH"),
    ("Are there any mental health clinics near Uppsala?", False, False, "THERAPIST_SEARCH"),
    ("Find me a counselor close to Malmö", False, False, "THERAPIST_SEARCH"),
    ("I'm looking for a psychiatrist in Lund", False, False, "THERAPIST_SEARCH"),
    ("Search for therapist near Västerås", False, False, "THERAPIST_SEARCH"),
    ("Find a therapist near Stockholm for anxiety", False, False, "THERAPIST_SEARCH"),
    ("Are there any BUP clinics near me?", False, False, "THERAPIST_SEARCH"),
    ("I need a mottagning near Örebro", False, False, "THERAPIST_SEARCH"),

    # ── BOOKING_EMAIL cases ──────────────────────────────────────────────────
    ("Send an email to dr.anna@example.com to book an appointment", False, False, "BOOKING_EMAIL"),
    ("I want to book an appointment with a therapist", False, False, "BOOKING_EMAIL"),
    ("Can you draft an email to schedule a session?", False, False, "BOOKING_EMAIL"),
    ("Email the clinic for me", False, False, "BOOKING_EMAIL"),
    ("I'd like to schedule an appointment", False, False, "BOOKING_EMAIL"),
    ("Book a session with therapist@example.com", False, False, "BOOKING_EMAIL"),
    ("Help me contact a therapist via email", False, False, "BOOKING_EMAIL"),
    ("Send appointment request to info@mindler.se", False, False, "BOOKING_EMAIL"),
    ("I want to send an email to book with a counselor", False, False, "BOOKING_EMAIL"),
    ("Draft a booking email to the clinic", False, False, "BOOKING_EMAIL"),

    # ── Pending booking always → BOOKING_EMAIL ───────────────────────────────
    ("Yes, please send it", True, False, "BOOKING_EMAIL"),
    ("Confirmed", True, False, "BOOKING_EMAIL"),
    ("Go ahead", True, False, "BOOKING_EMAIL"),

    # ── Pending therapist location reply → THERAPIST_SEARCH ─────────────────
    ("Stockholm", False, True, "THERAPIST_SEARCH"),
    ("Gothenburg", False, True, "THERAPIST_SEARCH"),
    ("Uppsala", False, True, "THERAPIST_SEARCH"),
]


# ---------------------------------------------------------------------------
# Parametrized accuracy test
# ---------------------------------------------------------------------------

router = ChatRouter()


@pytest.mark.parametrize(
    "message,has_pending_booking,has_pending_therapist_location,expected",
    ROUTING_CASES,
    ids=[f"[{i:02d}] {case[0][:50]}" for i, case in enumerate(ROUTING_CASES)],
)
def test_route(
    message: str,
    has_pending_booking: bool,
    has_pending_therapist_location: bool,
    expected: str,
) -> None:
    """Assert each message routes to the expected agent."""
    result = router.route(
        RouterInput(
            message=message,
            has_pending_booking=has_pending_booking,
            has_pending_therapist_location=has_pending_therapist_location,
        )
    )
    assert result == expected, (
        f"\nMessage: {message!r}\n"
        f"Expected: {expected!r}\n"
        f"Got:      {result!r}"
    )


# ---------------------------------------------------------------------------
# Aggregate accuracy assertion — must be ≥ 90%
# ---------------------------------------------------------------------------

def test_routing_accuracy_above_90_percent() -> None:
    """Run all cases and assert overall accuracy ≥ 90%."""
    correct = 0
    total = len(ROUTING_CASES)
    failures: list[str] = []

    for message, has_pending_booking, has_pending_therapist_location, expected in ROUTING_CASES:
        result = router.route(
            RouterInput(
                message=message,
                has_pending_booking=has_pending_booking,
                has_pending_therapist_location=has_pending_therapist_location,
            )
        )
        if result == expected:
            correct += 1
        else:
            failures.append(
                f"  ✗ {message!r}: expected {expected!r}, got {result!r}"
            )

    accuracy = correct / total
    print(f"\n{'='*60}")
    print(f"Routing accuracy: {correct}/{total} = {accuracy:.1%}")
    if failures:
        print("Failures:")
        for f in failures:
            print(f)
    print(f"{'='*60}")

    assert accuracy >= 0.90, (
        f"Routing accuracy {accuracy:.1%} is below the 90% threshold.\n"
        + "\n".join(failures)
    )


# ---------------------------------------------------------------------------
# Spot-checks for edge cases
# ---------------------------------------------------------------------------

def test_confirmation_message_with_pending_booking_routes_to_booking() -> None:
    result = router.route(RouterInput(
        message="yes",
        has_pending_booking=True,
        has_pending_therapist_location=False,
    ))
    assert result == "BOOKING_EMAIL"


def test_location_reply_with_pending_therapist_location() -> None:
    result = router.route(RouterInput(
        message="Malmö",
        has_pending_booking=False,
        has_pending_therapist_location=True,
    ))
    assert result == "THERAPIST_SEARCH"


def test_no_pending_state_defaults_to_coach() -> None:
    result = router.route(RouterInput(
        message="Hello, I need some help",
        has_pending_booking=False,
        has_pending_therapist_location=False,
    ))
    assert result == "COACH"


def test_email_address_in_message_routes_to_booking() -> None:
    result = router.route(RouterInput(
        message="Please email dr.smith@clinic.se to set up a meeting",
        has_pending_booking=False,
        has_pending_therapist_location=False,
    ))
    assert result == "BOOKING_EMAIL"


def test_therapist_search_with_emotional_context_routes_to_therapist() -> None:
    """Therapist search messages with emotional context should still go to THERAPIST_SEARCH."""
    result = router.route(RouterInput(
        message="Find therapists near Stockholm for anxiety",
        has_pending_booking=False,
        has_pending_therapist_location=False,
    ))
    assert result == "THERAPIST_SEARCH"
