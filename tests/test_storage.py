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


def test_session_progress_counts(store):
    sid = store.create_session(cv="CV", job_offer="Offre")
    iid = store.create_interview(sid, context="RH", language="fr")
    store.save_questions(iid, ["Q1", "Q2", "Q3"])
    store.save_feedback(iid, 0, {"score": 8})
    session = store.get_session(sid)
    itw = session["interviews"][0]
    assert itw["question_count"] == 3
    assert itw["feedback_count"] == 1


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
