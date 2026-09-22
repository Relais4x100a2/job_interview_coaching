"""Couche de persistance pour les offres et entretiens (in-memory ou SQLite).

Modèle de données : une session représente une offre d'emploi (CV, offre,
titre). Une offre peut avoir plusieurs entretiens (contexte, langue,
questions, feedbacks).
"""

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

VALID_LANGUAGES = ("fr", "en")


def _build_offer_title(job_offer: str, created_at: datetime) -> str:
    """Construit un titre court pour identifier une offre d'emploi.

    Args:
        job_offer: Description de l'offre d'emploi.
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
    return f"Offre du {date_str}"


def _validate_language(language: str) -> None:
    """Vérifie que la langue est une valeur supportée.

    Args:
        language: Code langue à valider.

    Raises:
        ValueError: Si la langue n'est pas 'fr' ou 'en'.
    """
    if language not in VALID_LANGUAGES:
        raise ValueError(
            f"Langue invalide : {language!r} (attendu : {VALID_LANGUAGES})"
        )


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
    """Stockage en mémoire des offres et entretiens d'entraînement."""

    def __init__(self) -> None:
        """Initialise le stockage vide avec un verrou thread-safe."""
        self._sessions: dict[str, dict[str, Any]] = {}
        self._interviews: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    # -- Sessions (offres) ------------------------------------------------

    def create_session(self, cv: str, job_offer: str) -> str:
        """Crée une nouvelle offre (session) et retourne son identifiant.

        Args:
            cv: Contenu du CV du candidat.
            job_offer: Description de l'offre d'emploi.

        Returns:
            L'identifiant unique de la session créée.
        """
        session_id = str(uuid.uuid4())
        created_at = datetime.now(UTC)
        session = {
            "session_id": session_id,
            "cv": cv,
            "job_offer": job_offer,
            "offer_title": _build_offer_title(job_offer, created_at),
            "created_at": created_at,
            "archived": False,
        }
        with self._lock:
            self._sessions[session_id] = session
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Récupère une offre par son identifiant, avec ses entretiens.

        Args:
            session_id: Identifiant de la session.

        Returns:
            Dictionnaire de la session (avec liste `interviews`) ou None.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            interviews = [
                {
                    "interview_id": itw["interview_id"],
                    "context": itw["context"],
                    "language": itw["language"],
                    "question_count": len(itw["questions"]),
                    "feedback_count": len(itw["feedbacks"]),
                    "created_at": itw["created_at"],
                }
                for itw in self._interviews.values()
                if itw["session_id"] == session_id
            ]
            interviews.sort(key=lambda i: i["created_at"])
            return {**session, "interviews": interviews}

    def get_all_sessions(self, archived: bool = False) -> list[dict[str, Any]]:
        """Retourne la liste des offres, triées par date décroissante.

        Args:
            archived: Si True, retourne les offres archivées.

        Returns:
            Liste de résumés d'offres avec le nombre d'entretiens.
        """
        with self._lock:
            sessions = [
                s for s in self._sessions.values()
                if s.get("archived", False) == archived
            ]
            result = []
            for s in sessions:
                count = sum(
                    1
                    for itw in self._interviews.values()
                    if itw["session_id"] == s["session_id"]
                )
                result.append({
                    "session_id": s["session_id"],
                    "offer_title": s["offer_title"],
                    "interview_count": count,
                    "created_at": s["created_at"].isoformat(),
                })

        result.sort(key=lambda s: s["created_at"], reverse=True)
        return result

    def update_offer_title(self, session_id: str, title: str) -> None:
        """Met à jour le titre d'une offre."""
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session introuvable : {session_id}")
            self._sessions[session_id]["offer_title"] = title

    def update_offer_content(self, session_id: str, cv: str, job_offer: str) -> None:
        """Met à jour le CV et l'offre d'emploi d'une session."""
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session introuvable : {session_id}")
            self._sessions[session_id]["cv"] = cv
            self._sessions[session_id]["job_offer"] = job_offer

    def archive_session(self, session_id: str) -> None:
        """Archive une offre."""
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session introuvable : {session_id}")
            self._sessions[session_id]["archived"] = True

    def unarchive_session(self, session_id: str) -> None:
        """Désarchive une offre."""
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session introuvable : {session_id}")
            self._sessions[session_id]["archived"] = False

    def delete_session(self, session_id: str) -> None:
        """Supprime définitivement une offre et ses entretiens (cascade)."""
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session introuvable : {session_id}")
            del self._sessions[session_id]
            to_delete = [
                iid
                for iid, itw in self._interviews.items()
                if itw["session_id"] == session_id
            ]
            for iid in to_delete:
                del self._interviews[iid]

    # -- Interviews ---------------------------------------------------------

    def create_interview(self, session_id: str, context: str, language: str) -> str:
        """Crée un entretien pour une offre existante.

        Args:
            session_id: Identifiant de l'offre parente.
            context: Contexte de l'entretien.
            language: Langue de l'entretien ('fr' ou 'en').

        Returns:
            L'identifiant unique de l'entretien créé.

        Raises:
            KeyError: Si l'offre n'existe pas.
            ValueError: Si la langue n'est pas 'fr' ou 'en'.
        """
        _validate_language(language)
        interview_id = str(uuid.uuid4())
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session introuvable : {session_id}")
            self._interviews[interview_id] = {
                "interview_id": interview_id,
                "session_id": session_id,
                "context": context,
                "language": language,
                "questions": [],
                "feedbacks": {},
                "created_at": datetime.now(UTC),
            }
        return interview_id

    def save_questions(self, interview_id: str, questions: list[str]) -> None:
        """Enregistre les questions générées pour un entretien.

        Args:
            interview_id: Identifiant de l'entretien.
            questions: Liste des questions d'entretien.

        Raises:
            KeyError: Si l'entretien n'existe pas.
        """
        with self._lock:
            if interview_id not in self._interviews:
                raise KeyError(f"Entretien introuvable : {interview_id}")
            self._interviews[interview_id]["questions"] = questions

    def get_interview(self, interview_id: str) -> dict[str, Any] | None:
        """Récupère un entretien par son identifiant.

        Args:
            interview_id: Identifiant de l'entretien.

        Returns:
            Copie de l'entretien ou None si introuvable.
        """
        with self._lock:
            itw = self._interviews.get(interview_id)
            if itw is None:
                return None
            return {
                **itw,
                "questions": list(itw["questions"]),
                "feedbacks": dict(itw["feedbacks"]),
            }

    def get_interview_with_session(self, interview_id: str) -> dict[str, Any] | None:
        """Récupère un entretien enrichi du CV et de l'offre parente.

        Args:
            interview_id: Identifiant de l'entretien.

        Returns:
            Dictionnaire de l'entretien avec `cv` et `job_offer`, ou None.
        """
        with self._lock:
            itw = self._interviews.get(interview_id)
            if itw is None:
                return None
            session = self._sessions.get(itw["session_id"])
            if session is None:
                return None
            return {
                **itw,
                "questions": list(itw["questions"]),
                "feedbacks": dict(itw["feedbacks"]),
                "cv": session["cv"],
                "job_offer": session["job_offer"],
            }

    def save_feedback(
        self,
        interview_id: str,
        question_index: int,
        feedback: dict[str, Any],
    ) -> None:
        """Enregistre le feedback d'une réponse pour une question donnée.

        Args:
            interview_id: Identifiant de l'entretien.
            question_index: Index de la question dans l'entretien.
            feedback: Données de feedback structurées.

        Raises:
            KeyError: Si l'entretien n'existe pas.
        """
        with self._lock:
            if interview_id not in self._interviews:
                raise KeyError(f"Entretien introuvable : {interview_id}")
            self._interviews[interview_id]["feedbacks"][question_index] = feedback

    def delete_interview(self, interview_id: str) -> None:
        """Supprime définitivement un entretien.

        Raises:
            KeyError: Si l'entretien n'existe pas.
        """
        with self._lock:
            if interview_id not in self._interviews:
                raise KeyError(f"Entretien introuvable : {interview_id}")
            del self._interviews[interview_id]


class SQLiteStorage:
    """Stockage SQLite des offres et entretiens d'entraînement."""

    def __init__(self, db_path: Path) -> None:
        """Initialise le stockage SQLite et crée/migre le schéma si nécessaire.

        Args:
            db_path: Chemin vers le fichier de base de données.
        """
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """Ouvre une connexion SQLite configurée avec WAL et clés étrangères.

        Returns:
            Connexion SQLite active.
        """
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
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
        """Crée le schéma s'il n'existe pas, et migre l'ancien schéma si besoin."""
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id   TEXT PRIMARY KEY,
                    offer_title  TEXT NOT NULL,
                    created_at   TEXT NOT NULL,
                    data         TEXT NOT NULL DEFAULT '{}',
                    archived     INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_created_at
                    ON sessions (created_at DESC);

                CREATE TABLE IF NOT EXISTS interviews (
                    interview_id TEXT PRIMARY KEY,
                    session_id   TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    context      TEXT NOT NULL,
                    language     TEXT NOT NULL CHECK (language IN ('fr', 'en')),
                    questions    TEXT NOT NULL DEFAULT '[]',
                    feedbacks    TEXT NOT NULL DEFAULT '{}',
                    created_at   TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_interviews_session
                    ON interviews (session_id);
            """)

            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if "language" in columns:
                self._migrate_legacy_schema(conn)

    def _migrate_legacy_schema(self, conn: sqlite3.Connection) -> None:
        """Migre l'ancien schéma (une session = un entretien) vers le nouveau.

        Pour chaque ancienne session : extrait le contexte du JSON `data`,
        crée une ligne `interviews` correspondante avec ses questions et
        feedbacks, met à jour `data` pour retirer le contexte, puis recrée
        la table `sessions` sans les colonnes obsolètes
        (language, questions, feedbacks).

        Important : la table `sessions` est recréée (DROP + RENAME) avant
        toute insertion dans `interviews`. Avec `PRAGMA foreign_keys=ON`,
        un `DROP TABLE` sur la table parente déclenche une suppression
        implicite de chacune de ses lignes, ce qui propagerait un
        `ON DELETE CASCADE` vers `interviews` si des lignes y existaient
        déjà — d'où l'ordre des opérations ci-dessous.

        Args:
            conn: Connexion SQLite active (transaction en cours).
        """
        rows = conn.execute(
            "SELECT session_id, language, data, questions, feedbacks, created_at "
            "FROM sessions"
        ).fetchall()

        # 1. Recrée la table sessions sans les colonnes obsolètes. Ce
        #    DROP TABLE doit précéder toute insertion dans `interviews`
        #    pour éviter une suppression en cascade (voir docstring).
        conn.executescript("""
            CREATE TABLE sessions_new (
                session_id   TEXT PRIMARY KEY,
                offer_title  TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                data         TEXT NOT NULL DEFAULT '{}',
                archived     INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO sessions_new (session_id, offer_title, created_at, data, archived)
                SELECT session_id, offer_title, created_at, data, archived FROM sessions;
            DROP TABLE sessions;
            ALTER TABLE sessions_new RENAME TO sessions;
            CREATE INDEX IF NOT EXISTS idx_sessions_created_at
                ON sessions (created_at DESC);
        """)

        # 2. Pour chaque ancienne session : crée l'entretien correspondant
        #    et nettoie le contexte du JSON `data` de la session.
        for row in rows:
            data = json.loads(row["data"])
            context = data.pop("context", "")
            interview_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO interviews
                    (interview_id, session_id, context, language, questions, feedbacks, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interview_id,
                    row["session_id"],
                    context,
                    row["language"],
                    row["questions"],
                    row["feedbacks"],
                    row["created_at"],
                ),
            )
            conn.execute(
                "UPDATE sessions SET data = ? WHERE session_id = ?",
                (json.dumps(data, ensure_ascii=False), row["session_id"]),
            )

    @staticmethod
    def _row_to_session(row: sqlite3.Row, interviews: list[dict[str, Any]]) -> dict[str, Any]:
        """Convertit une ligne SQL `sessions` en dictionnaire complet.

        Args:
            row: Ligne SQLite de la table sessions.
            interviews: Résumés des entretiens de cette offre.

        Returns:
            Dictionnaire session compatible avec InMemoryStorage.
        """
        data = json.loads(row["data"])
        return {
            "session_id": row["session_id"],
            "offer_title": row["offer_title"],
            "cv": data["cv"],
            "job_offer": data["job_offer"],
            "created_at": datetime.fromisoformat(row["created_at"]),
            "archived": bool(row["archived"]),
            "interviews": interviews,
        }

    @staticmethod
    def _row_to_interview(row: sqlite3.Row) -> dict[str, Any]:
        """Convertit une ligne SQL `interviews` en dictionnaire complet.

        Args:
            row: Ligne SQLite de la table interviews.

        Returns:
            Dictionnaire entretien compatible avec InMemoryStorage.
        """
        return {
            "interview_id": row["interview_id"],
            "session_id": row["session_id"],
            "context": row["context"],
            "language": row["language"],
            "questions": json.loads(row["questions"]),
            "feedbacks": _deserialize_feedbacks(row["feedbacks"]),
            "created_at": datetime.fromisoformat(row["created_at"]),
        }

    # -- Sessions (offres) ------------------------------------------------

    def create_session(self, cv: str, job_offer: str) -> str:
        """Crée une nouvelle offre (session) et retourne son identifiant.

        Args:
            cv: Contenu du CV du candidat.
            job_offer: Description de l'offre d'emploi.

        Returns:
            L'identifiant unique de la session créée.
        """
        session_id = str(uuid.uuid4())
        created_at_dt = datetime.now(UTC)
        created_at = created_at_dt.isoformat()
        offer_title = _build_offer_title(job_offer, created_at_dt)
        data_json = json.dumps({"cv": cv, "job_offer": job_offer}, ensure_ascii=False)

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions
                    (session_id, offer_title, created_at, data)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, offer_title, created_at, data_json),
            )
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Récupère une offre par son identifiant, avec ses entretiens.

        Args:
            session_id: Identifiant de la session.

        Returns:
            Dictionnaire de la session (avec liste `interviews`) ou None.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            interview_rows = conn.execute(
                """
                SELECT interview_id, context, language, questions, feedbacks, created_at
                FROM interviews
                WHERE session_id = ?
                ORDER BY created_at ASC
                """,
                (session_id,),
            ).fetchall()

        interviews = [
            {
                "interview_id": r["interview_id"],
                "context": r["context"],
                "language": r["language"],
                "question_count": len(json.loads(r["questions"])),
                "feedback_count": len(_deserialize_feedbacks(r["feedbacks"])),
                "created_at": datetime.fromisoformat(r["created_at"]),
            }
            for r in interview_rows
        ]
        return self._row_to_session(row, interviews)

    def get_all_sessions(self, archived: bool = False) -> list[dict[str, Any]]:
        """Retourne la liste des offres, triées par date décroissante.

        Args:
            archived: Si True, retourne les offres archivées.

        Returns:
            Liste de résumés d'offres avec le nombre d'entretiens.
        """
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT s.session_id, s.offer_title, s.created_at,
                       COUNT(i.interview_id) AS interview_count
                FROM sessions s
                LEFT JOIN interviews i ON i.session_id = s.session_id
                WHERE s.archived = ?
                GROUP BY s.session_id
                ORDER BY s.created_at DESC
                """,
                (1 if archived else 0,),
            ).fetchall()

        return [
            {
                "session_id": row["session_id"],
                "offer_title": row["offer_title"],
                "interview_count": row["interview_count"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def update_offer_title(self, session_id: str, title: str) -> None:
        """Met à jour le titre d'une offre."""
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET offer_title = ? WHERE session_id = ?",
                (title, session_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Session introuvable : {session_id}")

    def update_offer_content(self, session_id: str, cv: str, job_offer: str) -> None:
        """Met à jour le CV et l'offre d'emploi d'une session."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT data FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Session introuvable : {session_id}")
            data = json.loads(row["data"])
            data["cv"] = cv
            data["job_offer"] = job_offer
            conn.execute(
                "UPDATE sessions SET data = ? WHERE session_id = ?",
                (json.dumps(data, ensure_ascii=False), session_id),
            )

    def archive_session(self, session_id: str) -> None:
        """Archive une offre."""
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET archived = 1 WHERE session_id = ?",
                (session_id,),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Session introuvable : {session_id}")

    def unarchive_session(self, session_id: str) -> None:
        """Désarchive une offre."""
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET archived = 0 WHERE session_id = ?",
                (session_id,),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Session introuvable : {session_id}")

    def delete_session(self, session_id: str) -> None:
        """Supprime définitivement une offre et ses entretiens (cascade FK)."""
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Session introuvable : {session_id}")

    # -- Interviews ---------------------------------------------------------

    def create_interview(self, session_id: str, context: str, language: str) -> str:
        """Crée un entretien pour une offre existante.

        Args:
            session_id: Identifiant de l'offre parente.
            context: Contexte de l'entretien.
            language: Langue de l'entretien ('fr' ou 'en').

        Returns:
            L'identifiant unique de l'entretien créé.

        Raises:
            KeyError: Si l'offre n'existe pas.
            ValueError: Si la langue n'est pas 'fr' ou 'en'.
        """
        _validate_language(language)
        interview_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()
        with self._connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if exists is None:
                raise KeyError(f"Session introuvable : {session_id}")
            conn.execute(
                """
                INSERT INTO interviews
                    (interview_id, session_id, context, language, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (interview_id, session_id, context, language, created_at),
            )
        return interview_id

    def save_questions(self, interview_id: str, questions: list[str]) -> None:
        """Enregistre les questions générées pour un entretien.

        Args:
            interview_id: Identifiant de l'entretien.
            questions: Liste des questions d'entretien.

        Raises:
            KeyError: Si l'entretien n'existe pas.
        """
        questions_json = json.dumps(questions, ensure_ascii=False)
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE interviews SET questions = ? WHERE interview_id = ?",
                (questions_json, interview_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Entretien introuvable : {interview_id}")

    def get_interview(self, interview_id: str) -> dict[str, Any] | None:
        """Récupère un entretien par son identifiant.

        Args:
            interview_id: Identifiant de l'entretien.

        Returns:
            Dictionnaire de l'entretien ou None si introuvable.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM interviews WHERE interview_id = ?",
                (interview_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_interview(row)

    def get_interview_with_session(self, interview_id: str) -> dict[str, Any] | None:
        """Récupère un entretien enrichi du CV et de l'offre parente.

        Args:
            interview_id: Identifiant de l'entretien.

        Returns:
            Dictionnaire de l'entretien avec `cv` et `job_offer`, ou None.
        """
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT i.*, s.data AS session_data
                FROM interviews i
                JOIN sessions s ON s.session_id = i.session_id
                WHERE i.interview_id = ?
                """,
                (interview_id,),
            ).fetchone()
        if row is None:
            return None
        interview = self._row_to_interview(row)
        session_data = json.loads(row["session_data"])
        interview["cv"] = session_data["cv"]
        interview["job_offer"] = session_data["job_offer"]
        return interview

    def save_feedback(
        self,
        interview_id: str,
        question_index: int,
        feedback: dict[str, Any],
    ) -> None:
        """Enregistre le feedback via json_set atomique SQLite.

        Args:
            interview_id: Identifiant de l'entretien.
            question_index: Index de la question dans l'entretien.
            feedback: Données de feedback structurées.

        Raises:
            KeyError: Si l'entretien n'existe pas.
        """
        feedback_json = json.dumps(feedback, ensure_ascii=False)
        key = str(question_index)
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE interviews
                SET feedbacks = json_set(feedbacks, '$.' || ?, json(?))
                WHERE interview_id = ?
                """,
                (key, feedback_json, interview_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Entretien introuvable : {interview_id}")

    def delete_interview(self, interview_id: str) -> None:
        """Supprime définitivement un entretien.

        Raises:
            KeyError: Si l'entretien n'existe pas.
        """
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM interviews WHERE interview_id = ?",
                (interview_id,),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Entretien introuvable : {interview_id}")


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
