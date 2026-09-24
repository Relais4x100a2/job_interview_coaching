from unittest.mock import MagicMock, patch

from services import ai_service

FAKE_FRAME = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # minimal JPEG header bytes


def _mock_vision_response(text: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = text
    response = MagicMock()
    response.choices = [choice]
    return response


@patch.object(ai_service, "_get_openai_client")
def test_analyze_visual_returns_text(mock_client_fn):
    mock_client = MagicMock()
    mock_client_fn.return_value = mock_client
    mock_client.chat.completions.create.return_value = _mock_vision_response(
        "Le candidat maintient un bon contact visuel."
    )

    result = ai_service.analyze_visual(
        frames=[FAKE_FRAME, FAKE_FRAME],
        question="Présentez-vous.",
        language="fr",
    )

    assert isinstance(result, str)
    assert len(result) > 0
    mock_client.chat.completions.create.assert_called_once()

    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["model"] == "gpt-4o"
    messages = call_kwargs["messages"]
    user_msg = messages[1]
    image_parts = [p for p in user_msg["content"] if p["type"] == "image_url"]
    assert len(image_parts) == 2


@patch.object(ai_service, "_get_openai_client")
def test_analyze_visual_empty_frames_raises(mock_client_fn):
    try:
        ai_service.analyze_visual(frames=[], question="Q?", language="fr")
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "frame" in str(exc).lower()


@patch.object(ai_service, "_call_llm")
def test_format_offer_content_returns_markdown_tuple(mock_call_llm):
    mock_call_llm.return_value = (
        '{"cv": "# Mon CV", "job_offer": "# Offre Python"}'
    )

    cv_md, job_offer_md = ai_service.format_offer_content(
        cv="Mon CV brut", job_offer="Offre Python brute"
    )

    assert cv_md == "# Mon CV"
    assert job_offer_md == "# Offre Python"
    mock_call_llm.assert_called_once()


@patch.object(ai_service, "_call_llm")
def test_format_offer_content_missing_key_raises(mock_call_llm):
    mock_call_llm.return_value = '{"cv": "# Mon CV"}'

    try:
        ai_service.format_offer_content(cv="CV", job_offer="Offre")
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "job_offer" in str(exc)


@patch.object(ai_service, "_call_llm")
def test_analyze_answer_prompt_asks_to_build_on_candidate_answer(mock_call_llm):
    mock_call_llm.return_value = (
        '{"transcription": "Réponse", "analysis_content": "Bon", '
        '"analysis_form": "OK", "ideal_answer_text": "Idéal", '
        '"ideal_plan_text": "- Point 1"}'
    )

    ai_service.analyze_answer(
        question="Présentez-vous.",
        transcription="Réponse du candidat",
        cv="CV",
        job_offer="Offre",
        context="RH",
        language="fr",
        duration_seconds=30.0,
    )

    system_prompt = mock_call_llm.call_args[0][0]
    assert "transcription réelle" in system_prompt
    assert "voix personnelle" in system_prompt


@patch.object(ai_service, "_call_llm")
def test_analyze_answer_includes_ideal_plan_text(mock_call_llm):
    mock_call_llm.return_value = (
        '{"transcription": "Réponse", "analysis_content": "Bon", '
        '"analysis_form": "OK", "ideal_answer_text": "Idéal", '
        '"ideal_plan_text": "- Point 1\\n- Point 2"}'
    )

    result = ai_service.analyze_answer(
        question="Présentez-vous.",
        transcription="Réponse du candidat",
        cv="CV",
        job_offer="Offre",
        context="RH",
        language="fr",
        duration_seconds=30.0,
    )

    assert result["ideal_plan_text"] == "- Point 1\n- Point 2"


@patch.object(ai_service, "_call_llm")
def test_analyze_answer_missing_ideal_plan_text_raises(mock_call_llm):
    mock_call_llm.return_value = (
        '{"transcription": "Réponse", "analysis_content": "Bon", '
        '"analysis_form": "OK", "ideal_answer_text": "Idéal"}'
    )

    try:
        ai_service.analyze_answer(
            question="Présentez-vous.",
            transcription="Réponse du candidat",
            cv="CV",
            job_offer="Offre",
            context="RH",
            language="fr",
            duration_seconds=30.0,
        )
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "ideal_plan_text" in str(exc)


@patch.object(ai_service, "_call_llm")
def test_generate_neutral_ideal_answer_returns_text(mock_call_llm):
    mock_call_llm.return_value = '{"answer": "Réponse neutre engageante."}'

    result = ai_service.generate_neutral_ideal_answer(
        question="Présentez-vous.",
        cv="CV",
        job_offer="Offre",
        context="RH",
        language="fr",
    )

    assert result == "Réponse neutre engageante."
    mock_call_llm.assert_called_once()
    system_prompt = mock_call_llm.call_args[0][0]
    assert "engageant" in system_prompt


@patch.object(ai_service, "_call_llm")
def test_generate_neutral_ideal_answer_missing_key_raises(mock_call_llm):
    mock_call_llm.return_value = "{}"

    try:
        ai_service.generate_neutral_ideal_answer(
            question="Q", cv="CV", job_offer="Offre", context="RH", language="fr"
        )
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "answer" in str(exc)
