"""Service d'intelligence artificielle : LLM, STT et TTS."""

from __future__ import annotations

import base64
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
        "IMPORTANT : génère des questions **spécifiques au type d'entretien décrit "
        "dans le contexte**. Par exemple : pour un screening RH, concentre-toi sur "
        "la motivation, le parcours, les prétentions salariales et la disponibilité. "
        "Pour un entretien technique, concentre-toi sur les compétences techniques, "
        "la résolution de problèmes et les choix d'architecture. "
        "Pour un entretien manager, concentre-toi sur le leadership, la gestion "
        "d'équipe et la vision stratégique. Adapte les questions au contexte fourni. "
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


def format_offer_content(cv: str, job_offer: str) -> tuple[str, str]:
    """Reformate le CV et l'offre d'emploi en Markdown structuré.

    Args:
        cv: Contenu brut du CV.
        job_offer: Contenu brut de l'offre d'emploi.

    Returns:
        Tuple (cv_markdown, job_offer_markdown).
    """
    system_prompt = (
        "Tu reformates des documents de candidature en Markdown propre et bien "
        "structuré (titres avec les bons niveaux de hiérarchie, listes à puces "
        "quand pertinent). "
        "Conserve la langue d'origine de chaque document et tout le contenu "
        "substantiel (compétences, expériences, exigences, responsabilités, "
        "conditions). N'invente et ne déduis aucune information absente du texte "
        "source. "
        "Supprime en revanche ce qui n'a pas de lien évident avec le poste ou la "
        "candidature : discours RSE / mission d'entreprise génériques, sections "
        "\"qui sommes-nous\", mentions légales sans rapport avec le poste. "
        'Réponds uniquement en JSON avec exactement ces clés : "cv", "job_offer".'
    )
    user_prompt = f"CV :\n{cv}\n\nOffre d'emploi :\n{job_offer}"

    raw = _call_llm(system_prompt, user_prompt)
    data = _parse_json_response(raw)

    for key in ("cv", "job_offer"):
        if key not in data:
            raise ValueError(f"Clé manquante dans la réponse LLM : {key}")

    return str(data["cv"]), str(data["job_offer"])


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
        "IMPORTANT : rédige analysis_content et analysis_form TOUJOURS en français, "
        "même si l'entretien est en anglais. Ce sont des feedbacks pour le candidat francophone. "
        "Chaque champ d'analyse doit être une chaîne de texte fluide (paragraphes), "
        "PAS un objet JSON imbriqué. "
        f"Rédige ideal_answer_text en {lang_label} (la langue de l'entretien). "
        "Réponds uniquement en JSON avec exactement ces clés : "
        "transcription, analysis_content, analysis_form, ideal_answer_text. "
        "analysis_content (en français) : pertinence de la réponse, éléments du CV "
        "omis ou mal valorisés par rapport à l'offre. "
        "analysis_form (en français) : syntaxe, grammaire, tics de langage, clarté, "
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


def analyze_visual(
    frames: list[bytes],
    question: str,
    language: str,
) -> str:
    """Analyse les frames vidéo via GPT-4o vision pour le feedback non-verbal.

    Args:
        frames: Liste d'images JPEG en bytes.
        question: Question d'entretien posée.
        language: Code langue ('fr' ou 'en').

    Returns:
        Texte d'analyse du non-verbal.

    Raises:
        ValueError: Si aucune frame n'est fournie.
    """
    if not frames:
        raise ValueError("Au moins une frame est requise pour l'analyse visuelle.")

    system_prompt = (
        "Tu es un coach expert en communication non-verbale pour les entretiens "
        "d'embauche. On te fournit des captures d'écran extraites de la vidéo d'un "
        "candidat répondant à une question d'entretien. "
        "Analyse : expressions faciales, contact visuel (regarde-t-il la caméra ?), "
        "posture, gestes, tics corporels, niveau de confiance perçu. "
        "Donne des conseils concrets d'amélioration. "
        "OBLIGATION : tu DOIS rédiger TOUTE ton analyse en français. "
        "Peu importe la langue de la question ou de l'entretien, "
        "ta réponse est intégralement en français."
    )

    image_parts = []
    for frame in frames:
        b64 = base64.b64encode(frame).decode("utf-8")
        image_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"},
        })

    user_content = [
        {"type": "text", "text": (
            f"Question posée au candidat : {question}\n\n"
            "Rappel : rédige ton analyse entièrement en français."
        )},
        *image_parts,
    ]

    client = _get_openai_client()
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=1000,
        temperature=0.7,
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Réponse GPT-4o vision vide.")
    return content.strip()


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
