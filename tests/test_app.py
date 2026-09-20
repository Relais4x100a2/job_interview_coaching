"""Tests for the multi-interview API."""
from io import BytesIO
from unittest.mock import patch

import pytest
from app import create_app

FAKE_AUDIO = b"\x00" * 500
FAKE_FRAME = b"\xff\xd8\xff\xe0" + b"\x00" * 100


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _create_offer(client):
    resp = client.post("/api/sessions", json={"cv": "Mon CV", "job_offer": "Offre Python"})
    assert resp.status_code == 200
    return resp.get_json()


def _add_interview(client, session_id, context="Screening RH", language="fr"):
    with patch("services.ai_service.generate_questions", return_value=["Présentez-vous.", "Q2"]):
        resp = client.post(
            f"/api/sessions/{session_id}/interviews",
            json={"context": context, "language": language},
        )
        assert resp.status_code == 200
        return resp.get_json()


def test_create_offer(client):
    data = _create_offer(client)
    assert "session_id" in data
    assert "offer_title" in data


def test_create_offer_missing_cv(client):
    resp = client.post("/api/sessions", json={"job_offer": "Offre"})
    assert resp.status_code == 400


def test_add_interview(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])
    assert "interview_id" in itw
    assert itw["context"] == "Screening RH"
    assert itw["language"] == "fr"
    assert len(itw["questions"]) == 2


def test_add_interview_unknown_session(client):
    with patch("services.ai_service.generate_questions", return_value=["Q1"]):
        resp = client.post(
            "/api/sessions/unknown/interviews",
            json={"context": "RH", "language": "fr"},
        )
    assert resp.status_code == 404


def test_get_session_detail_with_interviews(client):
    offer = _create_offer(client)
    _add_interview(client, offer["session_id"], "RH", "fr")
    _add_interview(client, offer["session_id"], "Tech", "en")
    resp = client.get(f"/api/sessions/{offer['session_id']}")
    data = resp.get_json()
    assert len(data["interviews"]) == 2


def test_get_interview_detail(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])
    resp = client.get(f"/api/interviews/{itw['interview_id']}")
    data = resp.get_json()
    assert data["questions"] == ["Présentez-vous.", "Q2"]
    assert data["feedbacks"] == {}


def test_delete_interview(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])
    resp = client.delete(f"/api/interviews/{itw['interview_id']}")
    assert resp.status_code == 200
    resp2 = client.get(f"/api/interviews/{itw['interview_id']}")
    assert resp2.status_code == 404


@patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100)
@patch("services.ai_service.analyze_answer", return_value={
    "transcription": "Réponse",
    "analysis_content": "Bon",
    "analysis_form": "OK",
    "ideal_answer_text": "Idéal",
})
@patch("services.ai_service.transcribe_audio", return_value="Réponse")
def test_analyze_answer_uses_interview_id(mock_transcribe, mock_analyze, mock_tts, client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])
    data = {
        "interview_id": itw["interview_id"],
        "question_index": "0",
        "duration_seconds": "30.0",
        "recording_mode": "audio",
        "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
    }
    resp = client.post("/api/analyze-answer", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.get_json()["transcription"] == "Réponse"


@patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100)
@patch("services.ai_service.analyze_answer", return_value={
    "transcription": "Ma réponse",
    "analysis_content": "Bon contenu",
    "analysis_form": "Bonne forme",
    "ideal_answer_text": "Réponse idéale",
})
@patch("services.ai_service.analyze_visual", return_value="Bon contact visuel.")
@patch("services.ai_service.transcribe_audio", return_value="Ma réponse")
def test_analyze_answer_video_mode(mock_transcribe, mock_visual, mock_analyze, mock_tts, client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])

    data = {
        "interview_id": itw["interview_id"],
        "question_index": "0",
        "duration_seconds": "30.0",
        "recording_mode": "video",
        "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
        "frame_0": (BytesIO(FAKE_FRAME), "frame_0.jpg", "image/jpeg"),
        "frame_1": (BytesIO(FAKE_FRAME), "frame_1.jpg", "image/jpeg"),
    }

    resp = client.post(
        "/api/analyze-answer",
        data=data,
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert "analysis_visual" in body
    assert body["analysis_visual"] == "Bon contact visuel."
    mock_visual.assert_called_once()


def test_analyze_answer_missing_interview_id(client):
    data = {
        "question_index": "0",
        "duration_seconds": "30.0",
        "recording_mode": "audio",
        "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
    }
    resp = client.post("/api/analyze-answer", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_analyze_answer_unknown_interview(client):
    data = {
        "interview_id": "unknown",
        "question_index": "0",
        "duration_seconds": "30.0",
        "recording_mode": "audio",
        "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
    }
    resp = client.post("/api/analyze-answer", data=data, content_type="multipart/form-data")
    assert resp.status_code == 404


def test_list_sessions_shows_interview_count(client):
    offer = _create_offer(client)
    _add_interview(client, offer["session_id"], "RH", "fr")
    resp = client.get("/api/sessions")
    sessions = resp.get_json()["sessions"]
    assert sessions[0]["interview_count"] >= 1


def test_generate_questions_endpoint_removed(client):
    resp = client.post(
        "/api/generate-questions",
        json={"cv": "CV", "job_offer": "Offre", "language": "fr", "context": "RH"},
    )
    assert resp.status_code == 404
