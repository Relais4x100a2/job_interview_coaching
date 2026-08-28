"""Application Flask d'entraînement aux entretiens d'embauche."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import BadRequest, NotFound

from services import ai_service
from services.storage import InMemoryStorage

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR / "static" / "audio"

EXT_MAP = {
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/ogg": "ogg",
}

storage = InMemoryStorage()


def create_app() -> Flask:
    """Crée et configure l'application Flask.

    Returns:
        Instance Flask configurée.
    """
    app = Flask(__name__)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    @app.get("/")
    def index() -> str:
        """Affiche la page principale de l'application."""
        return render_template("index.html")

    @app.post("/api/generate-questions")
    def generate_questions():
        """Génère des questions d'entretien personnalisées."""
        data = request.get_json(silent=True) or {}
        cv = (data.get("cv") or "").strip()
        job_offer = (data.get("job_offer") or "").strip()
        language = (data.get("language") or "").strip()
        context = (data.get("context") or "").strip()

        if not cv:
            raise BadRequest("Le champ 'cv' est obligatoire.")
        if not job_offer:
            raise BadRequest("Le champ 'job_offer' est obligatoire.")
        if not context:
            raise BadRequest("Le champ 'context' est obligatoire.")
        if language not in ("fr", "en"):
            raise BadRequest("La langue doit être 'fr' ou 'en'.")

        try:
            questions = ai_service.generate_questions(
                cv=cv,
                job_offer=job_offer,
                language=language,
                context=context,
            )
        except Exception as exc:
            logger.exception("Erreur lors de la génération de questions")
            return jsonify({"error": str(exc)}), 500

        session_id = storage.create_session(
            cv=cv,
            job_offer=job_offer,
            language=language,
            context=context,
        )
        storage.save_questions(session_id, questions)

        session = storage.get_session(session_id)
        return jsonify({
            "session_id": session_id,
            "offer_title": session["offer_title"] if session else "",
            "questions": questions,
        })

    @app.get("/api/sessions")
    def list_sessions():
        """Retourne la liste des sessions enregistrées."""
        return jsonify({"sessions": storage.get_all_sessions()})

    @app.get("/api/sessions/<session_id>")
    def get_session_detail(session_id: str):
        """Retourne le détail d'une session avec questions et feedbacks."""
        session = storage.get_session(session_id)
        if session is None:
            raise NotFound("Session introuvable.")
        return jsonify({
            "session_id": session["session_id"],
            "offer_title": session["offer_title"],
            "language": session["language"],
            "context": session["context"],
            "created_at": session["created_at"].isoformat(),
            "questions": session["questions"],
            "feedbacks": session["feedbacks"],
        })

    @app.post("/api/analyze-answer")
    def analyze_answer():
        """Transcrit, analyse et synthétise le feedback d'une réponse orale."""
        session_id = (request.form.get("session_id") or "").strip()
        question_index_raw = request.form.get("question_index")
        duration_raw = request.form.get("duration_seconds", "0")
        audio_file = request.files.get("audio")

        if not session_id:
            raise BadRequest("Le champ 'session_id' est obligatoire.")
        if question_index_raw is None:
            raise BadRequest("Le champ 'question_index' est obligatoire.")
        if audio_file is None or not audio_file.filename:
            raise BadRequest("Le fichier audio est obligatoire.")

        try:
            question_index = int(question_index_raw)
            duration_seconds = float(duration_raw)
        except ValueError as exc:
            raise BadRequest("question_index ou duration_seconds invalide.") from exc

        session = storage.get_session(session_id)
        if session is None:
            raise NotFound("Session introuvable.")

        questions = session.get("questions", [])
        if question_index < 0 or question_index >= len(questions):
            raise BadRequest("Index de question invalide.")

        question = questions[question_index]
        audio_bytes = audio_file.read()
        if not audio_bytes:
            raise BadRequest("Le fichier audio est vide.")

        filename = audio_file.filename or "audio.webm"

        raw_content_type = audio_file.content_type or ""
        clean_content_type = raw_content_type.split(";")[0].strip()
        ext = EXT_MAP.get(clean_content_type, "webm")

        user_audio_filename = f"user_{session_id}_{question_index}.{ext}"
        user_audio_path = AUDIO_DIR / user_audio_filename
        user_audio_path.write_bytes(audio_bytes)

        try:
            transcription = ai_service.transcribe_audio(audio_bytes, filename)
            feedback = ai_service.analyze_answer(
                question=question,
                transcription=transcription,
                cv=session["cv"],
                job_offer=session["job_offer"],
                context=session["context"],
                language=session["language"],
                duration_seconds=duration_seconds,
            )
            mp3_bytes = ai_service.synthesize_speech(feedback["ideal_answer_text"])
        except Exception as exc:
            logger.exception("Erreur lors de l'analyse de la réponse")
            return jsonify({"error": str(exc)}), 500

        ideal_audio_filename = f"ideal_{session_id}_{question_index}.mp3"
        ideal_audio_path = AUDIO_DIR / ideal_audio_filename
        ideal_audio_path.write_bytes(mp3_bytes)

        feedback["user_audio_url"] = f"/static/audio/{user_audio_filename}"
        feedback["audio_url"] = f"/static/audio/{ideal_audio_filename}"
        feedback["duration_seconds"] = duration_seconds

        storage.save_feedback(session_id, question_index, feedback)

        return jsonify(feedback)

    @app.errorhandler(BadRequest)
    def handle_bad_request(exc: BadRequest):
        """Retourne une erreur 400 en JSON."""
        return jsonify({"error": exc.description}), 400

    @app.errorhandler(NotFound)
    def handle_not_found(exc: NotFound):
        """Retourne une erreur 404 en JSON."""
        return jsonify({"error": exc.description}), 404

    @app.errorhandler(Exception)
    def handle_generic_error(exc: Exception):
        """Retourne une erreur 500 en JSON."""
        logger.exception("Erreur interne")
        return jsonify({"error": "Erreur interne du serveur."}), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.getenv("FLASK_DEBUG") == "1")
