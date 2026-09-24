"""Tests for the storage layer with multi-interview support."""
import pytest

from services.storage import InMemoryStorage, SQLiteStorage


@pytest.fixture()
def store():
    return InMemoryStorage()


def test_create_session_returns_id(store):
    sid = store.create_session(cv="Mon CV", job_offer="Offre Python")
    assert isinstance(sid, str)
    assert len(sid) == 36  # UUID


def test_get_session_returns_offer_with_interviews_list(store):
    sid = store.create_session(cv="CV", job_offer="Offre")
    session = store.get_session(sid)
    assert session["cv"] == "CV"
    assert session["job_offer"] == "Offre"
    assert session["interviews"] == []
    assert "offer_title" in session


def test_create_interview_and_list(store):
    sid = store.create_session(cv="CV", job_offer="Offre")
    iid = store.create_interview(sid, context="Screening RH", language="fr")
    assert isinstance(iid, str)
    session = store.get_session(sid)
    assert len(session["interviews"]) == 1
    assert session["interviews"][0]["context"] == "Screening RH"
    assert session["interviews"][0]["language"] == "fr"


def test_create_interview_unknown_session(store):
    with pytest.raises(KeyError):
        store.create_interview("unknown", context="RH", language="fr")


def test_save_questions_and_get_interview(store):
    sid = store.create_session(cv="CV", job_offer="Offre")
    iid = store.create_interview(sid, context="Tech", language="en")
    store.save_questions(iid, ["Q1", "Q2"])
    interview = store.get_interview(iid)
    assert interview["questions"] == ["Q1", "Q2"]
    assert interview["feedbacks"] == {}


def test_save_feedback(store):
    sid = store.create_session(cv="CV", job_offer="Offre")
    iid = store.create_interview(sid, context="Tech", language="en")
    store.save_questions(iid, ["Q1"])
    store.save_feedback(iid, 0, {"score": 8})
    interview = store.get_interview(iid)
    assert interview["feedbacks"][0] == {"score": 8}


def test_get_interview_with_session(store):
    sid = store.create_session(cv="Mon CV", job_offer="Mon offre")
    iid = store.create_interview(sid, context="RH", language="fr")
    result = store.get_interview_with_session(iid)
    assert result["cv"] == "Mon CV"
    assert result["job_offer"] == "Mon offre"
    assert result["context"] == "RH"


def test_delete_interview(store):
    sid = store.create_session(cv="CV", job_offer="Offre")
    iid = store.create_interview(sid, context="RH", language="fr")
    store.delete_interview(iid)
    assert store.get_interview(iid) is None
    session = store.get_session(sid)
    assert len(session["interviews"]) == 0


def test_delete_session_cascades_interviews(store):
    sid = store.create_session(cv="CV", job_offer="Offre")
    iid = store.create_interview(sid, context="RH", language="fr")
    store.delete_session(sid)
    assert store.get_session(sid) is None
    assert store.get_interview(iid) is None


def test_get_all_sessions_shows_interview_count(store):
    sid = store.create_session(cv="CV", job_offer="Offre")
    store.create_interview(sid, context="RH", language="fr")
    store.create_interview(sid, context="Tech", language="en")
    sessions = store.get_all_sessions()
    assert sessions[0]["interview_count"] == 2


def test_update_offer_content(store):
    sid = store.create_session(cv="CV brut", job_offer="Offre brute")
    store.update_offer_content(sid, cv="# CV", job_offer="# Offre")
    session = store.get_session(sid)
    assert session["cv"] == "# CV"
    assert session["job_offer"] == "# Offre"


def test_update_offer_content_unknown_session(store):
    with pytest.raises(KeyError):
        store.update_offer_content("unknown", cv="CV", job_offer="Offre")


def test_session_progress_counts(store):
    sid = store.create_session(cv="CV", job_offer="Offre")
    iid = store.create_interview(sid, context="RH", language="fr")
    store.save_questions(iid, ["Q1", "Q2", "Q3"])
    store.save_feedback(iid, 0, {"score": 8})
    session = store.get_session(sid)
    itw = session["interviews"][0]
    assert itw["question_count"] == 3
    assert itw["feedback_count"] == 1


def test_speech_stats_defaults_to_none(store):
    sid = store.create_session(cv="CV", job_offer="Offre")
    iid = store.create_interview(sid, context="RH", language="fr")
    assert store.get_interview(iid)["speech_stats"] is None


def test_save_speech_stats(store):
    sid = store.create_session(cv="CV", job_offer="Offre")
    iid = store.create_interview(sid, context="RH", language="fr")
    speech_stats = {"tics": [{"phrase": "du coup", "count": 3}], "filler_totals": {"euh": 2}, "advice": "Conseil."}
    store.save_speech_stats(iid, speech_stats)
    assert store.get_interview(iid)["speech_stats"] == speech_stats


def test_save_speech_stats_unknown_interview_raises(store):
    with pytest.raises(KeyError):
        store.save_speech_stats("unknown", {"tics": [], "filler_totals": {}, "advice": ""})


@pytest.fixture()
def sqlite_store(tmp_path):
    return SQLiteStorage(tmp_path / "test.db")


def test_sqlite_create_session(sqlite_store):
    sid = sqlite_store.create_session(cv="CV", job_offer="Offre")
    session = sqlite_store.get_session(sid)
    assert session["cv"] == "CV"
    assert session["interviews"] == []


def test_sqlite_interview_lifecycle(sqlite_store):
    sid = sqlite_store.create_session(cv="CV", job_offer="Offre")
    iid = sqlite_store.create_interview(sid, "Tech", "en")
    sqlite_store.save_questions(iid, ["Q1", "Q2"])
    sqlite_store.save_feedback(iid, 0, {"score": 9})
    itw = sqlite_store.get_interview(iid)
    assert itw["questions"] == ["Q1", "Q2"]
    assert itw["feedbacks"][0] == {"score": 9}


def test_sqlite_delete_session_cascades(sqlite_store):
    sid = sqlite_store.create_session(cv="CV", job_offer="Offre")
    iid = sqlite_store.create_interview(sid, "RH", "fr")
    sqlite_store.delete_session(sid)
    assert sqlite_store.get_interview(iid) is None


def test_sqlite_get_interview_with_session(sqlite_store):
    sid = sqlite_store.create_session(cv="Mon CV", job_offer="Mon offre")
    iid = sqlite_store.create_interview(sid, "RH", "fr")
    result = sqlite_store.get_interview_with_session(iid)
    assert result["cv"] == "Mon CV"
    assert result["context"] == "RH"


def test_sqlite_update_offer_content(sqlite_store):
    sid = sqlite_store.create_session(cv="CV brut", job_offer="Offre brute")
    sqlite_store.update_offer_content(sid, cv="# CV", job_offer="# Offre")
    session = sqlite_store.get_session(sid)
    assert session["cv"] == "# CV"
    assert session["job_offer"] == "# Offre"


def test_sqlite_update_offer_content_unknown_session(sqlite_store):
    with pytest.raises(KeyError):
        sqlite_store.update_offer_content("unknown", cv="CV", job_offer="Offre")


def test_sqlite_speech_stats_defaults_to_none(sqlite_store):
    sid = sqlite_store.create_session(cv="CV", job_offer="Offre")
    iid = sqlite_store.create_interview(sid, "RH", "fr")
    assert sqlite_store.get_interview(iid)["speech_stats"] is None


def test_sqlite_save_speech_stats(sqlite_store):
    sid = sqlite_store.create_session(cv="CV", job_offer="Offre")
    iid = sqlite_store.create_interview(sid, "RH", "fr")
    speech_stats = {"tics": [{"phrase": "du coup", "count": 3}], "filler_totals": {"euh": 2}, "advice": "Conseil."}
    sqlite_store.save_speech_stats(iid, speech_stats)
    assert sqlite_store.get_interview(iid)["speech_stats"] == speech_stats


def test_sqlite_save_speech_stats_unknown_interview_raises(sqlite_store):
    with pytest.raises(KeyError):
        sqlite_store.save_speech_stats("unknown", {"tics": [], "filler_totals": {}, "advice": ""})


def test_sqlite_migrates_existing_interviews_table_without_speech_stats(tmp_path):
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE sessions (
            session_id   TEXT PRIMARY KEY,
            offer_title  TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            data         TEXT NOT NULL DEFAULT '{}',
            archived     INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE interviews (
            interview_id TEXT PRIMARY KEY,
            session_id   TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            context      TEXT NOT NULL,
            language     TEXT NOT NULL CHECK (language IN ('fr', 'en')),
            questions    TEXT NOT NULL DEFAULT '[]',
            feedbacks    TEXT NOT NULL DEFAULT '{}',
            created_at   TEXT NOT NULL
        )
        """
    )
    conn.execute("INSERT INTO sessions VALUES ('s1', 'Test Offer', '2026-01-01T00:00:00', '{}', 0)")
    conn.execute(
        "INSERT INTO interviews (interview_id, session_id, context, language, created_at) "
        "VALUES ('i1', 's1', 'RH', 'fr', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    store = SQLiteStorage(db_path)

    interview = store.get_interview("i1")
    assert interview is not None
    assert interview["speech_stats"] is None
