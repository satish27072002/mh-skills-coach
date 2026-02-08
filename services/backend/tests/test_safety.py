import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./test.db"

from app.safety import route_message


def test_crisis_routing():
    response = route_message("I want to end my life")
    assert "112" in response.coach_message
    assert response.premium_cta is None
    assert response.risk_level == "crisis"


def test_medical_refusal():
    response = route_message("Can you give me a diagnosis?")
    assert response.premium_cta is not None
    assert response.premium_cta.enabled is True
    assert "Premium" in response.premium_cta.message
    assert "beyond my capability" in response.coach_message
    assert "prescriptions" in response.coach_message
    assert "clinician" in response.coach_message
    assert any("mindler.se" in resource.url for resource in response.resources or [])
    assert response.risk_level == "crisis"


def test_default_exercise():
    response = route_message("I feel anxious")
    assert response.exercise is not None
    assert response.exercise.duration_seconds > 0
