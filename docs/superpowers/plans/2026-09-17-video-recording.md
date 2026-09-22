# Video Recording Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to choose video recording alongside the existing audio mode, adding GPT-4o vision analysis of facial expressions, posture, tics and eye contact as a third feedback block (`analysis_visual`).

**Architecture:** The browser captures video via `getUserMedia({audio, video})`, extracts frames client-side (1 frame/10s, cap 10) onto a hidden `<canvas>`, and sends audio + JPEG frames as multipart. The server passes frames to GPT-4o vision via a new `analyze_visual()` function and returns `analysis_visual` alongside the existing feedback fields. The audio-only path is untouched.

**Tech Stack:** Flask, OpenAI Python SDK (GPT-4o vision, Whisper, TTS), vanilla JS MediaRecorder + Canvas API, Tailwind CSS.

**Spec:** `docs/superpowers/specs/` — no separate spec file; design was approved in-chat.

## Global Constraints

- Python ≥ 3.11, dependencies managed via `pyproject.toml` + uv
- OpenAI API key required (`OPENAI_API_KEY`) — GPT-4o vision uses the same key
- No new system dependencies (no ffmpeg) — frame extraction is client-side
- Existing audio mode must not regress — all changes are additive
- Frame images sent as JPEG, `detail: "low"` to GPT-4o to control cost (~85 tokens/frame)
- No test framework is set up yet — tests use `pytest` with Flask's test client

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `services/ai_service.py` | Modify | Add `analyze_visual(frames, question, language)` |
| `app.py` | Modify | Handle `recording_mode`, frame files, `static/video/` dir, call `analyze_visual` |
| `templates/index.html` | Modify | Audio/video toggle, `<video>` preview, hidden `<canvas>`, visual feedback block |
| `static/js/app.js` | Modify | Video capture, frame extraction, multipart with frames, display `analysis_visual` |
| `tests/conftest.py` | Create | Pytest fixtures: Flask test client, mock OpenAI |
| `tests/test_ai_service.py` | Create | Unit tests for `analyze_visual()` |
| `tests/test_app.py` | Create | Integration tests for `/api/analyze-answer` with video mode |

---

### Task 1: `analyze_visual()` — AI service

**Files:**
- Modify: `services/ai_service.py` (add function after `analyze_answer`)
- Create: `tests/conftest.py`
- Create: `tests/test_ai_service.py`

**Interfaces:**
- Consumes: `_get_openai_client()` (existing), `LANGUAGE_LABELS` (existing)
- Produces: `analyze_visual(frames: list[bytes], question: str, language: str) -> str` — returns the visual analysis text. Used by Task 2's endpoint handler.

- [ ] **Step 1: Write the failing test**

Create `tests/conftest.py`:

```python
import pytest
from app import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
```

Create `tests/test_ai_service.py`:

```python
from unittest.mock import MagicMock, patch

from services import ai_service

FAKE_FRAME = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # minimal JPEG header bytes


def _mock_vision_response(text: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = text
    response = MagicMock()
    response.choices = [choice]
    return response


@patch.object(ai_service, "_get_openai_client")
def test_analyze_visual_returns_text(mock_client_fn):
    mock_client = MagicMock()
    mock_client_fn.return_value = mock_client
    mock_client.chat.completions.create.return_value = _mock_vision_response(
        "Le candidat maintient un bon contact visuel."
    )

    result = ai_service.analyze_visual(
        frames=[FAKE_FRAME, FAKE_FRAME],
        question="Présentez-vous.",
        language="fr",
    )

    assert isinstance(result, str)
    assert len(result) > 0
    mock_client.chat.completions.create.assert_called_once()

    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["model"] == "gpt-4o"
    messages = call_kwargs["messages"]
    user_msg = messages[1]
    image_parts = [p for p in user_msg["content"] if p["type"] == "image_url"]
    assert len(image_parts) == 2


@patch.object(ai_service, "_get_openai_client")
def test_analyze_visual_empty_frames_raises(mock_client_fn):
    try:
        ai_service.analyze_visual(frames=[], question="Q?", language="fr")
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "frame" in str(exc).lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && python -m pytest tests/test_ai_service.py -v`
Expected: FAIL with `AttributeError: module 'services.ai_service' has no attribute 'analyze_visual'`

- [ ] **Step 3: Implement `analyze_visual()`**

Add to `services/ai_service.py` after the `analyze_answer` function:

```python
import base64


def analyze_visual(
    frames: list[bytes],
    question: str,
    language: str,
) -> str:
    """Analyse les frames vidéo via GPT-4o vision pour le feedback non-verbal.

    Args:
        frames: Liste d'images JPEG en bytes.
        question: Question d'entretien posée.
        language: Code langue ('fr' ou 'en').

    Returns:
        Texte d'analyse du non-verbal.

    Raises:
        ValueError: Si aucune frame n'est fournie.
    """
    if not frames:
        raise ValueError("Au moins une frame est requise pour l'analyse visuelle.")

    lang_label = LANGUAGE_LABELS.get(language, language)

    system_prompt = (
        "Tu es un coach expert en communication non-verbale pour les entretiens "
        "d'embauche. On te fournit des captures d'écran extraites de la vidéo d'un "
        "candidat répondant à une question d'entretien. "
        "Analyse : expressions faciales, contact visuel (regarde-t-il la caméra ?), "
        "posture, gestes, tics corporels, niveau de confiance perçu. "
        "Donne des conseils concrets d'amélioration. "
        f"Rédige ton analyse en {lang_label}."
    )

    image_parts = []
    for frame in frames:
        b64 = base64.b64encode(frame).decode("utf-8")
        image_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"},
        })

    user_content = [
        {"type": "text", "text": f"Question posée au candidat : {question}"},
        *image_parts,
    ]

    client = _get_openai_client()
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=1000,
        temperature=0.7,
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Réponse GPT-4o vision vide.")
    return content.strip()
```

Note: the `import base64` should be added at the top of the file with the other imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && python -m pytest tests/test_ai_service.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add services/ai_service.py tests/conftest.py tests/test_ai_service.py
git commit -m "feat: add analyze_visual() for GPT-4o vision frame analysis"
```

---

### Task 2: Backend — video mode in `/api/analyze-answer`

**Files:**
- Modify: `app.py` (endpoint + `VIDEO_DIR` + `EXT_MAP` for video)
- Create: `tests/test_app.py`

**Interfaces:**
- Consumes: `ai_service.analyze_visual(frames, question, language)` from Task 1
- Produces: Modified `/api/analyze-answer` endpoint that accepts `recording_mode=video` + `frame_N` files and returns `analysis_visual` + `user_video_url` in the JSON response. Used by Task 4's frontend JS.

- [ ] **Step 1: Write the failing test**

Create `tests/test_app.py`:

```python
from io import BytesIO
from unittest.mock import MagicMock, patch

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


def _setup_session(client):
    """Create a session with one question via mocked AI."""
    with patch("services.ai_service.generate_questions", return_value=["Présentez-vous."]):
        resp = client.post(
            "/api/generate-questions",
            json={
                "cv": "Mon CV",
                "job_offer": "Offre test",
                "language": "fr",
                "context": "Entretien RH",
            },
        )
        return resp.get_json()["session_id"]


@patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100)
@patch("services.ai_service.analyze_answer", return_value={
    "transcription": "Ma réponse",
    "analysis_content": "Bon contenu",
    "analysis_form": "Bonne forme",
    "ideal_answer_text": "Réponse idéale",
})
@patch("services.ai_service.analyze_visual", return_value="Bon contact visuel.")
@patch("services.ai_service.transcribe_audio", return_value="Ma réponse")
def test_analyze_answer_video_mode(mock_transcribe, mock_visual, mock_analyze, mock_tts, client):
    session_id = _setup_session(client)

    data = {
        "session_id": session_id,
        "question_index": "0",
        "duration_seconds": "30.0",
        "recording_mode": "video",
        "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
        "frame_0": (BytesIO(FAKE_FRAME), "frame_0.jpg", "image/jpeg"),
        "frame_1": (BytesIO(FAKE_FRAME), "frame_1.jpg", "image/jpeg"),
    }

    resp = client.post(
        "/api/analyze-answer",
        data=data,
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert "analysis_visual" in body
    assert body["analysis_visual"] == "Bon contact visuel."
    mock_visual.assert_called_once()


@patch("services.ai_service.synthesize_speech", return_value=b"\x00" * 100)
@patch("services.ai_service.analyze_answer", return_value={
    "transcription": "Ma réponse",
    "analysis_content": "Bon contenu",
    "analysis_form": "Bonne forme",
    "ideal_answer_text": "Réponse idéale",
})
@patch("services.ai_service.transcribe_audio", return_value="Ma réponse")
def test_analyze_answer_audio_mode_unchanged(mock_transcribe, mock_analyze, mock_tts, client):
    session_id = _setup_session(client)

    data = {
        "session_id": session_id,
        "question_index": "0",
        "duration_seconds": "30.0",
        "recording_mode": "audio",
        "audio": (BytesIO(FAKE_AUDIO), "recording.webm", "audio/webm"),
    }

    resp = client.post(
        "/api/analyze-answer",
        data=data,
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert "analysis_visual" not in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && python -m pytest tests/test_app.py -v`
Expected: FAIL — `analysis_visual` missing from response (video test), or `recording_mode` not handled.

- [ ] **Step 3: Implement video mode in app.py**

In `app.py`, add `VIDEO_DIR` alongside `AUDIO_DIR`:

```python
VIDEO_DIR = BASE_DIR / "static" / "video"
```

In `create_app()`, add:

```python
VIDEO_DIR.mkdir(parents=True, exist_ok=True)
```

Modify the `analyze_answer` endpoint. After the existing audio processing and before the return, add video frame handling:

```python
        recording_mode = (request.form.get("recording_mode") or "audio").strip()

        # ... (existing audio analysis code stays unchanged) ...

        if recording_mode == "video":
            frames = []
            for i in range(10):
                frame_file = request.files.get(f"frame_{i}")
                if frame_file is None:
                    break
                frame_bytes = frame_file.read()
                if frame_bytes:
                    frames.append(frame_bytes)

            if frames:
                try:
                    visual_analysis = ai_service.analyze_visual(
                        frames=frames,
                        question=question,
                        language=session["language"],
                    )
                    feedback["analysis_visual"] = visual_analysis
                except Exception as exc:
                    logger.exception("Erreur lors de l'analyse visuelle")
                    feedback["analysis_visual"] = f"Analyse visuelle indisponible : {exc}"

            user_video_filename = f"user_{session_id}_{question_index}.webm"
            video_file = request.files.get("video")
            if video_file:
                video_bytes = video_file.read()
                if video_bytes:
                    video_path = VIDEO_DIR / user_video_filename
                    video_path.write_bytes(video_bytes)
                    feedback["user_video_url"] = f"/static/video/{user_video_filename}"
```

The full modified endpoint — the `recording_mode` variable is read right after `audio_file`, and the video block is inserted after `feedback["duration_seconds"] = duration_seconds` and before `storage.save_feedback(...)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && python -m pytest tests/test_app.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: handle video mode and frames in /api/analyze-answer"
```

---

### Task 3: Frontend — HTML + JS for video recording and visual feedback

**Files:**
- Modify: `templates/index.html` (audio/video toggle, video preview, canvas, visual feedback block)
- Modify: `static/js/app.js` (video capture, frame extraction, multipart upload, visual feedback display)

**Interfaces:**
- Consumes: `/api/analyze-answer` with `recording_mode=video`, `frame_N` files, optional `video` file — returns `analysis_visual` and `user_video_url` (from Task 2)
- Produces: Complete user-facing video recording and feedback UI

- [ ] **Step 1: Add HTML elements to `templates/index.html`**

**a) Audio/video toggle** — inside `<div id="recording-controls">`, before the record button, add:

```html
                    <div id="mode-selector" class="flex justify-center gap-4 mb-4">
                        <label class="flex items-center gap-2 cursor-pointer">
                            <input type="radio" name="recording-mode" value="audio" checked
                                class="accent-indigo-600">
                            <span class="text-sm text-slate-600">Audio seul</span>
                        </label>
                        <label class="flex items-center gap-2 cursor-pointer">
                            <input type="radio" name="recording-mode" value="video"
                                class="accent-indigo-600">
                            <span class="text-sm text-slate-600">Vidéo</span>
                        </label>
                    </div>
```

**b) Video preview** — right after `<p id="recording-status">`, add:

```html
                    <video id="video-preview" autoplay muted playsinline
                        class="hidden mx-auto rounded-lg w-full max-w-md mb-4 -scale-x-100"></video>
                    <canvas id="frame-canvas" class="hidden"></canvas>
```

**c) Visual feedback block** — in `<div id="consultation-mode">`, after the "Analyse de la forme" block and before the "Réponse idéale" block, add:

```html
                <div id="feedback-visual-block" class="hidden">
                    <h3 class="font-semibold text-slate-700 mb-1">Analyse du non-verbal</h3>
                    <p id="feedback-visual" class="text-slate-600 bg-amber-50 p-3 rounded-lg whitespace-pre-wrap"></p>
                </div>
```

**d) User video playback** — in the "Votre enregistrement" block, after `<audio id="user-audio">`, add:

```html
                    <video id="user-video" controls playsinline
                        class="hidden w-full rounded-lg"></video>
```

- [ ] **Step 2: Add video recording logic to `static/js/app.js`**

**a) Add state fields** — add to the `state` object:

```javascript
    recordingMode: "audio",
    capturedFrames: [],
    frameInterval: null,
    videoChunks: [],
    videoRecorder: null,
```

**b) Add mode selection handler** — after the existing event listeners at the bottom:

```javascript
document.querySelectorAll('input[name="recording-mode"]').forEach((radio) => {
    radio.addEventListener("change", (e) => {
        state.recordingMode = e.target.value;
    });
});
```

**c) Modify `toggleRecording()`** — replace the `getUserMedia` call:

```javascript
        const constraints = state.recordingMode === "video"
            ? { audio: true, video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } } }
            : { audio: true };

        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        activeStream = stream;

        if (state.recordingMode === "video") {
            const preview = document.getElementById("video-preview");
            preview.srcObject = stream;
            preview.classList.remove("hidden");
            startFrameCapture(stream);
            startVideoRecording(stream);
        }
```

**d) Add frame capture functions:**

```javascript
function startFrameCapture(stream) {
    state.capturedFrames = [];
    const videoTrack = stream.getVideoTracks()[0];
    if (!videoTrack) return;

    const canvas = document.getElementById("frame-canvas");
    const ctx = canvas.getContext("2d");
    const preview = document.getElementById("video-preview");

    captureOneFrame(preview, canvas, ctx);

    state.frameInterval = setInterval(() => {
        if (state.capturedFrames.length >= 10) {
            clearInterval(state.frameInterval);
            state.frameInterval = null;
            return;
        }
        captureOneFrame(preview, canvas, ctx);
    }, 10000);
}

function captureOneFrame(video, canvas, ctx) {
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
        (blob) => {
            if (blob) state.capturedFrames.push(blob);
        },
        "image/jpeg",
        0.7,
    );
}

function stopFrameCapture() {
    if (state.frameInterval) {
        clearInterval(state.frameInterval);
        state.frameInterval = null;
    }
    const preview = document.getElementById("video-preview");
    preview.srcObject = null;
    preview.classList.add("hidden");
}
```

**e) Add video recording functions:**

```javascript
function startVideoRecording(stream) {
    state.videoChunks = [];
    const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9,opus")
        ? "video/webm;codecs=vp9,opus"
        : "video/webm";
    state.videoRecorder = new MediaRecorder(stream, { mimeType });
    state.videoRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) state.videoChunks.push(e.data);
    };
    state.videoRecorder.start();
}

function stopVideoRecording() {
    return new Promise((resolve) => {
        if (!state.videoRecorder || state.videoRecorder.state !== "recording") {
            resolve(null);
            return;
        }
        state.videoRecorder.onstop = () => {
            const blob = new Blob(state.videoChunks, { type: "video/webm" });
            resolve(blob);
        };
        state.videoRecorder.stop();
    });
}
```

**f) Modify `stopMicrophone()`** — add cleanup before `state.mediaRecorder = null`:

```javascript
    stopFrameCapture();
    if (state.videoRecorder && state.videoRecorder.state === "recording") {
        state.videoRecorder.stop();
    }
    state.videoRecorder = null;
    state.capturedFrames = [];
```

**g) Modify `mediaRecorder.onstop`** — replace `sendAudio(blob, duration)` with:

```javascript
            if (state.recordingMode === "video") {
                stopFrameCapture();
                stopVideoRecording().then((videoBlob) => {
                    sendMedia(blob, duration, state.capturedFrames, videoBlob);
                });
            } else {
                sendMedia(blob, duration, [], null);
            }
```

**h) Replace `sendAudio` with `sendMedia`:**

```javascript
async function sendMedia(audioBlob, durationSeconds, frames, videoBlob) {
    state.isAnalyzing = true;
    setNavigationLocked(true);

    const formData = new FormData();
    formData.append("session_id", state.currentSessionId);
    formData.append("question_index", state.currentQuestionIndex);
    formData.append("duration_seconds", durationSeconds.toFixed(1));
    formData.append("recording_mode", state.recordingMode);
    formData.append("audio", audioBlob, "recording.webm");

    frames.forEach((frame, i) => {
        formData.append(`frame_${i}`, frame, `frame_${i}.jpg`);
    });

    if (videoBlob) {
        formData.append("video", videoBlob, "recording.webm");
    }

    try {
        const response = await fetch("/api/analyze-answer", {
            method: "POST",
            body: formData,
        });

        const data = await response.json();

        if (response.status === 404) {
            showError("recording-error", "Session expirée. Retournez à l'accueil.");
            document.getElementById("analysis-loading").classList.add("hidden");
            document.getElementById("recording-controls").classList.remove("hidden");
            await loadSessions();
            return;
        }

        if (!response.ok) {
            throw new Error(data.error || "Erreur lors de l'analyse.");
        }

        state.feedbacks[state.currentQuestionIndex] = data;
        showConsultationMode(data);
    } catch (err) {
        document.getElementById("analysis-loading").classList.add("hidden");
        document.getElementById("recording-controls").classList.remove("hidden");
        showError("recording-error", err.message);
    } finally {
        state.isAnalyzing = false;
        setNavigationLocked(false);
    }
}
```

**i) Modify `displayFeedback`** — add visual feedback display:

```javascript
    const visualBlock = document.getElementById("feedback-visual-block");
    if (data.analysis_visual) {
        document.getElementById("feedback-visual").textContent = data.analysis_visual;
        visualBlock.classList.remove("hidden");
    } else {
        visualBlock.classList.add("hidden");
    }

    const userAudio = document.getElementById("user-audio");
    const userVideo = document.getElementById("user-video");
    if (data.user_video_url) {
        userAudio.classList.add("hidden");
        userVideo.src = `${data.user_video_url}?t=${Date.now()}`;
        userVideo.classList.remove("hidden");
    } else {
        userVideo.classList.add("hidden");
        userAudio.classList.remove("hidden");
    }
```

**j) Modify `resetRecordingView()`** — add:

```javascript
    stopFrameCapture();
    state.capturedFrames = [];
    document.getElementById("video-preview").classList.add("hidden");
```

- [ ] **Step 3: Manual browser test**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && FLASK_DEBUG=1 python app.py`

Test scenario — audio mode:
1. Create a session with CV + job offer + context
2. Select a question
3. Verify "Audio seul" is selected by default
4. Record an answer → verify the existing flow works identically

Test scenario — video mode:
1. Select "Vidéo" radio button
2. Click "Démarrer l'enregistrement" → browser asks for camera + mic permission
3. Verify video preview shows (mirrored)
4. Record for ~25 seconds → should capture 3 frames (0s, 10s, 20s)
5. Click "Arrêter l'enregistrement" → analysis loading appears
6. Verify response includes: transcription, analysis_content, analysis_form, **analysis_visual**, ideal_answer_text
7. Verify "Analyse du non-verbal" block shows with amber background
8. Verify video playback works in consultation mode

- [ ] **Step 4: Commit**

```bash
git add templates/index.html static/js/app.js
git commit -m "feat: add video recording UI with frame capture and visual feedback display"
```

---

### Task 4: Polish and edge cases

**Files:**
- Modify: `static/js/app.js` (edge case handling)
- Modify: `app.py` (`.gitkeep` for video dir)

**Interfaces:**
- Consumes: Everything from Tasks 1-3
- Produces: Production-ready video mode

- [ ] **Step 1: Handle mode selector visibility**

The mode selector should be hidden in consultation mode and re-shown when switching back to recording. In `showRecordingMode()` in `app.js`:

```javascript
    document.getElementById("mode-selector").classList.remove("hidden");
```

In `showConsultationMode()`:

```javascript
    document.getElementById("mode-selector").classList.add("hidden");
```

- [ ] **Step 2: Ensure video preview stops on navigation**

Verify `stopMicrophone()` is called on all navigation paths. Check that `goToSetup()`, `goToQuestions()`, and `selectQuestion()` all call it — they already do per the existing code.

- [ ] **Step 3: Add `.gitkeep` for video directory**

```bash
mkdir -p static/video
touch static/video/.gitkeep
git add static/video/.gitkeep
```

- [ ] **Step 4: Add `static/video/` to `.gitignore`**

Add to `.gitignore` (same pattern as audio files if present):

```
static/video/*.webm
```

- [ ] **Step 5: Run all tests**

Run: `cd /home/guillaumecayeux/code_dev/Next_JOB/job_interview && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Full manual test in browser**

Repeat the browser test from Task 3 Step 3. Verify:
- Mode toggle works and persists within a session
- Switching from video to audio between questions works cleanly
- Consultation mode for a video-recorded question shows video player + visual analysis
- Consultation mode for an audio-recorded question shows audio player, no visual analysis block
- Re-recording a video answer works (previous video is overwritten)

- [ ] **Step 7: Commit**

```bash
git add static/js/app.js app.py static/video/.gitkeep .gitignore
git commit -m "feat: polish video mode — edge cases and cleanup"
```
