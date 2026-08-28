"""Service d'intelligence artificielle : LLM, STT et TTS."""

from __future__ import annotations

import json
import logging
import os
from io import BytesIO
from typing import Any

import litellm
from openai import OpenAI

logger = logging.getLogger(__name__)

LANGUAGE_LABELS = {"fr": "Français", "en": "English"}

INTRO_QUESTIONS = {
    "fr": "Pouvez-vous vous présenter ?",
    "en": "Could you introduce yourself?",
}


def _detect_provider() -> str:
    """Détecte le provider IA à partir des variables d'environnement.

    Returns:
        'openai' ou 'openrouter'.

    Raises:
        RuntimeError: Si aucune clé API n'est configurée.
    """
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    raise RuntimeError(
        "Aucune clé API configurée. "
        "Définissez OPENAI_API_KEY ou OPENROUTER_API_KEY."
    )


def _get_openai_client() -> OpenAI:
    """Retourne un client OpenAI pour STT et TTS.

    Returns:
        Client OpenAI configuré.

    Raises:
        RuntimeError: Si OPENAI_API_KEY est absent.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY est requis pour la transcription (Whisper) "
            "et la synthèse vocale (TTS)."
        )
    return OpenAI(api_key=api_key)


def _get_llm_model() -> str:
    """Retourne le nom du modèle LLM selon le provider actif."""
    provider = _detect_provider()
    if provider == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """Appelle le LLM configuré et retourne le contenu textuel.

    Args:
        system_prompt: Instructions système.
        user_prompt: Message utilisateur.

    Returns:
        Contenu textuel de la réponse du modèle.
    """
    provider = _detect_provider()
    model = _get_llm_model()

    if provider == "openai":
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("Réponse LLM vide.")
        return content

    litellm_model = f"openrouter/{model}" if not model.startswith("openrouter/") else model
    response = litellm.completion(
        model=litellm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Réponse LLM vide.")
    return content


def _parse_json_response(raw: str) -> dict[str, Any]:
    """Parse une réponse JSON du LLM avec gestion des erreurs.

    Args:
        raw: Chaîne JSON brute.

    Returns:
        Dictionnaire parsé.

    Raises:
        ValueError: Si le JSON est invalide.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON invalide reçu du LLM : {exc}") from exc
    if not isinstance(parsed, dict):
        raise TypeError("La réponse LLM doit être un objet JSON.")
    return parsed


def generate_questions(
    cv: str,
    job_offer: str,
    language: str,
    context: str,
) -> list[str]:
    """Génère 5 à 7 questions d'entretien personnalisées (Q1 = présentation).

    Args:
        cv: Contenu du CV.
        job_offer: Description de l'offre.
        language: Code langue ('fr' ou 'en').
        context: Contexte de l'entretien.

    Returns:
        Liste de questions d'entretien avec la question de présentation en Q1.
    """
    lang_label = LANGUAGE_LABELS.get(language, language)
    intro_q = INTRO_QUESTIONS[language]
    system_prompt = (
        "Tu es un expert en recrutement. Génère des questions d'entretien "
        "pertinentes basées sur le CV, l'offre d'emploi et le contexte fournis. "
        f"Les questions doivent être rédigées en {lang_label}. "
        f'La toute première question (Question #1) DOIT être strictement : "{intro_q}". '
        "Génère ensuite 4 à 6 questions spécifiques basées sur le CV, l'offre et le contexte. "
        'Réponds uniquement en JSON avec la clé "questions" contenant '
        "un tableau de 5 à 7 questions (chaînes de caractères)."
    )
    user_prompt = (
        f"CV du candidat :\n{cv}\n\n"
        f"Offre d'emploi :\n{job_offer}\n\n"
        f"Contexte de l'entretien :\n{context}\n\n"
        f'Question #1 obligatoire : "{intro_q}". '
        "Génère ensuite des questions variées couvrant motivation, compétences techniques, "
        "expériences passées et adéquation avec le poste."
    )

    raw = _call_llm(system_prompt, user_prompt)
    data = _parse_json_response(raw)
    questions = data.get("questions", [])
    if not isinstance(questions, list):
        raise TypeError("Le LLM n'a pas retourné de questions valides.")

    questions = [str(q) for q in questions if q]
    other_questions = [q for q in questions if q.strip().lower() != intro_q.lower()]
    return [intro_q] + other_questions[:6]


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """Transcrit un fichier audio en texte via Whisper.

    Args:
        audio_bytes: Contenu binaire de l'audio.
        filename: Nom du fichier pour l'API Whisper.

    Returns:
        Transcription textuelle.
    """
    client = _get_openai_client()
    audio_file = BytesIO(audio_bytes)
    audio_file.name = filename
    transcription = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
    )
    return transcription.text.strip()


def analyze_answer(
    question: str,
    transcription: str,
    cv: str,
    job_offer: str,
    context: str,
    language: str,
    duration_seconds: float,
) -> dict[str, str]:
    """Analyse une réponse d'entretien et produit un feedback structuré.

    Args:
        question: Question posée.
        transcription: Transcription de la réponse orale.
        cv: CV du candidat.
        job_offer: Offre d'emploi.
        context: Contexte de l'entretien.
        language: Code langue ('fr' ou 'en').
        duration_seconds: Durée de l'enregistrement audio.

    Returns:
        Dictionnaire avec transcription, analyses et réponse idéale.
    """
    lang_label = LANGUAGE_LABELS.get(language, language)
    word_count = len(transcription.split()) if transcription else 0
    wpm = round((word_count / duration_seconds) * 60, 1) if duration_seconds > 0 else 0

    system_prompt = (
        "Tu es un coach en entretien d'embauche. Analyse la réponse du candidat "
        "et produis un feedback détaillé. "
        f"Rédige ideal_answer_text en {lang_label}. "
        "Réponds uniquement en JSON avec exactement ces clés : "
        "transcription, analysis_content, analysis_form, ideal_answer_text. "
        "analysis_content : pertinence, éléments du CV omis ou mal valorisés "
        "par rapport à l'offre. "
        "analysis_form : syntaxe, grammaire, tics de langage, clarté, "
        f"débit estimé ({wpm} mots/minute sur {duration_seconds:.1f}s)."
    )
    user_prompt = (
        f"Question : {question}\n\n"
        f"Transcription de la réponse : {transcription}\n\n"
        f"CV :\n{cv}\n\n"
        f"Offre d'emploi :\n{job_offer}\n\n"
        f"Contexte :\n{context}\n\n"
        f"Durée audio : {duration_seconds:.1f} secondes\n"
        f"Nombre de mots : {word_count}"
    )

    raw = _call_llm(system_prompt, user_prompt)
    data = _parse_json_response(raw)

    required_keys = (
        "transcription",
        "analysis_content",
        "analysis_form",
        "ideal_answer_text",
    )
    for key in required_keys:
        if key not in data:
            raise ValueError(f"Clé manquante dans la réponse LLM : {key}")

    return {
        "transcription": str(data["transcription"]),
        "analysis_content": str(data["analysis_content"]),
        "analysis_form": str(data["analysis_form"]),
        "ideal_answer_text": str(data["ideal_answer_text"]),
    }


def synthesize_speech(text: str) -> bytes:
    """Synthétise un texte en audio MP3 via OpenAI TTS.

    Args:
        text: Texte à synthétiser.

    Returns:
        Contenu binaire du fichier MP3.
    """
    client = _get_openai_client()
    response = client.audio.speech.create(
        model="tts-1",
        voice=os.getenv("TTS_VOICE", "alloy"),
        input=text,
        response_format="mp3",
    )
    return response.content
