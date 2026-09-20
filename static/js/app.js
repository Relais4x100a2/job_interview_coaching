/** Application SPA d'entraînement aux entretiens. */

const state = {
    currentSessionId: null,
    offerTitle: null,
    questions: [],
    feedbacks: {},
    currentQuestionIndex: null,
    viewMode: null,
    isAnalyzing: false,
    isAbandoning: false,
    mediaRecorder: null,
    audioChunks: [],
    recordingStart: null,
    timerInterval: null,
    recordingMode: "audio",
    capturedFrames: [],
    frameInterval: null,
    videoChunks: [],
    videoRecorder: null,
};

let activeStream = null;

const NAV_BUTTON_IDS = [
    "btn-back-home",
    "btn-back-to-questions",
    "nav-home",
    "btn-back-questions-consult",
    "btn-rerecord",
];

const views = {
    setup: document.getElementById("view-setup"),
    questions: document.getElementById("view-questions"),
    recording: document.getElementById("view-recording"),
};

function showView(name) {
    if (name !== "recording") {
        stopMicrophone();
    }
    Object.entries(views).forEach(([key, el]) => {
        el.classList.toggle("hidden", key !== name);
    });
    updateBreadcrumb(name);
}

function showError(elementId, message) {
    const el = document.getElementById(elementId);
    el.textContent = message;
    el.classList.remove("hidden");
}

function hideError(elementId) {
    const el = document.getElementById(elementId);
    el.classList.add("hidden");
}

function formatTimer(seconds) {
    const m = Math.floor(seconds / 60).toString().padStart(2, "0");
    const s = (seconds % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
}

function formatDate(isoString) {
    const date = new Date(isoString);
    return date.toLocaleDateString("fr-FR", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    });
}

function getFeedback(index) {
    return state.feedbacks[index] ?? state.feedbacks[String(index)] ?? null;
}

function isQuestionAnswered(index) {
    return getFeedback(index) !== null;
}

function updateBreadcrumb(view) {
    const breadcrumb = document.getElementById("breadcrumb");
    const sep1 = document.getElementById("breadcrumb-sep-1");
    const sep2 = document.getElementById("breadcrumb-sep-2");
    const offerEl = document.getElementById("breadcrumb-offer");
    const questionEl = document.getElementById("breadcrumb-question");

    if (!view || view === "setup") {
        breadcrumb.classList.add("hidden");
        return;
    }

    breadcrumb.classList.remove("hidden");
    sep1.classList.remove("hidden");
    offerEl.classList.remove("hidden");
    offerEl.textContent = state.offerTitle || "Offre";

    if (view === "recording" && state.currentQuestionIndex !== null) {
        sep2.classList.remove("hidden");
        questionEl.classList.remove("hidden");
        questionEl.textContent = `Question ${state.currentQuestionIndex + 1}/${state.questions.length}`;
    } else {
        sep2.classList.add("hidden");
        questionEl.classList.add("hidden");
    }
}

function setNavigationLocked(locked) {
    NAV_BUTTON_IDS.forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.disabled = locked;
        el.classList.toggle("opacity-50", locked);
        el.classList.toggle("pointer-events-none", locked);
    });
}

function stopMicrophone() {
    state.isAbandoning = true;

    if (state.mediaRecorder && state.mediaRecorder.state === "recording") {
        state.mediaRecorder.stop();
    }

    if (activeStream) {
        activeStream.getTracks().forEach((track) => track.stop());
        activeStream = null;
    }

    stopFrameCapture();
    if (state.videoRecorder && state.videoRecorder.state === "recording") {
        state.videoRecorder.stop();
    }
    state.videoRecorder = null;
    state.capturedFrames = [];

    state.mediaRecorder = null;
    state.isAbandoning = false;
    stopTimer();
}

function showRecordingMode() {
    document.getElementById("recording-mode").classList.remove("hidden");
    document.getElementById("consultation-mode").classList.add("hidden");
    document.getElementById("mode-selector").classList.remove("hidden");
    state.viewMode = "recording";
}

function showConsultationMode(feedback) {
    document.getElementById("recording-mode").classList.add("hidden");
    document.getElementById("consultation-mode").classList.remove("hidden");
    document.getElementById("mode-selector").classList.add("hidden");
    displayFeedback(feedback);
    state.viewMode = "consultation";
}

function goToSetup() {
    if (state.isAnalyzing) return;
    stopMicrophone();
    state.currentQuestionIndex = null;
    showView("setup");
}

function goToQuestions() {
    if (state.isAnalyzing) return;
    stopMicrophone();
    state.currentQuestionIndex = null;
    renderQuestions();
    showView("questions");
}

async function loadSessions() {
    hideError("sessions-error");
    const emptyEl = document.getElementById("sessions-empty");
    const listEl = document.getElementById("sessions-list");

    try {
        const response = await fetch("/api/sessions");
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || "Erreur lors du chargement des sessions.");
        }

        const sessions = data.sessions || [];
        if (sessions.length === 0) {
            listEl.innerHTML = "";
            emptyEl.classList.remove("hidden");
            return;
        }

        emptyEl.classList.add("hidden");
        renderSessions(sessions);
    } catch (err) {
        showError("sessions-error", err.message);
    }
}

function renderSessions(sessions) {
    const listEl = document.getElementById("sessions-list");
    listEl.innerHTML = "";

    sessions.forEach((session) => {
        const langLabel = session.language === "fr" ? "Français" : "Anglais";
        const contextPreview = session.context.length > 60
            ? `${session.context.slice(0, 60)}…`
            : session.context;

        const card = document.createElement("div");
        card.className =
            "text-left bg-slate-50 border border-slate-200 rounded-lg p-4 hover:ring-2 hover:ring-indigo-400 transition cursor-pointer";
        card.innerHTML = `
            <p class="font-medium text-slate-800">${session.offer_title}</p>
            <p class="text-xs text-slate-500 mt-1">${langLabel} · ${formatDate(session.created_at)}</p>
            <p class="text-sm text-slate-600 mt-2">${contextPreview}</p>
            <div class="flex gap-2 mt-3 justify-end">
                <button type="button" data-action="archive" class="text-xs text-slate-400 hover:text-amber-600 px-2 py-1 rounded hover:bg-amber-50 transition">Archiver</button>
                <button type="button" data-action="delete" class="text-xs text-slate-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50 transition">Supprimer</button>
            </div>
        `;
        card.addEventListener("click", (e) => {
            if (e.target.closest("[data-action]")) return;
            resumeSession(session.session_id);
        });
        card.querySelector("[data-action='archive']").addEventListener("click", (e) => {
            e.stopPropagation();
            archiveSession(session.session_id);
        });
        card.querySelector("[data-action='delete']").addEventListener("click", (e) => {
            e.stopPropagation();
            deleteSession(session.session_id);
        });
        listEl.appendChild(card);
    });
}

function renderArchivedSessions(sessions) {
    const listEl = document.getElementById("archived-list");
    const emptyEl = document.getElementById("archived-empty");
    listEl.innerHTML = "";

    if (sessions.length === 0) {
        emptyEl.classList.remove("hidden");
        return;
    }
    emptyEl.classList.add("hidden");

    sessions.forEach((session) => {
        const langLabel = session.language === "fr" ? "Français" : "Anglais";
        const contextPreview = session.context.length > 60
            ? `${session.context.slice(0, 60)}…`
            : session.context;

        const card = document.createElement("div");
        card.className =
            "text-left bg-slate-50 border border-slate-200 rounded-lg p-4 transition";
        card.innerHTML = `
            <p class="font-medium text-slate-800">${session.offer_title}</p>
            <p class="text-xs text-slate-500 mt-1">${langLabel} · ${formatDate(session.created_at)}</p>
            <p class="text-sm text-slate-600 mt-2">${contextPreview}</p>
            <div class="flex gap-2 mt-3 justify-end">
                <button type="button" data-action="unarchive" class="text-xs text-indigo-500 hover:text-indigo-700 px-2 py-1 rounded hover:bg-indigo-50 transition">Restaurer</button>
                <button type="button" data-action="delete" class="text-xs text-slate-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50 transition">Supprimer</button>
            </div>
        `;
        card.querySelector("[data-action='unarchive']").addEventListener("click", () => {
            unarchiveSession(session.session_id);
        });
        card.querySelector("[data-action='delete']").addEventListener("click", () => {
            deleteSession(session.session_id, true);
        });
        listEl.appendChild(card);
    });
}

async function archiveSession(sessionId) {
    try {
        const resp = await fetch(`/api/sessions/${sessionId}/archive`, { method: "POST" });
        if (!resp.ok) throw new Error("Erreur lors de l'archivage.");
        await loadSessions();
    } catch (err) {
        showError("sessions-error", err.message);
    }
}

async function unarchiveSession(sessionId) {
    try {
        const resp = await fetch(`/api/sessions/${sessionId}/unarchive`, { method: "POST" });
        if (!resp.ok) throw new Error("Erreur lors de la restauration.");
        await loadArchivedSessions();
        await loadSessions();
    } catch (err) {
        showError("sessions-error", err.message);
    }
}

async function deleteSession(sessionId, fromArchived = false) {
    if (!confirm("Supprimer définitivement cette offre ?")) return;
    try {
        const resp = await fetch(`/api/sessions/${sessionId}`, { method: "DELETE" });
        if (!resp.ok) throw new Error("Erreur lors de la suppression.");
        if (fromArchived) {
            await loadArchivedSessions();
        } else {
            await loadSessions();
        }
    } catch (err) {
        showError("sessions-error", err.message);
    }
}

async function loadArchivedSessions() {
    try {
        const response = await fetch("/api/sessions?archived=true");
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Erreur.");
        renderArchivedSessions(data.sessions || []);
    } catch (err) {
        showError("sessions-error", err.message);
    }
}

function showArchivedSection() {
    document.getElementById("history-section").classList.add("hidden");
    document.getElementById("archived-section").classList.remove("hidden");
    loadArchivedSessions();
}

function hideArchivedSection() {
    document.getElementById("archived-section").classList.add("hidden");
    document.getElementById("history-section").classList.remove("hidden");
}

function applySessionData(data) {
    state.currentSessionId = data.session_id;
    state.offerTitle = data.offer_title || "Offre";
    state.questions = data.questions || [];
    state.feedbacks = data.feedbacks || {};
    state.currentQuestionIndex = null;
}

async function resumeSession(sessionId) {
    hideError("sessions-error");

    try {
        const response = await fetch(`/api/sessions/${sessionId}`);
        const data = await response.json();

        if (response.status === 404) {
            showError(
                "sessions-error",
                "Cette session n'existe plus (serveur redémarré). " +
                "Veuillez créer une nouvelle offre ou en sélectionner une autre."
            );
            await loadSessions();
            showView("setup");
            return;
        }

        if (!response.ok) {
            throw new Error(data.error || "Erreur lors du chargement de la session.");
        }

        applySessionData(data);
        renderQuestions();
        showView("questions");
    } catch (err) {
        showError("sessions-error", err.message);
    }
}

async function generateQuestions() {
    hideError("setup-error");

    const cv = document.getElementById("cv").value.trim();
    const jobOffer = document.getElementById("job-offer").value.trim();
    const language = document.getElementById("language").value;
    const context = document.getElementById("context").value.trim();

    if (!cv || !jobOffer || !context) {
        showError("setup-error", "Veuillez remplir tous les champs obligatoires.");
        return;
    }

    const btn = document.getElementById("btn-generate");
    btn.disabled = true;
    btn.textContent = "Génération en cours...";

    try {
        const response = await fetch("/api/generate-questions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ cv, job_offer: jobOffer, language, context }),
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || "Erreur lors de la génération.");
        }

        applySessionData(data);
        state.feedbacks = {};
        renderQuestions();
        showView("questions");
        loadSessions();
    } catch (err) {
        showError("setup-error", err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = "Générer les questions";
    }
}

function renderQuestions() {
    const grid = document.getElementById("questions-grid");
    grid.innerHTML = "";

    state.questions.forEach((question, index) => {
        const answered = isQuestionAnswered(index);
        const card = document.createElement("button");
        card.type = "button";
        card.className = answered
            ? "text-left rounded-xl shadow-md p-4 border-2 border-green-200 bg-green-50 hover:ring-2 hover:ring-green-400 transition"
            : "text-left rounded-xl shadow-md p-4 border border-slate-200 bg-white hover:ring-2 hover:ring-indigo-400 transition";

        const statusBadge = answered
            ? '<span class="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">Complétée 🔊</span>'
            : '<span class="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">Non répondue</span>';

        card.innerHTML = `
            <div class="flex items-center justify-between gap-2">
                <span class="text-xs text-indigo-500 font-medium">Question ${index + 1}</span>
                ${statusBadge}
            </div>
            <p class="mt-1 text-slate-700">${question}</p>
        `;
        card.addEventListener("click", () => selectQuestion(index));
        grid.appendChild(card);
    });
}

function selectQuestion(index) {
    if (state.isAnalyzing) return;

    stopMicrophone();
    state.currentQuestionIndex = index;
    document.getElementById("selected-question").textContent = state.questions[index];
    hideError("recording-error");

    const existing = getFeedback(index);
    if (existing) {
        showConsultationMode(existing);
    } else {
        resetRecordingView();
        showRecordingMode();
    }

    showView("recording");
}

function resetRecordingView() {
    hideError("recording-error");
    document.getElementById("recording-controls").classList.remove("hidden");
    document.getElementById("analysis-loading").classList.add("hidden");
    document.getElementById("recording-status").textContent = "Appuyez pour enregistrer votre réponse";
    document.getElementById("btn-record").textContent = "Démarrer l'enregistrement";
    document.getElementById("btn-record").classList.remove("bg-gray-500");
    document.getElementById("btn-record").classList.add("bg-red-500");
    document.getElementById("recording-timer").classList.add("hidden");
    document.getElementById("user-audio").src = "";
    document.getElementById("user-video").src = "";
    document.getElementById("ideal-audio").src = "";
    stopTimer();
    stopFrameCapture();
    state.capturedFrames = [];
    document.getElementById("video-preview").classList.add("hidden");
}

function startRerecording() {
    if (state.isAnalyzing) return;
    stopMicrophone();
    resetRecordingView();
    showRecordingMode();
}

async function toggleRecording() {
    hideError("recording-error");

    if (state.mediaRecorder && state.mediaRecorder.state === "recording") {
        stopRecording();
        return;
    }

    try {
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

        const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
            ? "audio/webm;codecs=opus"
            : "audio/webm";

        state.audioChunks = [];
        const audioStream = state.recordingMode === "video"
            ? new MediaStream(stream.getAudioTracks())
            : stream;
        state.mediaRecorder = new MediaRecorder(audioStream, { mimeType });

        state.mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                state.audioChunks.push(event.data);
            }
        };

        state.mediaRecorder.onstop = () => {
            if (activeStream) {
                activeStream.getTracks().forEach((track) => track.stop());
                activeStream = null;
            }

            if (state.isAbandoning || state.isAnalyzing) {
                return;
            }

            const blob = new Blob(state.audioChunks, { type: mimeType });
            const duration = state.recordingStart
                ? (Date.now() - state.recordingStart) / 1000
                : 0;

            if (state.recordingMode === "video") {
                stopFrameCapture();
                stopVideoRecording().then((videoBlob) => {
                    sendMedia(blob, duration, state.capturedFrames, videoBlob);
                });
            } else {
                sendMedia(blob, duration, [], null);
            }
        };

        state.recordingStart = Date.now();
        state.mediaRecorder.start();
        startTimer();

        document.getElementById("recording-status").textContent = "Enregistrement en cours...";
        document.getElementById("btn-record").textContent = "Arrêter l'enregistrement";
        document.getElementById("btn-record").classList.replace("bg-red-500", "bg-gray-500");
        document.getElementById("recording-timer").classList.remove("hidden");
    } catch (err) {
        if (activeStream) {
            activeStream.getTracks().forEach((track) => track.stop());
            activeStream = null;
        }
        stopFrameCapture();
        if (state.videoRecorder && state.videoRecorder.state === "recording") {
            state.videoRecorder.stop();
        }
        state.videoRecorder = null;

        console.error("Erreur d'accès média :", err);
        const device = state.recordingMode === "video" ? "la caméra et au microphone" : "au microphone";
        const detail = err.name ? ` (${err.name})` : "";
        showError(
            "recording-error",
            `Impossible d'accéder à ${device}${detail}. Vérifiez les permissions de votre navigateur.`
        );
    }
}

function stopRecording() {
    if (state.mediaRecorder && state.mediaRecorder.state === "recording") {
        state.mediaRecorder.stop();
        stopTimer();
        document.getElementById("recording-controls").classList.add("hidden");
        document.getElementById("analysis-loading").classList.remove("hidden");
    }
}

function startTimer() {
    const timerEl = document.getElementById("recording-timer");
    let elapsed = 0;
    timerEl.textContent = formatTimer(elapsed);
    state.timerInterval = setInterval(() => {
        elapsed += 1;
        timerEl.textContent = formatTimer(elapsed);
    }, 1000);
}

function stopTimer() {
    if (state.timerInterval) {
        clearInterval(state.timerInterval);
        state.timerInterval = null;
    }
}

function startFrameCapture(stream) {
    state.capturedFrames = [];
    const videoTrack = stream.getVideoTracks()[0];
    if (!videoTrack) return;

    const canvas = document.getElementById("frame-canvas");
    const ctx = canvas.getContext("2d");
    const preview = document.getElementById("video-preview");

    const beginCapture = () => {
        captureOneFrame(preview, canvas, ctx);

        state.frameInterval = setInterval(() => {
            if (state.capturedFrames.length >= 10) {
                clearInterval(state.frameInterval);
                state.frameInterval = null;
                return;
            }
            captureOneFrame(preview, canvas, ctx);
        }, 10000);
    };

    // drawImage() throws InvalidStateError until the video element has
    // decoded at least one frame (readyState >= HAVE_CURRENT_DATA). Setting
    // srcObject does not make that data available synchronously, so wait
    // for it before capturing — unless it's already ready.
    if (preview.readyState >= 2) {
        beginCapture();
    } else {
        preview.addEventListener("loadeddata", beginCapture, { once: true });
    }
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

function displayFeedback(data) {
    document.getElementById("feedback-transcription").textContent = data.transcription;
    document.getElementById("feedback-content").textContent = data.analysis_content;
    document.getElementById("feedback-form").textContent = data.analysis_form;
    document.getElementById("feedback-ideal").textContent = data.ideal_answer_text;

    if (data.user_audio_url) {
        document.getElementById("user-audio").src = `${data.user_audio_url}?t=${Date.now()}`;
    }
    if (data.audio_url) {
        document.getElementById("ideal-audio").src = `${data.audio_url}?t=${Date.now()}`;
    }

    const visualBlock = document.getElementById("feedback-visual-block");
    const framesContainer = document.getElementById("feedback-frames");
    framesContainer.innerHTML = "";
    if (data.analysis_visual) {
        if (data.frame_urls && data.frame_urls.length > 0) {
            data.frame_urls.forEach((url, i) => {
                const img = document.createElement("img");
                img.src = `${url}?t=${Date.now()}`;
                img.alt = `Capture ${i + 1}`;
                img.className = "rounded-lg border border-slate-200 h-32 flex-shrink-0";
                framesContainer.appendChild(img);
            });
        }
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
}

document.getElementById("btn-generate").addEventListener("click", generateQuestions);
document.getElementById("btn-record").addEventListener("click", toggleRecording);
document.getElementById("btn-rerecord").addEventListener("click", startRerecording);
document.getElementById("btn-back-home").addEventListener("click", goToSetup);
document.getElementById("nav-home").addEventListener("click", goToSetup);
document.getElementById("btn-back-to-questions").addEventListener("click", goToQuestions);
document.getElementById("btn-back-questions-consult").addEventListener("click", goToQuestions);
document.getElementById("btn-show-archived").addEventListener("click", showArchivedSection);
document.getElementById("btn-hide-archived").addEventListener("click", hideArchivedSection);

document.querySelectorAll('input[name="recording-mode"]').forEach((radio) => {
    radio.addEventListener("change", (e) => {
        state.recordingMode = e.target.value;
    });
});

document.addEventListener("DOMContentLoaded", loadSessions);
