"""Couche de persistance pour les sessions d'entretien (in-memory ou SQLite)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
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


def _deserialize_feedbacks(raw: str) -> dict[int, dict[str, Any]]:
    """Désérialise les feedbacks JSON en dictionnaire indexé par int.

    Args:
        raw: Chaîne JSON des feedbacks.

    Returns:
        Dictionnaire indexé par numéro de question.
    """
    parsed: dict[str, Any] = json.loads(raw or "{}")
    return {int(k): v for k, v in parsed.items()}


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


class SQLiteStorage:
    """Stockage SQLite des sessions d'entraînement aux entretiens."""

    def __init__(self, db_path: Path) -> None:
        """Initialise le stockage SQLite et crée le schéma si nécessaire.

        Args:
            db_path: Chemin vers le fichier de base de données.
        """
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """Ouvre une connexion SQLite configurée avec WAL.

        Returns:
            Connexion SQLite active.
        """
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    @contextmanager
    def _connection(self):
        """Context manager pour une connexion SQLite thread-safe."""
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        """Crée la table sessions si elle n'existe pas."""
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id   TEXT PRIMARY KEY,
                    offer_title  TEXT NOT NULL,
                    language     TEXT NOT NULL CHECK (language IN ('fr', 'en')),
                    created_at   TEXT NOT NULL,
                    data         TEXT NOT NULL DEFAULT '{}',
                    questions    TEXT NOT NULL DEFAULT '[]',
                    feedbacks    TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_created_at
                    ON sessions (created_at DESC);
            """)

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> dict[str, Any]:
        """Convertit une ligne SQL en dictionnaire session complet.

        Args:
            row: Ligne SQLite.

        Returns:
            Dictionnaire session compatible avec InMemoryStorage.
        """
        data = json.loads(row["data"])
        return {
            "session_id": row["session_id"],
            "offer_title": row["offer_title"],
            "language": row["language"],
            "cv": data["cv"],
            "job_offer": data["job_offer"],
            "context": data["context"],
            "questions": json.loads(row["questions"]),
            "feedbacks": _deserialize_feedbacks(row["feedbacks"]),
            "created_at": datetime.fromisoformat(row["created_at"]),
        }

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
        created_at_dt = datetime.now(UTC)
        created_at = created_at_dt.isoformat()
        offer_title = _build_offer_title(job_offer, language, created_at_dt)
        data_json = json.dumps(
            {"cv": cv, "job_offer": job_offer, "context": context},
            ensure_ascii=False,
        )

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions
                    (session_id, offer_title, language, created_at, data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, offer_title, language, created_at, data_json),
            )
        return session_id

    def save_questions(self, session_id: str, questions: list[str]) -> None:
        """Enregistre les questions générées pour une session.

        Args:
            session_id: Identifiant de la session.
            questions: Liste des questions d'entretien.

        Raises:
            KeyError: Si la session n'existe pas.
        """
        questions_json = json.dumps(questions, ensure_ascii=False)
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET questions = ? WHERE session_id = ?",
                (questions_json, session_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Session introuvable : {session_id}")

    def save_feedback(
        self,
        session_id: str,
        question_index: int,
        feedback: dict[str, Any],
    ) -> None:
        """Enregistre le feedback via json_set atomique SQLite.

        Args:
            session_id: Identifiant de la session.
            question_index: Index de la question dans la session.
            feedback: Données de feedback structurées.

        Raises:
            KeyError: Si la session n'existe pas.
        """
        feedback_json = json.dumps(feedback, ensure_ascii=False)
        key = str(question_index)
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE sessions
                SET feedbacks = json_set(feedbacks, '$.' || ?, json(?))
                WHERE session_id = ?
                """,
                (key, feedback_json, session_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Session introuvable : {session_id}")

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Récupère une session par son identifiant.

        Args:
            session_id: Identifiant de la session.

        Returns:
            Copie de la session ou None si introuvable.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def get_all_sessions(self) -> list[dict[str, Any]]:
        """Retourne la liste des sessions, triées par date décroissante.

        Returns:
            Liste de résumés de sessions (sans CV ni offre complète).
        """
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT session_id, offer_title, language, data, created_at
                FROM sessions
                ORDER BY created_at DESC
                """,
            ).fetchall()

        return [
            {
                "session_id": row["session_id"],
                "offer_title": row["offer_title"],
                "language": row["language"],
                "context": json.loads(row["data"])["context"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


def create_storage(
    base_dir: Path | None = None,
) -> InMemoryStorage | SQLiteStorage:
    """Instancie le backend de stockage selon STORAGE_TYPE.

    Args:
        base_dir: Répertoire racine pour résoudre DATABASE_PATH par défaut.

    Returns:
        Instance InMemoryStorage ou SQLiteStorage.
    """
    storage_type = os.getenv("STORAGE_TYPE", "sqlite").lower()
    if storage_type == "memory":
        return InMemoryStorage()

    root = base_dir or Path(__file__).resolve().parent.parent
    default_path = root / "instance" / "app.db"
    db_path = Path(os.getenv("DATABASE_PATH", str(default_path)))
    return SQLiteStorage(db_path)
