"""Test that existing single-interview databases migrate correctly."""
import json
import sqlite3
from pathlib import Path

from services.storage import SQLiteStorage


def _create_old_schema_db(db_path: Path) -> str:
    """Create a DB with the old schema and one session, return its session_id."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE sessions (
            session_id   TEXT PRIMARY KEY,
            offer_title  TEXT NOT NULL,
            language     TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            data         TEXT NOT NULL DEFAULT '{}',
            questions    TEXT NOT NULL DEFAULT '[]',
            feedbacks    TEXT NOT NULL DEFAULT '{}',
            archived     INTEGER NOT NULL DEFAULT 0
        );
    """)
    session_id = "test-old-session-001"
    data_json = json.dumps({"cv": "Old CV", "job_offer": "Old Offer", "context": "Entretien RH"})
    questions_json = json.dumps(["Q1 old", "Q2 old"])
    feedbacks_json = json.dumps({"0": {"score": 7}})
    conn.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, "Old Title", "fr", "2026-01-01T00:00:00", data_json, questions_json, feedbacks_json, 0),
    )
    conn.commit()
    conn.close()
    return session_id


def test_migration_creates_interview_from_old_session(tmp_path):
    db_path = tmp_path / "migrate.db"
    old_sid = _create_old_schema_db(db_path)

    storage = SQLiteStorage(db_path)

    session = storage.get_session(old_sid)
    assert session is not None
    assert session["cv"] == "Old CV"
    assert len(session["interviews"]) == 1

    itw = session["interviews"][0]
    assert itw["question_count"] == 2
    assert itw["feedback_count"] == 1

    interview = storage.get_interview(itw["interview_id"])
    assert interview["context"] == "Entretien RH"
    assert interview["language"] == "fr"
    assert interview["questions"] == ["Q1 old", "Q2 old"]
    assert interview["feedbacks"][0] == {"score": 7}


def test_migration_removes_context_from_data(tmp_path):
    db_path = tmp_path / "migrate.db"
    old_sid = _create_old_schema_db(db_path)

    SQLiteStorage(db_path)

    # Read the DB directly to check the data JSON column
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT data FROM sessions WHERE session_id = ?", (old_sid,)).fetchone()
    conn.close()
    data = json.loads(row[0])
    assert "context" not in data
    assert "cv" in data
    assert "job_offer" in data
