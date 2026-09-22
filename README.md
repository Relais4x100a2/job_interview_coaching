# Entraînement aux entretiens d'embauche

Application Flask containerisée pour s'entraîner aux entretiens d'embauche : une offre (CV + fiche de poste) peut donner lieu à plusieurs entretiens (contextes/langues différents), avec génération de questions personnalisées, enregistrement audio ou vidéo, transcription Whisper, analyse IA (fond, forme et non-verbal), et synthèse vocale de la réponse idéale.

## Fonctionnalités

- Création d'une offre (CV + fiche de poste) reformatée automatiquement en Markdown structuré par LLM (suppression du contenu hors-sujet : discours RSE, "qui sommes-nous", etc.), avec repli sur le texte brut si le formatage échoue
- Visualisation et modification manuelle du CV/de l'offre reformatés depuis l'écran de détail
- Une offre peut avoir plusieurs entretiens (contexte + langue FR/EN propres à chacun), chacun avec ses propres questions et feedbacks
- Génération de 5 à 7 questions d'entretien via LLM par entretien (Q1 = présentation obligatoire)
- Navigation par fil d'Ariane (accueil → détail de l'offre → entretien → question) sur une SPA à 4 écrans
- Historique des offres avec titre modifiable, archivage/désarchivage et suppression (offre ou entretien)
- Enregistrement navigateur audio ou vidéo (MediaRecorder API), avec capture périodique d'images en mode vidéo
- Transcription STT (Whisper), analyse fond/forme (LLM), analyse du non-verbal en mode vidéo (GPT-4o vision), TTS de la réponse idéale
- Feedback détaillé avec lecteurs audio (votre enregistrement + réponse idéale) et, en mode vidéo, l'analyse visuelle

## Prérequis

- Docker et Docker Compose
- Clé API OpenAI (`OPENAI_API_KEY`) — requise pour STT/TTS et LLM
- Optionnel : clé OpenRouter (`OPENROUTER_API_KEY`) pour le LLM si pas de clé OpenAI

## Démarrage rapide

```bash
cp .env.example .env
# Éditez .env et renseignez OPENAI_API_KEY

docker compose up --build
```

L'application est accessible sur [http://localhost:5000](http://localhost:5000).

## Développement local (sans Docker)

```bash
uv sync
cp .env.example .env
uv run flask --app app run --debug
```

## Architecture

```
app.py                  → Routes Flask
services/storage.py     → SQLiteStorage / InMemoryStorage (pattern Repository, tables sessions/interviews)
services/ai_service.py  → LLM (questions, formatage Markdown, analyse fond/forme, analyse visuelle), STT Whisper, TTS OpenAI
templates/index.html    → Interface SPA (4 écrans : accueil, détail offre, entretien, question)
static/js/app.js        → Navigation, enregistrement audio/vidéo et appels API
instance/app.db         → Base SQLite (persistée, gitignored)
```

Une offre (`sessions`) regroupe le CV et la fiche de poste ; chaque entretien (`interviews`) rattaché à une offre par clé étrangère porte son propre contexte, sa langue, ses questions et ses feedbacks.

## Persistance des données

| Donnée | Emplacement | Persiste au restart ? |
|---|---|---|
| Offres, entretiens, questions, feedbacks | `instance/app.db` (SQLite) | Oui |
| Fichiers audio (.webm, .mp3) | `static/audio/` | Oui |
| Images extraites des vidéos (.jpg) | `static/video/` | Oui |
| Clés API | `.env` (local, gitignored) | Oui |

Le schéma hybride (colonnes SQL + JSON) permet d'évoluer les champs sans migration Alembic.

Avec Docker, le volume `./instance:/app/instance` garantit la persistance de la base sur l'hôte.

## Variables d'environnement

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | Clé OpenAI (STT, TTS, LLM, analyse visuelle) |
| `OPENROUTER_API_KEY` | Clé OpenRouter (LLM alternatif) |
| `OPENROUTER_MODEL` | Modèle OpenRouter (défaut : `openai/gpt-4o-mini`) |
| `OPENAI_MODEL` | Modèle OpenAI (défaut : `gpt-4o-mini`) |
| `TTS_VOICE` | Voix TTS (défaut : `alloy`) |
| `FLASK_DEBUG` | Mode debug Flask (`1` pour activer) |
| `STORAGE_TYPE` | `sqlite` (défaut) ou `memory` |
| `DATABASE_PATH` | Chemin BDD SQLite (défaut : `instance/app.db`) |

> **Note :** Whisper (STT) et TTS nécessitent toujours une clé `OPENAI_API_KEY`, même si le LLM passe par OpenRouter. L'analyse visuelle (mode vidéo) utilise également l'API OpenAI (GPT-4o vision).

## API

### `POST /api/sessions`

Crée une offre (CV + fiche de poste). Le contenu est automatiquement reformaté en Markdown par LLM (repli sur le texte brut en cas d'échec).

```json
{
  "cv": "...",
  "job_offer": "...",
  "offer_title": "..."
}
```

### `GET /api/sessions`

Retourne la liste des offres (titre, date, nombre d'entretiens). Paramètre `?archived=true` pour lister les offres archivées.

### `GET /api/sessions/<session_id>`

Retourne le détail d'une offre : CV, fiche de poste (Markdown), titre et liste de ses entretiens.

### `PATCH /api/sessions/<session_id>`

Met à jour le CV et la fiche de poste d'une offre (édition manuelle).

```json
{ "cv": "...", "job_offer": "..." }
```

### `PATCH /api/sessions/<session_id>/title`

Met à jour le titre d'une offre. `{ "title": "..." }`

### `POST /api/sessions/<session_id>/archive` / `POST /api/sessions/<session_id>/unarchive`

Archive ou désarchive une offre.

### `DELETE /api/sessions/<session_id>`

Supprime définitivement une offre et ses entretiens (cascade).

### `POST /api/sessions/<session_id>/interviews`

Crée un entretien (génération des questions via LLM) pour une offre existante.

```json
{ "context": "...", "language": "fr" }
```

### `GET /api/interviews/<interview_id>`

Retourne le détail d'un entretien : contexte, langue, questions, feedbacks.

### `DELETE /api/interviews/<interview_id>`

Supprime définitivement un entretien.

### `POST /api/analyze-answer` (multipart/form-data)

- `interview_id`, `question_index`, `duration_seconds`, `recording_mode` (`audio` ou `video`), `audio` (fichier webm), et en mode vidéo `frame_0`, `frame_1`, ... (images JPEG capturées pendant l'enregistrement)

Réponse inclut `user_audio_url` (enregistrement candidat), `audio_url` (réponse idéale TTS), `analysis_content`, `analysis_form`, `ideal_answer_text`, et en mode vidéo `analysis_visual` (analyse du non-verbal) et `frame_urls`.

## CI

GitHub Actions exécute `ruff check` à chaque push/PR.
