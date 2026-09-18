from io import BytesIO
from unittest.mock import MagicMock, patch

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


def _setup_session(client):
    """Create a session with one question via mocked AI."""
    with patch("services.ai_service.generate_questions", return_value=["Présentez-vous."]):
        resp = client.post(
            "/api/generate-questions",
            json={
                "cv": "Mon CV",
                "job_offer": "Offre test",
                "language": "fr",
                "context": "Entretien RH",
            },
        )
        return resp.get_json()["session_id"]


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
    session_id = _setup_session(client)

    data = {
        "session_id": session_id,
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


@patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100)
@patch("services.ai_service.analyze_answer", return_value={
    "transcription": "Ma réponse",
    "analysis_content": "Bon contenu",
    "analysis_form": "Bonne forme",
    "ideal_answer_text": "Réponse idéale",
})
@patch("services.ai_service.transcribe_audio", return_value="Ma réponse")
def test_analyze_answer_audio_mode_unchanged(mock_transcribe, mock_analyze, mock_tts, client):
    session_id = _setup_session(client)

    data = {
        "session_id": session_id,
        "question_index": "0",
        "duration_seconds": "30.0",
        "recording_mode": "audio",
        "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
    }

    resp = client.post(
        "/api/analyze-answer",
        data=data,
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert "analysis_visual" not in body
