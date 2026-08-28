# Entraînement aux entretiens d'embauche

Application Flask containerisée pour s'entraîner aux entretiens d'embauche avec génération de questions personnalisées, enregistrement vocal, transcription Whisper, analyse IA et synthèse vocale de la réponse idéale.

## Fonctionnalités

- Formulaire d'initialisation (CV, offre, langue FR/EN, contexte)
- Génération de 5 à 7 questions d'entretien via LLM (Q1 = présentation obligatoire)
- Historique des sessions : reprise directe d'une offre existante depuis l'accueil
- Enregistrement audio navigateur (MediaRecorder API)
- Transcription STT (Whisper), analyse fond/forme (LLM), TTS réponse idéale
- Feedback détaillé avec deux lecteurs audio : votre enregistrement + réponse idéale

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
services/storage.py     → SQLiteStorage / InMemoryStorage (pattern Repository)
services/ai_service.py  → LLM, STT Whisper, TTS OpenAI
templates/index.html    → Interface SPA
static/js/app.js        → Enregistrement audio et appels API
instance/app.db         → Base SQLite (persistée, gitignored)
```

## Persistance des données

| Donnée | Emplacement | Persiste au restart ? |
|---|---|---|
| Sessions, questions, feedbacks | `instance/app.db` (SQLite) | Oui |
| Fichiers audio (.webm, .mp3) | `static/audio/` | Oui |
| Clés API | `.env` (local, gitignored) | Oui |

Le schéma hybride (colonnes SQL + JSON) permet d'évoluer les champs sans migration Alembic.

Avec Docker, le volume `./instance:/app/instance` garantit la persistance de la base sur l'hôte.

## Variables d'environnement

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | Clé OpenAI (STT, TTS, LLM) |
| `OPENROUTER_API_KEY` | Clé OpenRouter (LLM alternatif) |
| `OPENROUTER_MODEL` | Modèle OpenRouter (défaut : `openai/gpt-4o-mini`) |
| `OPENAI_MODEL` | Modèle OpenAI (défaut : `gpt-4o-mini`) |
| `TTS_VOICE` | Voix TTS (défaut : `alloy`) |
| `FLASK_DEBUG` | Mode debug Flask (`1` pour activer) |
| `STORAGE_TYPE` | `sqlite` (défaut) ou `memory` |
| `DATABASE_PATH` | Chemin BDD SQLite (défaut : `instance/app.db`) |

> **Note :** Whisper (STT) et TTS nécessitent toujours une clé `OPENAI_API_KEY`, même si le LLM passe par OpenRouter.

## API

### `GET /api/sessions`

Retourne la liste des sessions enregistrées (titre offre, langue, contexte, date).

### `GET /api/sessions/<session_id>`

Retourne le détail d'une session : questions, feedbacks et métadonnées.

### `POST /api/generate-questions`

```json
{
  "cv": "...",
  "job_offer": "...",
  "language": "fr",
  "context": "..."
}
```

### `POST /api/analyze-answer` (multipart/form-data)

- `session_id`, `question_index`, `duration_seconds`, `audio` (fichier webm)

Réponse inclut `user_audio_url` (enregistrement candidat) et `audio_url` (réponse idéale TTS).

## CI

GitHub Actions exécute `ruff check` à chaque push/PR.
