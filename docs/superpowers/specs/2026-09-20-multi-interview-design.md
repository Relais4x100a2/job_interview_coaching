# Multi-Interview per Offer — Design Spec

## Context

Currently each "session" bundles one job offer with one interview context, one set of questions, and feedbacks. Users applying for a position go through multiple interviews (HR screening, technical, manager, etc.) and need separate question sets for each.

## Decisions

- V1 is incremental only: users add interviews one at a time (no automatic detection of the recruitment process from the job posting).
- Language is per-interview, not per-offer — users can practice a screening in French and a technical interview in English for the same position.
- Question generation is tailored to the interview type via the context field, with "introduce yourself" always as Q1.

## Data Model

### Table `sessions` (= offer)

| Column      | Type    | Description                   |
|-------------|---------|-------------------------------|
| session_id  | TEXT PK | UUID                          |
| offer_title | TEXT    | Offer title (editable)        |
| created_at  | TEXT    | ISO datetime                  |
| data        | TEXT    | JSON `{cv, job_offer}`        |
| archived    | INT     | 0 or 1                        |

Removed from current schema: `language`, `questions`, `feedbacks`.

### Table `interviews` (new)

| Column       | Type    | Description                          |
|--------------|---------|--------------------------------------|
| interview_id | TEXT PK | UUID                                 |
| session_id   | TEXT FK | References sessions(session_id)      |
| context      | TEXT    | Interview type ("Screening RH", ...) |
| language     | TEXT    | 'fr' or 'en'                         |
| questions    | TEXT    | JSON array of strings                |
| feedbacks    | TEXT    | JSON `{"0": {...}, "1": {...}}`      |
| created_at   | TEXT    | ISO datetime                         |

Foreign key: `interviews.session_id → sessions.session_id` with `ON DELETE CASCADE`.

### Migration

The current `data` JSON column contains `{cv, job_offer, context}`. After migration it holds only `{cv, job_offer}`.

For each existing session:
1. Extract `context` from the `data` JSON field.
2. Create an interview row with that `context`, plus the session's `language`, `questions`, and `feedbacks`.
3. Update `data` to remove the `context` key.
4. Drop columns `language`, `questions`, `feedbacks` from `sessions`. SQLite requires table recreation for column removal.

Sessions with no questions (empty) are kept as offers with zero interviews (an interview is still created with the context but empty questions).

## API

### New endpoints

- `POST /api/sessions` — Create an offer. Body: `{cv, job_offer, offer_title?}`. Returns `{session_id, offer_title}`.
- `POST /api/sessions/<session_id>/interviews` — Add an interview. Body: `{context, language}`. Generates questions from the offer's CV/job_offer + the given context/language. Returns `{interview_id, context, language, questions}`.
- `GET /api/interviews/<interview_id>` — Interview detail with questions and feedbacks.
- `DELETE /api/interviews/<interview_id>` — Delete an interview.

### Modified endpoints

- `GET /api/sessions/<session_id>` — Returns offer details + list of interviews (id, context, language, question count, completed feedback count, created_at).
- `POST /api/analyze-answer` — Takes `interview_id` instead of `session_id` (plus question_index, audio, etc.). Internally resolves the offer's CV/job_offer from the interview's parent session.

### Unchanged endpoints

- `GET /api/sessions` — List offers.
- `PATCH /api/sessions/<session_id>/title` — Edit offer title.
- `POST /api/sessions/<session_id>/archive` — Archive offer.
- `POST /api/sessions/<session_id>/unarchive` — Unarchive offer.
- `DELETE /api/sessions/<session_id>` — Delete offer (cascades to interviews).

### Removed

- `POST /api/generate-questions` — Replaced by `POST /api/sessions/<session_id>/interviews`.

## UX — 4 Screens

### Screen 1 — Home (Setup)

- List of existing offers (unchanged cards with edit/archive/delete).
- Simplified creation form: **CV + Job offer** only (language and context removed from this level). Button: "Créer l'offre".
- Offer title is auto-generated from first 40 chars of job offer text, editable later.

### Screen 2 — Offer Detail (NEW)

- Breadcrumb: Accueil > Offer title (editable on click)
- Back button to home.
- List of interviews as cards, each showing:
  - Context (e.g. "Screening RH")
  - Language badge (FR/EN)
  - Progress: "3/7 questions complétées"
  - Delete button
- "Ajouter un entretien" button → inline form or expandable section with:
  - Context textarea (required)
  - Language select (fr/en)
  - "Générer les questions" button
- Empty state: "Aucun entretien. Ajoutez votre premier entretien pour commencer."

### Screen 3 — Interview Questions (existing, adapted)

- Breadcrumb: Accueil > Offer title > Interview context
- Question grid (unchanged behavior).

### Screen 4 — Recording/Feedback (existing, unchanged)

- Breadcrumb: Accueil > Offer title > Interview context > Question N/M

## Question Generation

The `generate_questions` function signature stays the same (`cv`, `job_offer`, `language`, `context`). The system prompt is enhanced to generate questions specific to the interview type:

> "Génère des questions d'entretien **spécifiques au type d'entretien décrit dans le contexte**. Par exemple : pour un screening RH, concentre-toi sur la motivation, le parcours, les prétentions salariales et la disponibilité. Pour un entretien technique, concentre-toi sur les compétences techniques, la résolution de problèmes et les choix d'architecture. Adapte les questions au contexte fourni."

Q1 is always the self-introduction question ("Pouvez-vous vous présenter ?" / "Could you introduce yourself?").

## State Management (Frontend)

The JS `state` object gains:
- `interviews: []` — list of interviews for current offer
- `currentInterviewId: null` — selected interview

The `views` object gains:
- `offer: document.getElementById("view-offer")` — new offer detail screen

Navigation flow: setup → offer detail → questions → recording.
