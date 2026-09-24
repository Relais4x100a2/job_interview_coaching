"""Service d'intelligence artificielle : LLM, STT et TTS."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
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


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> tuple[str, list[dict]]:
    """Transcrit un fichier audio en texte via Whisper, avec timestamps par mot.

    Args:
        audio_bytes: Contenu binaire de l'audio.
        filename: Nom du fichier pour l'API Whisper.

    Returns:
        Tuple (texte transcrit, liste de mots `{word, start, end}`).
    """
    client = _get_openai_client()
    audio_file = BytesIO(audio_bytes)
    audio_file.name = filename
    transcription = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        response_format="verbose_json",
        timestamp_granularities=["word"],
    )
    words = [
        {"word": w.word, "start": w.start, "end": w.end}
        for w in (transcription.words or [])
    ]
    return transcription.text.strip(), words


PACING_WINDOW_SECONDS = 10.0
PACING_STEP_SECONDS = 2.0
HESITATION_SILENCE_MIN_S = 0.25
HESITATION_SILENCE_MAX_S = 1.2
HESITATION_MIN_PRIOR_SPEECH_S = 0.4


def analyze_speech_pacing(words: list[dict]) -> dict:
    """Calcule le débit de parole glissant et détecte les hésitations.

    Args:
        words: Liste de mots `{word, start, end}` issue de `transcribe_audio`.

    Returns:
        Dict `{pacing_segments, hesitation_count, hesitation_timestamps}`.
        Structures vides si `words` est vide (jamais d'exception).
    """
    if not words:
        return {
            "pacing_segments": [],
            "hesitation_count": 0,
            "hesitation_timestamps": [],
        }

    total_end = words[-1]["end"]
    pacing_segments = []
    start = 0.0
    while start < total_end:
        end = start + PACING_WINDOW_SECONDS
        window_end = min(end, total_end)
        window_duration = window_end - start
        count = sum(1 for w in words if start <= w["start"] < end)
        wpm = round((count / window_duration) * 60.0, 1) if window_duration > 0 else 0.0
        pacing_segments.append({"start_s": start, "end_s": window_end, "wpm": wpm})
        start += PACING_STEP_SECONDS

    hesitation_count = 0
    hesitation_timestamps = []
    prior_speech_start = words[0]["start"]
    for i in range(1, len(words)):
        gap = words[i]["start"] - words[i - 1]["end"]
        if gap >= HESITATION_SILENCE_MIN_S:
            prior_speech_duration = words[i - 1]["end"] - prior_speech_start
            if gap <= HESITATION_SILENCE_MAX_S and prior_speech_duration >= HESITATION_MIN_PRIOR_SPEECH_S:
                hesitation_count += 1
                hesitation_timestamps.append(words[i - 1]["end"])
            prior_speech_start = words[i]["start"]

    return {
        "pacing_segments": pacing_segments,
        "hesitation_count": hesitation_count,
        "hesitation_timestamps": hesitation_timestamps,
    }


FILLER_WORD_PATTERNS = {
    "fr": ["euh", "hum", "du coup", "en fait", "voilà"],
    "en": ["um", "uh", "like", "you know", "actually"],
}


def count_filler_words(transcription: str, language: str) -> dict[str, int]:
    """Compte les mots de remplissage littéraux dans une transcription.

    Args:
        transcription: Texte transcrit par Whisper.
        language: Langue de l'entretien (`fr` ou `en`).

    Returns:
        Dict `{motif: occurrences}`, uniquement les motifs trouvés au moins
        une fois.
    """
    patterns = FILLER_WORD_PATTERNS.get(language, FILLER_WORD_PATTERNS["fr"])
    text = transcription.lower()
    counts: dict[str, int] = {}
    for phrase in patterns:
        matches = re.findall(rf"\b{re.escape(phrase)}\b", text)
        if matches:
            counts[phrase] = len(matches)
    return counts


def merge_filler_counts(counts_list: list[dict[str, int]]) -> dict[str, int]:
    """Fusionne plusieurs compteurs de mots de remplissage en un seul total."""
    merged: dict[str, int] = {}
    for counts in counts_list:
        for phrase, count in counts.items():
            merged[phrase] = merged.get(phrase, 0) + count
    return merged


TIC_NGRAM_MIN_LENGTH = 2
TIC_NGRAM_MAX_LENGTH = 4
TIC_MIN_OCCURRENCES = 2

STOPWORDS = {
    "fr": {
        "le", "la", "les", "un", "une", "des", "de", "du", "et", "à", "au",
        "aux", "que", "qui", "est", "je", "tu", "il", "elle", "on", "nous",
        "vous", "ils", "elles", "ce", "cette", "ces", "dans", "pour", "par",
        "avec", "sur", "pas", "ne", "se", "sa", "son", "ses", "mon", "ma",
        "mes", "ton", "ta", "tes", "y", "en",
    },
    "en": {
        "the", "a", "an", "and", "to", "of", "in", "on", "for", "with",
        "is", "are", "was", "were", "i", "you", "he", "she", "it", "we",
        "they", "this", "that", "these", "those", "at", "by", "as", "be",
        "been", "have", "has", "had", "do", "does", "did", "not", "so", "if",
    },
}


def detect_tics(transcriptions: list[str], language: str) -> list[dict]:
    """Détecte les tournures (n-grammes) qui reviennent dans des transcriptions.

    Args:
        transcriptions: Liste de textes transcrits (une réponse, ou toutes
            les réponses d'un entretien pour l'agrégat).
        language: Langue de l'entretien (`fr` ou `en`), pour choisir la
            liste de mots vides à filtrer.

    Returns:
        Liste `{phrase, count}` pour les n-grammes (2 à 4 mots) apparaissant
        au moins `TIC_MIN_OCCURRENCES` fois et non composés uniquement de
        mots vides, triée par occurrences décroissantes.
    """
    stopwords = STOPWORDS.get(language, STOPWORDS["fr"])
    counts: dict[str, int] = {}
    for text in transcriptions:
        tokens = re.findall(r"[\w']+", text.lower())
        for n in range(TIC_NGRAM_MIN_LENGTH, TIC_NGRAM_MAX_LENGTH + 1):
            for i in range(len(tokens) - n + 1):
                ngram_tokens = tokens[i:i + n]
                if all(tok in stopwords for tok in ngram_tokens):
                    continue
                phrase = " ".join(ngram_tokens)
                counts[phrase] = counts.get(phrase, 0) + 1

    tics = [
        {"phrase": phrase, "count": count}
        for phrase, count in counts.items()
        if count >= TIC_MIN_OCCURRENCES
    ]
    tics.sort(key=lambda t: t["count"], reverse=True)
    return tics


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
        f"Pour ideal_answer_text (en {lang_label}, la langue de l'entretien) : fais "
        "du coaching, pas une réécriture générique. Pars de la transcription réelle "
        "du candidat, garde ses idées fortes, son vécu concret et sa voix "
        "personnelle quand ils sont pertinents, et améliore seulement ce qui doit "
        "l'être (tics de langage, formulations floues ou maladroites, manque de "
        "précision). Utilise le CV et l'offre pour combler des trous factuels ou "
        "préciser des compétences, jamais pour remplacer le vécu du candidat par "
        "une réponse générique et impersonnelle. Le résultat doit rester à la "
        "première personne et sonner comme ce candidat, pas comme une réponse type. "
        f"Pour ideal_plan_text (en {lang_label}) : résume en 3 à 5 points la "
        "structure de cette réponse idéale, rédigé en Markdown à puces (une ligne "
        "commençant par '- ' par point), sans reprendre le texte intégral de la "
        "réponse. "
        "Réponds uniquement en JSON avec exactement ces clés : "
        "transcription, analysis_content, analysis_form, ideal_answer_text, "
        "ideal_plan_text. "
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
        "ideal_plan_text",
    )
    for key in required_keys:
        if key not in data:
            raise ValueError(f"Clé manquante dans la réponse LLM : {key}")

    return {
        "transcription": str(data["transcription"]),
        "analysis_content": str(data["analysis_content"]),
        "analysis_form": str(data["analysis_form"]),
        "ideal_answer_text": str(data["ideal_answer_text"]),
        "ideal_plan_text": str(data["ideal_plan_text"]),
    }


def generate_neutral_ideal_answer(
    question: str,
    cv: str,
    job_offer: str,
    context: str,
    language: str,
) -> str:
    """Génère une réponse idéale neutre basée uniquement sur le CV et l'offre.

    Args:
        question: Question d'entretien posée.
        cv: CV du candidat.
        job_offer: Offre d'emploi.
        context: Contexte de l'entretien.
        language: Code langue ('fr' ou 'en').

    Returns:
        Texte de la réponse idéale neutre.

    Raises:
        ValueError: Si la clé attendue est absente de la réponse LLM.
    """
    lang_label = LANGUAGE_LABELS.get(language, language)

    system_prompt = (
        "Tu es un coach en entretien d'embauche. À partir du CV et de l'offre "
        "d'emploi fournis, rédige une réponse idéale et neutre à la question "
        "posée, comme si elle était donnée par un candidat solide dont le profil "
        "correspond parfaitement au poste. "
        "Le ton doit être neutre et sérieux, mais engageant : la réponse doit "
        "donner envie d'embaucher la personne, sans tomber dans le survendu ni "
        "le jargon corporate creux. "
        "Base-toi uniquement sur les faits du CV et de l'offre, sans inventer "
        "d'expérience absente du CV. "
        f"Rédige la réponse en {lang_label} (la langue de l'entretien), à la "
        "première personne. "
        'Réponds uniquement en JSON avec exactement cette clé : "answer".'
    )
    user_prompt = (
        f"Question : {question}\n\n"
        f"CV :\n{cv}\n\n"
        f"Offre d'emploi :\n{job_offer}\n\n"
        f"Contexte de l'entretien :\n{context}"
    )

    raw = _call_llm(system_prompt, user_prompt)
    data = _parse_json_response(raw)
    if "answer" not in data:
        raise ValueError("Clé manquante dans la réponse LLM : answer")
    return str(data["answer"])


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
