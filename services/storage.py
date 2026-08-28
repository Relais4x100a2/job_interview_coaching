"""Couche de persistance in-memory pour les sessions d'entretien."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

LANGUAGE_DISPLAY = {"fr": "Français", "en": "English"}


def _build_offer_title(job_offer: str, language: str, created_at: datetime) -> str:
    """Construit un titre court pour identifier une offre d'emploi.

    Args:
        job_offer: Description de l'offre d'emploi.
        language: Code langue ('fr' ou 'en').
        created_at: Date de création de la session.

    Returns:
        Titre extrait de l'offre ou fallback daté.
    """
    normalized = " ".join(job_offer.strip().split())
    if normalized:
        if len(normalized) > 40:
            return f"{normalized[:40]}…"
        return normalized

    date_str = created_at.strftime("%d/%m/%Y")
    lang_label = LANGUAGE_DISPLAY.get(language, language)
    return f"Offre du {date_str} - {lang_label}"


class InMemoryStorage:
    """Stockage en mémoire des sessions d'entraînement aux entretiens."""

    def __init__(self) -> None:
        """Initialise le stockage vide avec un verrou thread-safe."""
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_session(
        self,
        cv: str,
        job_offer: str,
        language: str,
        context: str,
    ) -> str:
        """Crée une nouvelle session et retourne son identifiant.

        Args:
            cv: Contenu du CV du candidat.
            job_offer: Description de l'offre d'emploi.
            language: Langue de l'entretien ('fr' ou 'en').
            context: Contexte de l'entretien.

        Returns:
            L'identifiant unique de la session créée.
        """
        session_id = str(uuid.uuid4())
        created_at = datetime.now(UTC)
        session = {
            "session_id": session_id,
            "cv": cv,
            "job_offer": job_offer,
            "language": language,
            "context": context,
            "offer_title": _build_offer_title(job_offer, language, created_at),
            "questions": [],
            "feedbacks": {},
            "created_at": created_at,
        }
        with self._lock:
            self._sessions[session_id] = session
        return session_id

    def save_questions(self, session_id: str, questions: list[str]) -> None:
        """Enregistre les questions générées pour une session.

        Args:
            session_id: Identifiant de la session.
            questions: Liste des questions d'entretien.

        Raises:
            KeyError: Si la session n'existe pas.
        """
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session introuvable : {session_id}")
            self._sessions[session_id]["questions"] = questions

    def save_feedback(
        self,
        session_id: str,
        question_index: int,
        feedback: dict[str, Any],
    ) -> None:
        """Enregistre le feedback d'une réponse pour une question donnée.

        Args:
            session_id: Identifiant de la session.
            question_index: Index de la question dans la session.
            feedback: Données de feedback structurées.

        Raises:
            KeyError: Si la session n'existe pas.
        """
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session introuvable : {session_id}")
            self._sessions[session_id]["feedbacks"][question_index] = feedback

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Récupère une session par son identifiant.

        Args:
            session_id: Identifiant de la session.

        Returns:
            Copie de la session ou None si introuvable.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            return {
                **session,
                "questions": list(session["questions"]),
                "feedbacks": dict(session["feedbacks"]),
            }

    def get_all_sessions(self) -> list[dict[str, Any]]:
        """Retourne la liste des sessions, triées par date décroissante.

        Returns:
            Liste de résumés de sessions (sans CV ni offre complète).
        """
        with self._lock:
            sessions = list(self._sessions.values())

        sessions.sort(key=lambda s: s["created_at"], reverse=True)
        return [
            {
                "session_id": session["session_id"],
                "offer_title": session["offer_title"],
                "language": session["language"],
                "context": session["context"],
                "created_at": session["created_at"].isoformat(),
            }
            for session in sessions
        ]
