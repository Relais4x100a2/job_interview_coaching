"""Application Flask d'entraînement aux entretiens d'embauche."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import BadRequest, NotFound

from services import ai_service
from services.storage import create_storage

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR / "static" / "audio"
VIDEO_DIR = BASE_DIR / "static" / "video"
INSTANCE_DIR = BASE_DIR / "instance"

EXT_MAP = {
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/ogg": "ogg",
}

storage = create_storage(BASE_DIR)


def create_app() -> Flask:
    """Crée et configure l'application Flask.

    Returns:
        Instance Flask configurée.
    """
    app = Flask(__name__)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)

    @app.get("/")
    def index() -> str:
        """Affiche la page principale de l'application."""
        return render_template("index.html")

    @app.post("/api/sessions")
    def create_session():
        """Crée une nouvelle offre (CV + offre d'emploi)."""
        data = request.get_json(silent=True) or {}
        cv = (data.get("cv") or "").strip()
        job_offer = (data.get("job_offer") or "").strip()
        offer_title = (data.get("offer_title") or "").strip()

        if not cv:
            raise BadRequest("Le champ 'cv' est obligatoire.")
        if not job_offer:
            raise BadRequest("Le champ 'job_offer' est obligatoire.")

        raw_cv, raw_job_offer = cv, job_offer
        try:
            cv, job_offer = ai_service.format_offer_content(cv, job_offer)
        except Exception:
            logger.warning("Échec du formatage Markdown du CV/offre, texte brut conservé", exc_info=True)

        # Le titre auto-généré doit rester basé sur le texte brut (pas le Markdown formaté).
        session_id = storage.create_session(cv=raw_cv, job_offer=raw_job_offer)
        if (cv, job_offer) != (raw_cv, raw_job_offer):
            storage.update_offer_content(session_id, cv=cv, job_offer=job_offer)
        if offer_title:
            storage.update_offer_title(session_id, offer_title)

        session = storage.get_session(session_id)
        return jsonify({
            "session_id": session_id,
            "offer_title": session["offer_title"] if session else offer_title,
        })

    @app.post("/api/sessions/<session_id>/interviews")
    def create_interview(session_id: str):
        """Crée un entretien (contexte + langue) pour une offre existante."""
        session = storage.get_session(session_id)
        if session is None:
            raise NotFound("Session introuvable.")

        data = request.get_json(silent=True) or {}
        context = (data.get("context") or "").strip()
        language = (data.get("language") or "").strip()

        if not context:
            raise BadRequest("Le champ 'context' est obligatoire.")
        if language not in ("fr", "en"):
            raise BadRequest("La langue doit être 'fr' ou 'en'.")

        try:
            questions = ai_service.generate_questions(
                cv=session["cv"],
                job_offer=session["job_offer"],
                language=language,
                context=context,
            )
        except Exception as exc:
            logger.exception("Erreur lors de la génération de questions")
            return jsonify({"error": str(exc)}), 500

        interview_id = storage.create_interview(session_id, context, language)
        storage.save_questions(interview_id, questions)

        return jsonify({
            "interview_id": interview_id,
            "context": context,
            "language": language,
            "questions": questions,
        })

    @app.get("/api/interviews/<interview_id>")
    def get_interview_detail(interview_id: str):
        """Retourne le détail d'un entretien (questions, feedbacks)."""
        interview = storage.get_interview(interview_id)
        if interview is None:
            raise NotFound("Entretien introuvable.")
        return jsonify({
            "interview_id": interview["interview_id"],
            "session_id": interview["session_id"],
            "context": interview["context"],
            "language": interview["language"],
            "questions": interview["questions"],
            "feedbacks": interview["feedbacks"],
            "created_at": interview["created_at"].isoformat(),
        })

    @app.delete("/api/interviews/<interview_id>")
    def delete_interview(interview_id: str):
        """Supprime définitivement un entretien."""
        try:
            storage.delete_interview(interview_id)
        except KeyError:
            raise NotFound("Entretien introuvable.")
        return jsonify({"ok": True})

    @app.get("/api/sessions")
    def list_sessions():
        """Retourne la liste des sessions enregistrées."""
        archived = request.args.get("archived", "false").lower() == "true"
        return jsonify({"sessions": storage.get_all_sessions(archived=archived)})

    @app.patch("/api/sessions/<session_id>/title")
    def update_session_title(session_id: str):
        """Met à jour le titre d'une session."""
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip()
        if not title:
            raise BadRequest("Le titre ne peut pas être vide.")
        try:
            storage.update_offer_title(session_id, title)
        except KeyError:
            raise NotFound("Session introuvable.")
        return jsonify({"ok": True, "offer_title": title})

    @app.post("/api/sessions/<session_id>/archive")
    def archive_session(session_id: str):
        """Archive une session."""
        try:
            storage.archive_session(session_id)
        except KeyError:
            raise NotFound("Session introuvable.")
        return jsonify({"ok": True})

    @app.post("/api/sessions/<session_id>/unarchive")
    def unarchive_session(session_id: str):
        """Désarchive une session."""
        try:
            storage.unarchive_session(session_id)
        except KeyError:
            raise NotFound("Session introuvable.")
        return jsonify({"ok": True})

    @app.delete("/api/sessions/<session_id>")
    def delete_session(session_id: str):
        """Supprime définitivement une session."""
        try:
            storage.delete_session(session_id)
        except KeyError:
            raise NotFound("Session introuvable.")
        return jsonify({"ok": True})

    @app.get("/api/sessions/<session_id>")
    def get_session_detail(session_id: str):
        """Retourne le détail d'une offre avec la liste de ses entretiens."""
        session = storage.get_session(session_id)
        if session is None:
            raise NotFound("Session introuvable.")
        interviews = [
            {**itw, "created_at": itw["created_at"].isoformat()}
            for itw in session["interviews"]
        ]
        return jsonify({
            "session_id": session["session_id"],
            "offer_title": session["offer_title"],
            "cv": session["cv"],
            "job_offer": session["job_offer"],
            "created_at": session["created_at"].isoformat(),
            "interviews": interviews,
        })

    @app.patch("/api/sessions/<session_id>")
    def update_session_content(session_id: str):
        """Met à jour le CV et l'offre d'emploi d'une session."""
        data = request.get_json(silent=True) or {}
        cv = (data.get("cv") or "").strip()
        job_offer = (data.get("job_offer") or "").strip()
        if not cv:
            raise BadRequest("Le champ 'cv' est obligatoire.")
        if not job_offer:
            raise BadRequest("Le champ 'job_offer' est obligatoire.")
        try:
            storage.update_offer_content(session_id, cv=cv, job_offer=job_offer)
        except KeyError:
            raise NotFound("Session introuvable.")
        return jsonify({"ok": True, "cv": cv, "job_offer": job_offer})

    @app.post("/api/analyze-answer")
    def analyze_answer():
        """Transcrit, analyse et synthétise le feedback d'une réponse orale."""
        interview_id = (request.form.get("interview_id") or "").strip()
        question_index_raw = request.form.get("question_index")
        duration_raw = request.form.get("duration_seconds", "0")
        recording_mode = (request.form.get("recording_mode") or "audio").strip()
        audio_file = request.files.get("audio")

        if not interview_id:
            raise BadRequest("Le champ 'interview_id' est obligatoire.")
        if question_index_raw is None:
            raise BadRequest("Le champ 'question_index' est obligatoire.")
        if audio_file is None or not audio_file.filename:
            raise BadRequest("Le fichier audio est obligatoire.")

        try:
            question_index = int(question_index_raw)
            duration_seconds = float(duration_raw)
        except ValueError as exc:
            raise BadRequest("question_index ou duration_seconds invalide.") from exc

        interview = storage.get_interview_with_session(interview_id)
        if interview is None:
            raise NotFound("Entretien introuvable.")

        questions = interview.get("questions", [])
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

        user_audio_filename = f"user_{interview_id}_{question_index}.{ext}"
        user_audio_path = AUDIO_DIR / user_audio_filename
        user_audio_path.write_bytes(audio_bytes)

        try:
            transcription = ai_service.transcribe_audio(audio_bytes, filename)
            feedback = ai_service.analyze_answer(
                question=question,
                transcription=transcription,
                cv=interview["cv"],
                job_offer=interview["job_offer"],
                context=interview["context"],
                language=interview["language"],
                duration_seconds=duration_seconds,
            )
            mp3_bytes = ai_service.synthesize_speech(feedback["ideal_answer_text"])
        except Exception as exc:
            logger.exception("Erreur lors de l'analyse de la réponse")
            return jsonify({"error": str(exc)}), 500

        ideal_audio_filename = f"ideal_{interview_id}_{question_index}.mp3"
        ideal_audio_path = AUDIO_DIR / ideal_audio_filename
        ideal_audio_path.write_bytes(mp3_bytes)

        feedback["user_audio_url"] = f"/static/audio/{user_audio_filename}"
        feedback["audio_url"] = f"/static/audio/{ideal_audio_filename}"
        feedback["duration_seconds"] = duration_seconds

        if recording_mode == "video":
            frames = []
            frame_urls = []
            for i in range(10):
                frame_file = request.files.get(f"frame_{i}")
                if frame_file is None:
                    break
                frame_bytes = frame_file.read()
                if frame_bytes:
                    frames.append(frame_bytes)
                    frame_filename = f"frame_{interview_id}_{question_index}_{i}.jpg"
                    (VIDEO_DIR / frame_filename).write_bytes(frame_bytes)
                    frame_urls.append(f"/static/video/{frame_filename}")

            if frames:
                try:
                    visual_analysis = ai_service.analyze_visual(
                        frames=frames,
                        question=question,
                        language=interview["language"],
                    )
                    feedback["analysis_visual"] = visual_analysis
                except Exception as exc:
                    logger.exception("Erreur lors de l'analyse visuelle")
                    feedback["analysis_visual"] = "Analyse visuelle indisponible."

            if frame_urls:
                feedback["frame_urls"] = frame_urls

            user_video_filename = f"user_{interview_id}_{question_index}.webm"
            video_file = request.files.get("video")
            if video_file:
                video_bytes = video_file.read()
                if video_bytes:
                    video_path = VIDEO_DIR / user_video_filename
                    video_path.write_bytes(video_bytes)
                    feedback["user_video_url"] = f"/static/video/{user_video_filename}"

        storage.save_feedback(interview_id, question_index, feedback)

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
