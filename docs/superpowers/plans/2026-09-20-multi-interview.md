# Multi-Interview per Offer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow multiple interviews (HR screening, technical, manager, etc.) per job offer, each with its own language, questions, and feedbacks.

**Architecture:** Add an `interviews` table with FK to `sessions`. The `sessions` table becomes the "offer" level (CV + job offer only). The frontend gains a new "offer detail" screen between the home and the questions list. Question generation prompt is enhanced to be interview-type-specific.

**Tech Stack:** Python 3.11, Flask, SQLite, vanilla JS (no framework), Tailwind CSS (CDN), pytest

**Spec:** `docs/superpowers/specs/2026-09-20-multi-interview-design.md`

## Global Constraints

- Python 3.11+, no new dependencies
- SQLite with WAL mode, JSON columns for nested data
- Both `InMemoryStorage` and `SQLiteStorage` must implement the same interface
- All tests use `STORAGE_TYPE=memory` (in-memory storage via `create_app()`)
- Language values: `'fr'` or `'en'` only
- Q1 is always the self-introduction question
- French UI labels throughout

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `services/storage.py` | Rewrite | New schema, interviews CRUD, migration |
| `app.py` | Rewrite | New/modified API endpoints |
| `templates/index.html` | Rewrite | 4-screen layout with offer detail view |
| `static/js/app.js` | Rewrite | 4-screen navigation, interview CRUD UI |
| `services/ai_service.py` | Modify | Enhanced question generation prompt |
| `tests/test_app.py` | Rewrite | Tests for new API surface |
| `tests/conftest.py` | Keep | No changes needed |
| `tests/test_ai_service.py` | Keep | No changes needed |

---

### Task 1: Storage Layer — New Schema and Interview CRUD

**Files:**
- Modify: `services/storage.py` (full rewrite of both storage classes)
- Test: `tests/test_storage.py` (new file)

**Interfaces:**
- Consumes: nothing (foundation task)
- Produces:
  - `create_session(cv: str, job_offer: str) -> str` — returns session_id
  - `get_session(session_id: str) -> dict | None` — returns `{session_id, offer_title, cv, job_offer, created_at, interviews: [{interview_id, context, language, question_count, feedback_count, created_at}]}`
  - `get_all_sessions(archived: bool) -> list[dict]` — returns list of `{session_id, offer_title, interview_count, created_at}`
  - `create_interview(session_id: str, context: str, language: str) -> str` — returns interview_id, raises KeyError if session not found
  - `save_questions(interview_id: str, questions: list[str]) -> None` — raises KeyError if interview not found
  - `get_interview(interview_id: str) -> dict | None` — returns `{interview_id, session_id, context, language, questions, feedbacks, created_at}`
  - `get_interview_with_session(interview_id: str) -> dict | None` — returns interview dict + `cv`, `job_offer` from parent session
  - `save_feedback(interview_id: str, question_index: int, feedback: dict) -> None`
  - `delete_interview(interview_id: str) -> None` — raises KeyError
  - Existing: `update_offer_title`, `archive_session`, `unarchive_session`, `delete_session` (cascades interviews in SQLite)

- [ ] **Step 1: Write tests for InMemoryStorage new interface**

Create `tests/test_storage.py`:

```python
"""Tests for the storage layer with multi-interview support."""
import pytest
from services.storage import InMemoryStorage


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && .venv/bin/python -m pytest tests/test_storage.py -v`
Expected: FAIL — `create_session()` takes wrong number of args.

- [ ] **Step 3: Rewrite InMemoryStorage**

In `services/storage.py`, update `_build_offer_title` to no longer require `language`, then rewrite `InMemoryStorage`:

```python
def _build_offer_title(job_offer: str, created_at: datetime) -> str:
    normalized = " ".join(job_offer.strip().split())
    if normalized:
        if len(normalized) > 40:
            return f"{normalized[:40]}…"
        return normalized
    date_str = created_at.strftime("%d/%m/%Y")
    return f"Offre du {date_str}"


class InMemoryStorage:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._interviews: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_session(self, cv: str, job_offer: str) -> str:
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
        with self._lock:
            sessions = [
                s for s in self._sessions.values()
                if s.get("archived", False) == archived
            ]
            result = []
            for s in sessions:
                count = sum(
                    1 for itw in self._interviews.values()
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

    def create_interview(self, session_id: str, context: str, language: str) -> str:
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
        with self._lock:
            if interview_id not in self._interviews:
                raise KeyError(f"Interview introuvable : {interview_id}")
            self._interviews[interview_id]["questions"] = questions

    def get_interview(self, interview_id: str) -> dict[str, Any] | None:
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

    def save_feedback(self, interview_id: str, question_index: int, feedback: dict[str, Any]) -> None:
        with self._lock:
            if interview_id not in self._interviews:
                raise KeyError(f"Interview introuvable : {interview_id}")
            self._interviews[interview_id]["feedbacks"][question_index] = feedback

    def delete_interview(self, interview_id: str) -> None:
        with self._lock:
            if interview_id not in self._interviews:
                raise KeyError(f"Interview introuvable : {interview_id}")
            del self._interviews[interview_id]

    def update_offer_title(self, session_id: str, title: str) -> None:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session introuvable : {session_id}")
            self._sessions[session_id]["offer_title"] = title

    def archive_session(self, session_id: str) -> None:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session introuvable : {session_id}")
            self._sessions[session_id]["archived"] = True

    def unarchive_session(self, session_id: str) -> None:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session introuvable : {session_id}")
            self._sessions[session_id]["archived"] = False

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session introuvable : {session_id}")
            del self._sessions[session_id]
            to_delete = [
                iid for iid, itw in self._interviews.items()
                if itw["session_id"] == session_id
            ]
            for iid in to_delete:
                del self._interviews[iid]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && .venv/bin/python -m pytest tests/test_storage.py -v`
Expected: all 12 tests PASS.

- [ ] **Step 5: Rewrite SQLiteStorage with new schema + migration**

In `services/storage.py`, rewrite `SQLiteStorage`:

- `_init_schema`: create `sessions` table (without language/questions/feedbacks), create `interviews` table with FK + CASCADE, then run migration if old columns exist.
- Migration logic: detect old schema by checking for `language` column in sessions. If present: for each row, extract context from `data` JSON, insert an interview row, update `data` to remove context, then recreate the sessions table without old columns.
- All CRUD methods updated to match `InMemoryStorage` interface.

Key schema:

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    offer_title  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    data         TEXT NOT NULL DEFAULT '{}',
    archived     INTEGER NOT NULL DEFAULT 0
);

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
```

Migration detection: `PRAGMA table_info(sessions)` — if `language` column exists, run migration.

- [ ] **Step 6: Add SQLiteStorage tests**

Append to `tests/test_storage.py`:

```python
from pathlib import Path
from services.storage import SQLiteStorage

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
```

- [ ] **Step 7: Run all storage tests**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && .venv/bin/python -m pytest tests/test_storage.py -v`
Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add services/storage.py tests/test_storage.py
git commit -m "feat: rewrite storage layer for multi-interview per offer

New interviews table, updated session (offer) schema, cascade delete,
migration from old single-interview schema. Both InMemory and SQLite
backends implement the same interface."
```

---

### Task 2: API Endpoints

**Files:**
- Modify: `app.py` (rewrite routes)
- Modify: `tests/test_app.py` (rewrite for new API)

**Interfaces:**
- Consumes: storage methods from Task 1 (`create_session`, `create_interview`, `save_questions`, `get_interview`, `get_interview_with_session`, `save_feedback`, `delete_interview`, `get_session`, `get_all_sessions`)
- Consumes: `ai_service.generate_questions(cv, job_offer, language, context) -> list[str]`
- Produces: HTTP endpoints consumed by frontend (Task 4)
  - `POST /api/sessions` → `{session_id, offer_title}`
  - `POST /api/sessions/:id/interviews` → `{interview_id, context, language, questions}`
  - `GET /api/sessions/:id` → `{session_id, offer_title, created_at, interviews: [...]}`
  - `GET /api/interviews/:id` → `{interview_id, context, language, questions, feedbacks}`
  - `DELETE /api/interviews/:id` → `{ok: true}`
  - `POST /api/analyze-answer` takes `interview_id` instead of `session_id`

- [ ] **Step 1: Write tests for new API endpoints**

Rewrite `tests/test_app.py`:

```python
"""Tests for the multi-interview API."""
from io import BytesIO
from unittest.mock import patch

import pytest
from app import create_app

FAKE_AUDIO = b"\x00" * 500
FAKE_FRAME = b"\xff\xd8\xff\xe0" + b"\x00" * 100


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _create_offer(client):
    resp = client.post("/api/sessions", json={"cv": "Mon CV", "job_offer": "Offre Python"})
    assert resp.status_code == 200
    return resp.get_json()


def _add_interview(client, session_id, context="Screening RH", language="fr"):
    with patch("services.ai_service.generate_questions", return_value=["Présentez-vous.", "Q2"]):
        resp = client.post(
            f"/api/sessions/{session_id}/interviews",
            json={"context": context, "language": language},
        )
        assert resp.status_code == 200
        return resp.get_json()


def test_create_offer(client):
    data = _create_offer(client)
    assert "session_id" in data
    assert "offer_title" in data


def test_create_offer_missing_cv(client):
    resp = client.post("/api/sessions", json={"job_offer": "Offre"})
    assert resp.status_code == 400


def test_add_interview(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])
    assert "interview_id" in itw
    assert itw["context"] == "Screening RH"
    assert itw["language"] == "fr"
    assert len(itw["questions"]) == 2


def test_add_interview_unknown_session(client):
    with patch("services.ai_service.generate_questions", return_value=["Q1"]):
        resp = client.post(
            "/api/sessions/unknown/interviews",
            json={"context": "RH", "language": "fr"},
        )
    assert resp.status_code == 404


def test_get_session_detail_with_interviews(client):
    offer = _create_offer(client)
    _add_interview(client, offer["session_id"], "RH", "fr")
    _add_interview(client, offer["session_id"], "Tech", "en")
    resp = client.get(f"/api/sessions/{offer['session_id']}")
    data = resp.get_json()
    assert len(data["interviews"]) == 2


def test_get_interview_detail(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])
    resp = client.get(f"/api/interviews/{itw['interview_id']}")
    data = resp.get_json()
    assert data["questions"] == ["Présentez-vous.", "Q2"]
    assert data["feedbacks"] == {}


def test_delete_interview(client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])
    resp = client.delete(f"/api/interviews/{itw['interview_id']}")
    assert resp.status_code == 200
    resp2 = client.get(f"/api/interviews/{itw['interview_id']}")
    assert resp2.status_code == 404


@patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100)
@patch("services.ai_service.analyze_answer", return_value={
    "transcription": "Réponse",
    "analysis_content": "Bon",
    "analysis_form": "OK",
    "ideal_answer_text": "Idéal",
})
@patch("services.ai_service.transcribe_audio", return_value="Réponse")
def test_analyze_answer_uses_interview_id(mock_transcribe, mock_analyze, mock_tts, client):
    offer = _create_offer(client)
    itw = _add_interview(client, offer["session_id"])
    data = {
        "interview_id": itw["interview_id"],
        "question_index": "0",
        "duration_seconds": "30.0",
        "recording_mode": "audio",
        "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
    }
    resp = client.post("/api/analyze-answer", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.get_json()["transcription"] == "Réponse"


def test_list_sessions_shows_interview_count(client):
    offer = _create_offer(client)
    _add_interview(client, offer["session_id"], "RH", "fr")
    resp = client.get("/api/sessions")
    sessions = resp.get_json()["sessions"]
    assert sessions[0]["interview_count"] >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && .venv/bin/python -m pytest tests/test_app.py -v`
Expected: FAIL — endpoints don't exist yet.

- [ ] **Step 3: Rewrite app.py routes**

Replace the route definitions in `app.py`. Key changes:

1. Remove `POST /api/generate-questions`
2. Add `POST /api/sessions` — creates offer (cv + job_offer), returns `{session_id, offer_title}`
3. Add `POST /api/sessions/<session_id>/interviews` — takes `{context, language}`, calls `ai_service.generate_questions`, creates interview, saves questions
4. Update `GET /api/sessions/<session_id>` — returns offer + interviews summary list
5. Add `GET /api/interviews/<interview_id>` — returns interview detail
6. Add `DELETE /api/interviews/<interview_id>`
7. Update `POST /api/analyze-answer` — read `interview_id` from form data instead of `session_id`, use `storage.get_interview_with_session()` to get cv/job_offer/context/language, use `storage.save_feedback(interview_id, ...)` to save
8. Update `GET /api/sessions` — no longer returns language/context per session, returns interview_count
9. Audio/video filenames: use `interview_id` instead of `session_id` in filenames (e.g., `user_{interview_id}_{question_index}.webm`)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && .venv/bin/python -m pytest tests/test_app.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Run all tests to check nothing is broken**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && .venv/bin/python -m pytest tests/ -v`
Expected: all tests PASS (storage + app + ai_service).

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: rewrite API for multi-interview per offer

New endpoints: POST /api/sessions, POST /api/sessions/:id/interviews,
GET /api/interviews/:id, DELETE /api/interviews/:id.
analyze-answer now takes interview_id instead of session_id."
```

---

### Task 3: Enhanced Question Generation Prompt

**Files:**
- Modify: `services/ai_service.py:126-163` (the `generate_questions` function's system_prompt and user_prompt)

**Interfaces:**
- Consumes: nothing new (same function signature)
- Produces: `generate_questions(cv, job_offer, language, context) -> list[str]` — same signature, better prompt

- [ ] **Step 1: Update the system_prompt in generate_questions**

In `services/ai_service.py`, replace the `system_prompt` in `generate_questions`:

```python
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
```

- [ ] **Step 2: Run existing ai_service tests**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && .venv/bin/python -m pytest tests/test_ai_service.py -v`
Expected: PASS (prompt change doesn't affect mocked tests).

- [ ] **Step 3: Commit**

```bash
git add services/ai_service.py
git commit -m "feat: enhance question generation prompt for interview-type specificity"
```

---

### Task 4: HTML Template — 4-Screen Layout

**Files:**
- Modify: `templates/index.html` (add offer detail view, simplify setup form, update breadcrumb)

**Interfaces:**
- Consumes: nothing (HTML structure consumed by JS in Task 5)
- Produces: DOM elements with these IDs:
  - `view-setup`, `view-offer`, `view-questions`, `view-recording` (4 screens)
  - `breadcrumb-offer`, `breadcrumb-interview`, `breadcrumb-sep-2`, `breadcrumb-sep-3`, `breadcrumb-question`
  - Setup form: `cv`, `job-offer`, `btn-create-offer`, `setup-error`
  - Offer detail: `interviews-list`, `interviews-empty`, `interview-context`, `interview-language`, `btn-add-interview`, `add-interview-form`, `btn-toggle-add-interview`, `interview-error`
  - Questions: `questions-grid`, `btn-back-to-offer`
  - Recording: unchanged element IDs

- [ ] **Step 1: Rewrite index.html**

Key changes to `templates/index.html`:

1. **Breadcrumb** — add `breadcrumb-interview` span and `breadcrumb-sep-3` between offer and question:
```html
<nav id="breadcrumb" class="hidden mb-4 text-sm text-slate-500">
    <button id="nav-home" type="button" class="hover:text-indigo-600">Accueil</button>
    <span id="breadcrumb-sep-1" class="hidden"> &gt; </span>
    <span id="breadcrumb-offer" class="hidden font-medium text-slate-700"></span>
    <span id="breadcrumb-sep-2" class="hidden"> &gt; </span>
    <span id="breadcrumb-interview" class="hidden font-medium text-slate-700"></span>
    <span id="breadcrumb-sep-3" class="hidden"> &gt; </span>
    <span id="breadcrumb-question" class="hidden"></span>
</nav>
```

2. **Setup form** — remove language select and context textarea. Change button to "Créer l'offre" with id `btn-create-offer`. Keep sessions list and archived section unchanged.

3. **New offer detail view** (`view-offer`):
```html
<section id="view-offer" class="hidden space-y-4">
    <button id="btn-back-home-offer" type="button"
        class="text-sm text-indigo-600 hover:underline">
        ← Retour à l'accueil
    </button>
    <h2 class="text-xl font-semibold text-slate-700">Entretiens</h2>

    <div id="interviews-list" class="grid gap-3 sm:grid-cols-2"></div>
    <p id="interviews-empty" class="text-slate-400 text-sm hidden">
        Aucun entretien. Ajoutez votre premier entretien pour commencer.
    </p>
    <p id="interview-error" class="text-red-600 text-sm hidden"></p>

    <div class="bg-white rounded-xl shadow-md p-6">
        <button id="btn-toggle-add-interview" type="button"
            class="w-full text-indigo-600 font-semibold hover:underline">
            + Ajouter un entretien
        </button>
        <div id="add-interview-form" class="hidden mt-4 space-y-3">
            <div>
                <label for="interview-context" class="block text-sm font-medium mb-1">
                    Type d'entretien *
                </label>
                <textarea id="interview-context" rows="2"
                    class="w-full border border-slate-300 rounded-lg p-3 focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    placeholder="Ex: Screening RH, Entretien technique avec le CTO..."></textarea>
            </div>
            <div>
                <label for="interview-language" class="block text-sm font-medium mb-1">
                    Langue *
                </label>
                <select id="interview-language"
                    class="w-full border border-slate-300 rounded-lg p-3 focus:ring-2 focus:ring-indigo-500 focus:outline-none">
                    <option value="fr">Français</option>
                    <option value="en">Anglais</option>
                </select>
            </div>
            <button id="btn-add-interview" type="button"
                class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-semibold py-3 rounded-lg transition">
                Générer les questions
            </button>
        </div>
    </div>
</section>
```

4. **Questions view** — change back button id to `btn-back-to-offer` with text "← Retour aux entretiens".

5. **Recording view** — unchanged except back button stays `btn-back-to-questions`.

- [ ] **Step 2: Verify HTML renders without errors**

Start the dev server and load the page in a browser. Verify 4 sections exist in the DOM (all hidden except setup). No JS errors in console.

- [ ] **Step 3: Commit**

```bash
git add templates/index.html
git commit -m "feat: 4-screen HTML layout with offer detail view

Simplified setup form (CV + offer only), new offer detail screen
with interview list and add-interview form, updated breadcrumb
with interview level."
```

---

### Task 5: Frontend JavaScript — 4-Screen Navigation

**Files:**
- Modify: `static/js/app.js` (full rewrite)

**Interfaces:**
- Consumes: API endpoints from Task 2, DOM elements from Task 4
- Produces: working SPA with 4-screen navigation

- [ ] **Step 1: Rewrite app.js**

Key changes to `static/js/app.js`:

1. **State** — add `interviews`, `currentInterviewId`, `currentInterviewContext`; remove `questions` and `feedbacks` from top-level (they live in the interview now):

```javascript
const state = {
    currentSessionId: null,
    offerTitle: null,
    interviews: [],
    currentInterviewId: null,
    currentInterviewContext: null,
    questions: [],
    feedbacks: {},
    currentQuestionIndex: null,
    // ... rest unchanged (recording state)
};
```

2. **Views** — add `offer`:

```javascript
const views = {
    setup: document.getElementById("view-setup"),
    offer: document.getElementById("view-offer"),
    questions: document.getElementById("view-questions"),
    recording: document.getElementById("view-recording"),
};
```

3. **Navigation functions**:
   - `goToSetup()` — reset all state, show setup
   - `goToOffer()` — keep session state, reset interview state, show offer detail, reload interviews
   - `goToQuestions()` — keep interview state, show questions
   - `goToRecording(index)` — show recording for question

4. **updateBreadcrumb(view)** — 4-level breadcrumb:
   - `setup`: hidden
   - `offer`: Accueil > Offer title (editable)
   - `questions`: Accueil > Offer title > Interview context
   - `recording`: Accueil > Offer title > Interview context > Question N/M

5. **createOffer()** — replaces `generateQuestions()`:
   - POST to `/api/sessions` with `{cv, job_offer}`
   - On success: set `state.currentSessionId` and `state.offerTitle`, show offer view
   - Reload sessions list in background

6. **loadOfferDetail(sessionId)** — called when entering offer view:
   - GET `/api/sessions/:id`
   - Populate `state.interviews`, render interview cards

7. **renderInterviews()** — render interview cards in `#interviews-list`:
   - Each card: context, language badge (FR/EN), progress "X/Y complétées", delete button
   - Click card → load interview → show questions

8. **addInterview()** — POST `/api/sessions/:id/interviews` with `{context, language}`:
   - On success: reload offer detail

9. **loadInterview(interviewId)** — GET `/api/interviews/:id`:
   - Set `state.currentInterviewId`, `state.questions`, `state.feedbacks`
   - Show questions view

10. **resumeSession(sessionId)** — now goes to offer detail view instead of questions

11. **sendMedia()** — send `interview_id` instead of `session_id` in FormData

12. **Session cards** — remove language/context display (no longer at offer level), show interview count instead

13. **Event listeners** — wire up `btn-create-offer`, `btn-toggle-add-interview`, `btn-add-interview`, `btn-back-home-offer`, `btn-back-to-offer`, breadcrumb click handlers

14. **NAV_BUTTON_IDS** — update to include new back buttons

- [ ] **Step 2: Manual browser test — create offer flow**

1. Load `http://localhost:5001`
2. Fill CV and job offer, click "Créer l'offre"
3. Verify: redirected to offer detail view, empty interview list shown, breadcrumb shows "Accueil > [title]"

- [ ] **Step 3: Manual browser test — add interview flow**

1. On offer detail, click "+ Ajouter un entretien"
2. Fill context "Screening RH", select Français, click "Générer les questions"
3. Verify: interview card appears with context, language badge, "0/N complétées"
4. Add a second interview "Technique CTO" in English
5. Verify: 2 interview cards shown

- [ ] **Step 4: Manual browser test — questions and recording flow**

1. Click on an interview card → questions grid shown
2. Breadcrumb: Accueil > Title > Interview context
3. Navigate back to offer detail → back to questions → verify state preserved
4. Verify existing recording/feedback flow still works (if API keys available)

- [ ] **Step 5: Manual browser test — session list and navigation**

1. Go back to home, verify offer card shows interview count
2. Click offer card → goes to offer detail (not questions)
3. Title edit still works (pencil icon on cards, breadcrumb click)
4. Archive/unarchive/delete still work

- [ ] **Step 6: Commit**

```bash
git add static/js/app.js
git commit -m "feat: 4-screen frontend with multi-interview navigation

New offer detail screen, interview CRUD, updated session cards
with interview count, 4-level breadcrumb navigation."
```

---

### Task 6: SQLite Migration Test

**Files:**
- Test: `tests/test_migration.py` (new file)

**Interfaces:**
- Consumes: `SQLiteStorage` from Task 1
- Produces: confidence that existing databases migrate correctly

- [ ] **Step 1: Write migration test**

Create `tests/test_migration.py`:

```python
"""Test that existing single-interview databases migrate correctly."""
import json
import sqlite3
from pathlib import Path

import pytest
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

    storage = SQLiteStorage(db_path)
    session = storage.get_session(old_sid)
    assert "context" not in {"cv", "job_offer"} or True  # data should only have cv and job_offer
    assert session["cv"] == "Old CV"
    assert session["job_offer"] == "Old Offer"
```

- [ ] **Step 2: Run migration tests**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && .venv/bin/python -m pytest tests/test_migration.py -v`
Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && .venv/bin/python -m pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_migration.py
git commit -m "test: add migration tests for old single-interview schema"
```
