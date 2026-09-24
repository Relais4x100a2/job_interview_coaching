"""Tests for the multi-interview API."""
from io import BytesIO
from unittest.mock import patch

import pytest

from app import create_app, storage

FAKE_AUDIO = b"\x00" * 500
FAKE_FRAME = b"\xff\xd8\xff\xe0" + b"\x00" * 100


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _create_offer(client, cv="Mon CV", job_offer="Offre Python"):
    with patch("services.ai_service.format_offer_content", return_value=(cv, job_offer)):
        resp = client.post("/api/sessions", json={"cv": cv, "job_offer": job_offer})
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


def test_create_offer_uses_formatted_markdown(client):
    with patch(
        "services.ai_service.format_offer_content",
        return_value=("# CV formaté", "# Offre formatée"),
    ) as mock_format:
        resp = client.post("/api/sessions", json={"cv": "CV brut", "job_offer": "Offre brute"})
    assert resp.status_code == 200
    mock_format.assert_called_once_with("CV brut", "Offre brute")

    session_id = resp.get_json()["session_id"]
    detail = client.get(f"/api/sessions/{session_id}").get_json()
    assert detail["cv"] == "# CV formaté"
    assert detail["job_offer"] == "# Offre formatée"


def test_create_offer_falls_back_to_raw_text_on_formatting_failure(client):
    with patch(
        "services.ai_service.format_offer_content",
        side_effect=RuntimeError("Aucune clé API configurée."),
    ):
        resp = client.post("/api/sessions", json={"cv": "CV brut", "job_offer": "Offre brute"})
    assert resp.status_code == 200

    session_id = resp.get_json()["session_id"]
    detail = client.get(f"/api/sessions/{session_id}").get_json()
    assert detail["cv"] == "CV brut"
    assert detail["job_offer"] == "Offre brute"


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


def test_get_session_detail_includes_cv_and_job_offer(client):
    offer = _create_offer(client, cv="Mon CV", job_offer="Offre Python")
    resp = client.get(f"/api/sessions/{offer['session_id']}")
    data = resp.get_json()
    assert data["cv"] == "Mon CV"
    assert data["job_offer"] == "Offre Python"


def test_update_session_content(client):
    offer = _create_offer(client)
    resp = client.patch(
        f"/api/sessions/{offer['session_id']}",
        json={"cv": "CV modifié", "job_offer": "Offre modifiée"},
    )
    assert resp.status_code == 200

    detail = client.get(f"/api/sessions/{offer['session_id']}").get_json()
    assert detail["cv"] == "CV modifié"
    assert detail["job_offer"] == "Offre modifiée"


def test_update_session_content_unknown_session(client):
    resp = client.patch(
        "/api/sessions/unknown",
        json={"cv": "CV", "job_offer": "Offre"},
    )
    assert resp.status_code == 404


def test_update_session_content_missing_cv(client):
    offer = _create_offer(client)
    resp = client.patch(
        f"/api/sessions/{offer['session_id']}",
        json={"job_offer": "Offre"},
    )
    assert resp.status_code == 400


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
    "ideal_plan_text": "Plan",
})
@patch("services.ai_service.transcribe_audio", return_value=("Réponse", []))
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
    "ideal_plan_text": "Plan",
})
@patch("services.ai_service.analyze_visual", return_value="Bon contact visuel.")
@patch("services.ai_service.transcribe_audio", return_value=("Ma réponse", []))
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


@patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100)
@patch("services.ai_service.generate_neutral_ideal_answer", return_value="Réponse neutre.")
def test_generate_neutral_answer(mock_generate, mock_tts, client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])

    resp = client.post(
        "/api/generate-neutral-answer",
        json={"interview_id": itw["interview_id"], "question_index": 0},
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["neutral_answer_text"] == "Réponse neutre."
    assert "neutral_audio_url" in data
    mock_generate.assert_called_once()


def test_generate_neutral_answer_persists_on_feedback(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])

    with (
        patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100),
        patch(
            "services.ai_service.analyze_answer",
            return_value={
                "transcription": "Réponse",
                "analysis_content": "Bon",
                "analysis_form": "OK",
                "ideal_answer_text": "Idéal",
                "ideal_plan_text": "Plan",
            },
        ),
        patch("services.ai_service.transcribe_audio", return_value=("Réponse", [])),
    ):
        client.post(
            "/api/analyze-answer",
            data={
                "interview_id": itw["interview_id"],
                "question_index": "0",
                "duration_seconds": "30.0",
                "recording_mode": "audio",
                "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
            },
            content_type="multipart/form-data",
        )

    with (
        patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100),
        patch("services.ai_service.generate_neutral_ideal_answer", return_value="Réponse neutre."),
    ):
        client.post(
            "/api/generate-neutral-answer",
            json={"interview_id": itw["interview_id"], "question_index": 0},
        )

    detail = client.get(f"/api/interviews/{itw['interview_id']}").get_json()
    feedback = detail["feedbacks"]["0"] if "0" in detail["feedbacks"] else detail["feedbacks"][0]
    assert feedback["ideal_answer_text"] == "Idéal"
    assert feedback["neutral_answer_text"] == "Réponse neutre."


@patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100)
@patch("services.ai_service.analyze_answer", return_value={
    "transcription": "Réponse",
    "analysis_content": "Bon",
    "analysis_form": "OK",
    "ideal_answer_text": "Idéal",
    "ideal_plan_text": "- Point 1\n- Point 2",
})
@patch("services.ai_service.transcribe_audio", return_value=("Réponse", []))
def test_analyze_answer_seeds_validated_fields_on_first_call(mock_transcribe, mock_analyze, mock_tts, client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])

    resp = client.post(
        "/api/analyze-answer",
        data={
            "interview_id": itw["interview_id"],
            "question_index": "0",
            "duration_seconds": "30.0",
            "recording_mode": "audio",
            "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
        },
        content_type="multipart/form-data",
    )

    body = resp.get_json()
    assert body["validated_plan_text"] == "- Point 1\n- Point 2"
    assert body["validated_answer_text"] == "Idéal"


def test_analyze_answer_preserves_validated_fields_on_rerecord(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])
    interview_id = itw["interview_id"]

    with (
        patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100),
        patch("services.ai_service.transcribe_audio", return_value=("Réponse", [])),
        patch("services.ai_service.analyze_answer", return_value={
            "transcription": "Réponse",
            "analysis_content": "Bon",
            "analysis_form": "OK",
            "ideal_answer_text": "Idéal v1",
            "ideal_plan_text": "Plan v1",
        }),
    ):
        client.post(
            "/api/analyze-answer",
            data={
                "interview_id": interview_id,
                "question_index": "0",
                "duration_seconds": "30.0",
                "recording_mode": "audio",
                "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
            },
            content_type="multipart/form-data",
        )

    existing = storage.get_interview(interview_id)["feedbacks"][0]
    existing["validated_plan_text"] = "Mon plan retravaillé"
    existing["validated_answer_text"] = "Ma réponse retravaillée"
    storage.save_feedback(interview_id, 0, existing)

    with (
        patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100),
        patch("services.ai_service.transcribe_audio", return_value=("Réponse", [])),
        patch("services.ai_service.analyze_answer", return_value={
            "transcription": "Réponse",
            "analysis_content": "Bon",
            "analysis_form": "OK",
            "ideal_answer_text": "Idéal v2",
            "ideal_plan_text": "Plan v2",
        }),
    ):
        resp = client.post(
            "/api/analyze-answer",
            data={
                "interview_id": interview_id,
                "question_index": "0",
                "duration_seconds": "30.0",
                "recording_mode": "audio",
                "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
            },
            content_type="multipart/form-data",
        )

    body = resp.get_json()
    assert body["validated_plan_text"] == "Mon plan retravaillé"
    assert body["validated_answer_text"] == "Ma réponse retravaillée"
    assert body["ideal_plan_text"] == "Plan v2"
    assert body["ideal_answer_text"] == "Idéal v2"


def test_analyze_answer_preserves_empty_validated_string(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])
    interview_id = itw["interview_id"]

    with (
        patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100),
        patch("services.ai_service.transcribe_audio", return_value=("Réponse", [])),
        patch("services.ai_service.analyze_answer", return_value={
            "transcription": "Réponse",
            "analysis_content": "Bon",
            "analysis_form": "OK",
            "ideal_answer_text": "Idéal v1",
            "ideal_plan_text": "Plan v1",
        }),
    ):
        client.post(
            "/api/analyze-answer",
            data={
                "interview_id": interview_id,
                "question_index": "0",
                "duration_seconds": "30.0",
                "recording_mode": "audio",
                "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
            },
            content_type="multipart/form-data",
        )

    existing = storage.get_interview(interview_id)["feedbacks"][0]
    existing["validated_plan_text"] = ""
    storage.save_feedback(interview_id, 0, existing)

    with (
        patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100),
        patch("services.ai_service.transcribe_audio", return_value=("Réponse", [])),
        patch("services.ai_service.analyze_answer", return_value={
            "transcription": "Réponse",
            "analysis_content": "Bon",
            "analysis_form": "OK",
            "ideal_answer_text": "Idéal v2",
            "ideal_plan_text": "Plan v2",
        }),
    ):
        resp = client.post(
            "/api/analyze-answer",
            data={
                "interview_id": interview_id,
                "question_index": "0",
                "duration_seconds": "30.0",
                "recording_mode": "audio",
                "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
            },
            content_type="multipart/form-data",
        )

    body = resp.get_json()
    assert body["validated_plan_text"] == ""


def test_generate_neutral_answer_unknown_interview(client):
    resp = client.post(
        "/api/generate-neutral-answer",
        json={"interview_id": "unknown", "question_index": 0},
    )
    assert resp.status_code == 404


def test_generate_neutral_answer_invalid_question_index(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])

    resp = client.post(
        "/api/generate-neutral-answer",
        json={"interview_id": itw["interview_id"], "question_index": 99},
    )
    assert resp.status_code == 400


def test_generate_questions_endpoint_removed(client):
    resp = client.post(
        "/api/generate-questions",
        json={"cv": "CV", "job_offer": "Offre", "language": "fr", "context": "RH"},
    )
    assert resp.status_code == 404


def test_save_validated_updates_fields_only(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])
    interview_id = itw["interview_id"]

    with (
        patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100),
        patch("services.ai_service.transcribe_audio", return_value=("Réponse", [])),
        patch("services.ai_service.analyze_answer", return_value={
            "transcription": "Réponse",
            "analysis_content": "Bon contenu",
            "analysis_form": "OK",
            "ideal_answer_text": "Idéal",
            "ideal_plan_text": "Plan",
        }),
    ):
        client.post(
            "/api/analyze-answer",
            data={
                "interview_id": interview_id,
                "question_index": "0",
                "duration_seconds": "30.0",
                "recording_mode": "audio",
                "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
            },
            content_type="multipart/form-data",
        )

    resp = client.post(
        "/api/save-validated",
        json={
            "interview_id": interview_id,
            "question_index": 0,
            "validated_plan_text": "Mon plan",
            "validated_answer_text": "Ma réponse",
        },
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["validated_plan_text"] == "Mon plan"
    assert body["validated_answer_text"] == "Ma réponse"
    assert body["analysis_content"] == "Bon contenu"


def test_save_validated_unknown_interview_returns_404(client):
    resp = client.post(
        "/api/save-validated",
        json={
            "interview_id": "unknown",
            "question_index": 0,
            "validated_plan_text": "Plan",
            "validated_answer_text": "Réponse",
        },
    )
    assert resp.status_code == 404


def test_save_validated_no_prior_feedback_returns_404(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])

    resp = client.post(
        "/api/save-validated",
        json={
            "interview_id": itw["interview_id"],
            "question_index": 0,
            "validated_plan_text": "Plan",
            "validated_answer_text": "Réponse",
        },
    )
    assert resp.status_code == 404


def test_save_validated_missing_field_returns_400(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])

    resp = client.post(
        "/api/save-validated",
        json={
            "interview_id": itw["interview_id"],
            "question_index": 0,
            "validated_plan_text": "Plan",
        },
    )
    assert resp.status_code == 400


def test_export_plans_unknown_interview_returns_404(client):
    resp = client.get("/api/interviews/unknown/export/plans")
    assert resp.status_code == 404


def test_export_answers_unknown_interview_returns_404(client):
    resp = client.get("/api/interviews/unknown/export/answers")
    assert resp.status_code == 404


def test_export_plans_empty_state_message(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])

    resp = client.get(f"/api/interviews/{itw['interview_id']}/export/plans")

    assert resp.status_code == 200
    assert "Aucun contenu validé" in resp.get_data(as_text=True)


def test_export_plans_ordered_and_filters_missing_content(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])
    interview_id = itw["interview_id"]

    # Save question 1's feedback before question 0's, to prove export order
    # follows question_index, not save order.
    storage.save_feedback(interview_id, 1, {
        "transcription": "R2", "analysis_content": "c", "analysis_form": "f",
        "ideal_answer_text": "Idéal 2", "ideal_plan_text": "Plan 2",
        "validated_plan_text": "Mon plan question 2",
        "validated_answer_text": "Ma réponse question 2",
    })
    storage.save_feedback(interview_id, 0, {
        "transcription": "R1", "analysis_content": "c", "analysis_form": "f",
        "ideal_answer_text": "Idéal 1", "ideal_plan_text": "Plan 1",
        "validated_plan_text": "Mon plan question 1",
        "validated_answer_text": "",
    })

    resp = client.get(f"/api/interviews/{interview_id}/export/plans")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "text/markdown; charset=utf-8"
    assert f"{interview_id}-plans.md" in resp.headers["Content-Disposition"]
    assert body.index("Mon plan question 1") < body.index("Mon plan question 2")

    resp2 = client.get(f"/api/interviews/{interview_id}/export/answers")
    body2 = resp2.get_data(as_text=True)

    assert f"{interview_id}-reponses.md" in resp2.headers["Content-Disposition"]
    assert "Ma réponse question 2" in body2
    assert "Question 1" not in body2
