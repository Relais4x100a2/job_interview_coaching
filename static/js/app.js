/** Application SPA d'entraînement aux entretiens. */

const state = {
    currentSessionId: null,
    offerTitle: null,
    offerCv: "",
    offerJobOffer: "",
    interviews: [],
    currentInterviewId: null,
    currentInterviewContext: null,
    currentInterviewLanguage: null,
    questions: [],
    feedbacks: {},
    currentQuestionIndex: null,
    validatedDirty: false,
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
let allSessions = [];
let analysisStepInterval = null;

const ANALYSIS_STEPS = [
    "Transcription de votre réponse…",
    "Analyse du contenu et de la forme…",
    "Génération de la réponse idéale et synthèse vocale…",
];

const NAV_BUTTON_IDS = [
    "btn-back-home-offer",
    "btn-back-to-offer",
    "btn-back-to-questions",
    "nav-home",
    "btn-back-questions-consult",
    "btn-rerecord",
];

const views = {
    setup: document.getElementById("view-setup"),
    questionSearch: document.getElementById("view-question-search"),
    offer: document.getElementById("view-offer"),
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
    const sep3 = document.getElementById("breadcrumb-sep-3");
    const offerEl = document.getElementById("breadcrumb-offer");
    const interviewEl = document.getElementById("breadcrumb-interview");
    const questionEl = document.getElementById("breadcrumb-question");

    if (!view || view === "setup" || view === "questionSearch") {
        breadcrumb.classList.add("hidden");
        return;
    }

    breadcrumb.classList.remove("hidden");
    sep1.classList.remove("hidden");
    offerEl.classList.remove("hidden");
    offerEl.textContent = state.offerTitle || "Offre";
    offerEl.title = "Cliquer pour renommer";
    offerEl.style.cursor = "pointer";

    if (view === "questions" || view === "recording") {
        sep2.classList.remove("hidden");
        interviewEl.classList.remove("hidden");
        interviewEl.textContent = state.currentInterviewContext || "Entretien";
    } else {
        sep2.classList.add("hidden");
        interviewEl.classList.add("hidden");
    }

    if (view === "recording" && state.currentQuestionIndex !== null) {
        sep3.classList.remove("hidden");
        questionEl.classList.remove("hidden");
        questionEl.textContent = `Question ${state.currentQuestionIndex + 1}/${state.questions.length}`;
    } else {
        sep3.classList.add("hidden");
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
    stopAnalysisProgress();
    setRecordingModeLocked(false);
}

async function updateOfferTitle(sessionId, newTitle) {
    const resp = await fetch(`/api/sessions/${sessionId}/title`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: newTitle }),
    });
    if (!resp.ok) throw new Error("Erreur lors de la mise à jour du titre.");
    if (sessionId === state.currentSessionId) {
        state.offerTitle = newTitle;
    }
}

function startTitleEdit(titleEl, sessionId, onSaved) {
    const current = titleEl.textContent;
    const input = document.createElement("input");
    input.type = "text";
    input.value = current;
    input.className = "font-medium text-slate-800 border border-indigo-300 rounded px-1 py-0.5 w-full focus:outline-none focus:ring-2 focus:ring-indigo-400";

    const commit = async () => {
        const val = input.value.trim();
        if (!val || val === current) {
            titleEl.textContent = current;
            input.replaceWith(titleEl);
            return;
        }
        try {
            await updateOfferTitle(sessionId, val);
            titleEl.textContent = val;
            input.replaceWith(titleEl);
            if (onSaved) onSaved();
        } catch {
            titleEl.textContent = current;
            input.replaceWith(titleEl);
        }
    };

    input.addEventListener("blur", commit);
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); input.blur(); }
        if (e.key === "Escape") { input.value = current; input.blur(); }
    });

    titleEl.replaceWith(input);
    input.focus();
    input.select();
}

function getCurrentView() {
    for (const [key, el] of Object.entries(views)) {
        if (!el.classList.contains("hidden")) return key;
    }
    return "setup";
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

function showConfirmModal({ title, message, confirmLabel = "Confirmer" } = {}) {
    return new Promise((resolve) => {
        const modal = document.getElementById("confirm-modal");
        document.getElementById("confirm-modal-title").textContent = title;
        document.getElementById("confirm-modal-message").textContent = message;
        const confirmBtn = document.getElementById("confirm-modal-confirm");
        const cancelBtn = document.getElementById("confirm-modal-cancel");
        confirmBtn.textContent = confirmLabel;

        const cleanup = (result) => {
            modal.classList.add("hidden");
            confirmBtn.removeEventListener("click", onConfirm);
            cancelBtn.removeEventListener("click", onCancel);
            document.removeEventListener("keydown", onKeydown);
            resolve(result);
        };
        const onConfirm = () => cleanup(true);
        const onCancel = () => cleanup(false);
        const onKeydown = (e) => {
            if (e.key === "Escape") cleanup(false);
        };

        confirmBtn.addEventListener("click", onConfirm);
        cancelBtn.addEventListener("click", onCancel);
        document.addEventListener("keydown", onKeydown);
        modal.classList.remove("hidden");
        confirmBtn.focus();
    });
}

function confirmDiscardValidated() {
    if (!state.validatedDirty) return true;
    const confirmed = confirm(
        "Vous avez des modifications non enregistrées dans le plan/la réponse validés. Continuer sans les enregistrer ?"
    );
    if (confirmed) state.validatedDirty = false;
    return confirmed;
}

function goToSetup() {
    if (state.isAnalyzing) return;
    if (!confirmDiscardValidated()) return;
    stopMicrophone();
    state.currentSessionId = null;
    state.offerTitle = null;
    state.interviews = [];
    state.currentInterviewId = null;
    state.currentInterviewContext = null;
    state.questions = [];
    state.feedbacks = {};
    state.currentQuestionIndex = null;
    showView("setup");
    loadSessions();
}

function goToOffer() {
    if (state.isAnalyzing) return;
    if (!confirmDiscardValidated()) return;
    stopMicrophone();
    state.currentInterviewId = null;
    state.currentInterviewContext = null;
    state.questions = [];
    state.feedbacks = {};
    state.currentQuestionIndex = null;
    document.getElementById("add-interview-form").classList.add("hidden");
    document.getElementById("btn-toggle-add-interview").textContent = "+ Ajouter un entretien";
    showView("offer");
    loadOfferDetail(state.currentSessionId);
}

function goToQuestions() {
    if (state.isAnalyzing) return;
    if (!confirmDiscardValidated()) return;
    stopMicrophone();
    state.currentQuestionIndex = null;
    renderQuestions();
    showView("questions");
}

async function loadSessions() {
    hideError("sessions-error");
    const emptyEl = document.getElementById("sessions-empty");
    const listEl = document.getElementById("sessions-list");
    const loadingEl = document.getElementById("sessions-loading");

    emptyEl.classList.add("hidden");
    listEl.innerHTML = "";
    loadingEl.classList.remove("hidden");

    try {
        const response = await fetch("/api/sessions");
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || "Erreur lors du chargement des sessions.");
        }

        allSessions = data.sessions || [];
        applySessionsFilter();
    } catch (err) {
        showError("sessions-error", err.message);
    } finally {
        loadingEl.classList.add("hidden");
    }
}

function applySessionsFilter() {
    const searchInput = document.getElementById("sessions-search");
    const emptyEl = document.getElementById("sessions-empty");
    const listEl = document.getElementById("sessions-list");
    const query = searchInput.value.trim().toLowerCase();

    if (allSessions.length === 0) {
        searchInput.classList.add("hidden");
        listEl.innerHTML = "";
        emptyEl.textContent = "Aucune session enregistrée.";
        emptyEl.classList.remove("hidden");
        return;
    }
    searchInput.classList.remove("hidden");

    const filtered = query
        ? allSessions.filter((s) => s.offer_title.toLowerCase().includes(query))
        : allSessions;

    if (filtered.length === 0) {
        listEl.innerHTML = "";
        emptyEl.textContent = "Aucune offre ne correspond à votre recherche.";
        emptyEl.classList.remove("hidden");
        return;
    }
    emptyEl.classList.add("hidden");
    renderSessions(filtered);
}

function interviewCountLabel(count) {
    return `${count} entretien${count === 1 ? "" : "s"}`;
}

function renderSessions(sessions) {
    const listEl = document.getElementById("sessions-list");
    listEl.innerHTML = "";

    sessions.forEach((session) => {
        const card = document.createElement("div");
        card.className =
            "text-left bg-slate-50 border border-slate-200 rounded-lg p-4 hover:ring-2 hover:ring-indigo-400 transition cursor-pointer";
        card.innerHTML = `
            <div class="flex items-start justify-between gap-1">
                <p class="font-medium text-slate-800 session-title">${session.offer_title}</p>
                <button type="button" data-action="edit-title" aria-label="Renommer « ${session.offer_title} »" class="text-xs text-slate-400 hover:text-indigo-600 px-1 py-0.5 rounded hover:bg-indigo-50 transition flex-shrink-0" title="Renommer">✏️</button>
            </div>
            <p class="text-xs text-slate-500 mt-1">${formatDate(session.created_at)}</p>
            <p class="text-sm text-slate-600 mt-2">${interviewCountLabel(session.interview_count)}</p>
            <div class="flex gap-2 mt-3 justify-end">
                <button type="button" data-action="archive" aria-label="Archiver « ${session.offer_title} »" class="text-xs text-slate-400 hover:text-amber-600 px-2 py-1 rounded hover:bg-amber-50 transition">Archiver</button>
                <button type="button" data-action="delete" aria-label="Supprimer « ${session.offer_title} »" class="text-xs text-slate-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50 transition">Supprimer</button>
            </div>
        `;
        card.addEventListener("click", (e) => {
            if (e.target.closest("[data-action]")) return;
            resumeSession(session.session_id);
        });
        card.querySelector("[data-action='edit-title']").addEventListener("click", (e) => {
            e.stopPropagation();
            const titleEl = card.querySelector(".session-title");
            startTitleEdit(titleEl, session.session_id);
        });
        card.querySelector("[data-action='archive']").addEventListener("click", (e) => {
            e.stopPropagation();
            archiveSession(session.session_id);
        });
        card.querySelector("[data-action='delete']").addEventListener("click", (e) => {
            e.stopPropagation();
            deleteSession(session.session_id, false, session.offer_title);
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
        const card = document.createElement("div");
        card.className =
            "text-left bg-slate-50 border border-slate-200 rounded-lg p-4 transition";
        card.innerHTML = `
            <div class="flex items-start justify-between gap-1">
                <p class="font-medium text-slate-800 session-title">${session.offer_title}</p>
                <button type="button" data-action="edit-title" aria-label="Renommer « ${session.offer_title} »" class="text-xs text-slate-400 hover:text-indigo-600 px-1 py-0.5 rounded hover:bg-indigo-50 transition flex-shrink-0" title="Renommer">✏️</button>
            </div>
            <p class="text-xs text-slate-500 mt-1">${formatDate(session.created_at)}</p>
            <p class="text-sm text-slate-600 mt-2">${interviewCountLabel(session.interview_count)}</p>
            <div class="flex gap-2 mt-3 justify-end">
                <button type="button" data-action="unarchive" aria-label="Restaurer « ${session.offer_title} »" class="text-xs text-indigo-500 hover:text-indigo-700 px-2 py-1 rounded hover:bg-indigo-50 transition">Restaurer</button>
                <button type="button" data-action="delete" aria-label="Supprimer « ${session.offer_title} »" class="text-xs text-slate-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50 transition">Supprimer</button>
            </div>
        `;
        card.querySelector("[data-action='edit-title']").addEventListener("click", (e) => {
            e.stopPropagation();
            const titleEl = card.querySelector(".session-title");
            startTitleEdit(titleEl, session.session_id);
        });
        card.querySelector("[data-action='unarchive']").addEventListener("click", () => {
            unarchiveSession(session.session_id);
        });
        card.querySelector("[data-action='delete']").addEventListener("click", () => {
            deleteSession(session.session_id, true, session.offer_title);
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

async function deleteSession(sessionId, fromArchived = false, title = "cette offre") {
    const confirmed = await showConfirmModal({
        title: "Supprimer l'offre",
        message: `Supprimer définitivement « ${title} » ? Tous les entretiens associés seront aussi supprimés. Cette action est irréversible.`,
        confirmLabel: "Supprimer",
    });
    if (!confirmed) return;
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
    const loadingEl = document.getElementById("archived-loading");
    document.getElementById("archived-list").innerHTML = "";
    document.getElementById("archived-empty").classList.add("hidden");
    loadingEl.classList.remove("hidden");

    try {
        const response = await fetch("/api/sessions?archived=true");
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Erreur.");
        renderArchivedSessions(data.sessions || []);
    } catch (err) {
        showError("sessions-error", err.message);
    } finally {
        loadingEl.classList.add("hidden");
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

function resumeSession(sessionId) {
    hideError("sessions-error");
    state.currentSessionId = sessionId;
    goToOffer();
}

async function createOffer() {
    hideError("setup-error");

    const cv = document.getElementById("cv").value.trim();
    const jobOffer = document.getElementById("job-offer").value.trim();

    if (!cv || !jobOffer) {
        showError("setup-error", "Veuillez remplir tous les champs obligatoires.");
        return;
    }

    const btn = document.getElementById("btn-create-offer");
    btn.disabled = true;
    btn.textContent = "Création en cours...";

    try {
        const response = await fetch("/api/sessions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ cv, job_offer: jobOffer }),
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || "Erreur lors de la création de l'offre.");
        }

        state.currentSessionId = data.session_id;
        state.offerTitle = data.offer_title;
        document.getElementById("cv").value = "";
        document.getElementById("job-offer").value = "";

        goToOffer();
        loadSessions();
    } catch (err) {
        showError("setup-error", err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = "Créer l'offre";
    }
}

async function loadOfferDetail(sessionId) {
    hideError("interview-error");
    const loadingEl = document.getElementById("interviews-loading");
    document.getElementById("interviews-list").innerHTML = "";
    document.getElementById("interviews-empty").classList.add("hidden");
    loadingEl.classList.remove("hidden");

    try {
        const response = await fetch(`/api/sessions/${sessionId}`);
        const data = await response.json();

        if (response.status === 404) {
            showError(
                "sessions-error",
                "Cette offre n'existe plus (serveur redémarré). " +
                "Veuillez créer une nouvelle offre ou en sélectionner une autre."
            );
            await loadSessions();
            goToSetup();
            return;
        }

        if (!response.ok) {
            throw new Error(data.error || "Erreur lors du chargement de l'offre.");
        }

        state.currentSessionId = data.session_id;
        state.offerTitle = data.offer_title;
        state.interviews = data.interviews || [];
        state.offerCv = data.cv || "";
        state.offerJobOffer = data.job_offer || "";
        renderInterviews();
        renderOfferContent();
        collapseOfferContent();
        updateBreadcrumb(getCurrentView());
    } catch (err) {
        showError("interview-error", err.message);
    } finally {
        loadingEl.classList.add("hidden");
    }
}

function renderOfferContent() {
    document.getElementById("offer-content-cv").innerHTML = marked.parse(state.offerCv || "");
    document.getElementById("offer-content-job-offer").innerHTML = marked.parse(state.offerJobOffer || "");
}

function collapseOfferContent() {
    document.getElementById("offer-content-body").classList.add("hidden");
    document.getElementById("offer-content-chevron").textContent = "▸";
    cancelEditOfferContent();
}

function toggleOfferContent() {
    const body = document.getElementById("offer-content-body");
    const chevron = document.getElementById("offer-content-chevron");
    const collapsed = body.classList.toggle("hidden");
    chevron.textContent = collapsed ? "▸" : "▾";
}

function startEditOfferContent() {
    hideError("offer-content-error");
    document.getElementById("offer-content-cv").classList.add("hidden");
    document.getElementById("offer-content-job-offer").classList.add("hidden");

    const cvInput = document.getElementById("offer-content-cv-input");
    const jobOfferInput = document.getElementById("offer-content-job-offer-input");
    cvInput.value = state.offerCv || "";
    jobOfferInput.value = state.offerJobOffer || "";
    cvInput.classList.remove("hidden");
    jobOfferInput.classList.remove("hidden");

    document.getElementById("btn-edit-offer-content").classList.add("hidden");
    const actions = document.getElementById("offer-content-edit-actions");
    actions.classList.remove("hidden");
    actions.classList.add("flex");
}

function cancelEditOfferContent() {
    hideError("offer-content-error");
    document.getElementById("offer-content-cv").classList.remove("hidden");
    document.getElementById("offer-content-job-offer").classList.remove("hidden");
    document.getElementById("offer-content-cv-input").classList.add("hidden");
    document.getElementById("offer-content-job-offer-input").classList.add("hidden");
    document.getElementById("btn-edit-offer-content").classList.remove("hidden");
    const actions = document.getElementById("offer-content-edit-actions");
    actions.classList.add("hidden");
    actions.classList.remove("flex");
}

async function saveOfferContent() {
    const cv = document.getElementById("offer-content-cv-input").value.trim();
    const jobOffer = document.getElementById("offer-content-job-offer-input").value.trim();

    if (!cv || !jobOffer) {
        showError("offer-content-error", "Le CV et l'offre ne peuvent pas être vides.");
        return;
    }

    const saveBtn = document.getElementById("btn-save-offer-content");
    saveBtn.disabled = true;
    try {
        const response = await fetch(`/api/sessions/${state.currentSessionId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ cv, job_offer: jobOffer }),
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || "Erreur lors de la mise à jour.");
        }
        state.offerCv = cv;
        state.offerJobOffer = jobOffer;
        renderOfferContent();
        cancelEditOfferContent();
    } catch (err) {
        showError("offer-content-error", err.message);
    } finally {
        saveBtn.disabled = false;
    }
}

function renderInterviews() {
    const listEl = document.getElementById("interviews-list");
    const emptyEl = document.getElementById("interviews-empty");
    listEl.innerHTML = "";

    if (state.interviews.length === 0) {
        emptyEl.classList.remove("hidden");
        return;
    }
    emptyEl.classList.add("hidden");

    state.interviews.forEach((interview) => {
        const isFr = interview.language === "fr";
        const langLabel = isFr ? "FR" : "EN";
        const langClass = isFr ? "bg-indigo-100 text-indigo-700" : "bg-amber-100 text-amber-700";
        const progress = `${interview.feedback_count}/${interview.question_count} complétées`;

        const card = document.createElement("div");
        card.className =
            "text-left bg-white border border-slate-200 rounded-lg p-4 hover:ring-2 hover:ring-indigo-400 transition cursor-pointer";
        card.innerHTML = `
            <div class="flex items-start justify-between gap-2">
                <p class="font-medium text-slate-800">${interview.context}</p>
                <span class="text-xs font-semibold ${langClass} px-2 py-0.5 rounded-full flex-shrink-0">${langLabel}</span>
            </div>
            <p class="text-sm text-slate-500 mt-2">${progress}</p>
            <div class="flex gap-2 mt-3 justify-end">
                <button type="button" data-action="delete" aria-label="Supprimer l'entretien « ${interview.context} »" class="text-xs text-slate-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50 transition">Supprimer</button>
            </div>
        `;
        card.addEventListener("click", (e) => {
            if (e.target.closest("[data-action]")) return;
            loadInterview(interview.interview_id);
        });
        card.querySelector("[data-action='delete']").addEventListener("click", (e) => {
            e.stopPropagation();
            deleteInterview(interview.interview_id, interview.context);
        });
        listEl.appendChild(card);
    });
}

async function deleteInterview(interviewId, context = "cet entretien") {
    const confirmed = await showConfirmModal({
        title: "Supprimer l'entretien",
        message: `Supprimer définitivement l'entretien « ${context} » ainsi que toutes ses questions et réponses ? Cette action est irréversible.`,
        confirmLabel: "Supprimer",
    });
    if (!confirmed) return;
    try {
        const resp = await fetch(`/api/interviews/${interviewId}`, { method: "DELETE" });
        if (!resp.ok) throw new Error("Erreur lors de la suppression.");
        await loadOfferDetail(state.currentSessionId);
    } catch (err) {
        showError("interview-error", err.message);
    }
}

function toggleAddInterviewForm() {
    const form = document.getElementById("add-interview-form");
    const btn = document.getElementById("btn-toggle-add-interview");
    const willShow = form.classList.contains("hidden");
    form.classList.toggle("hidden");
    btn.textContent = willShow ? "− Annuler" : "+ Ajouter un entretien";
}

async function addInterview() {
    hideError("interview-error");

    const context = document.getElementById("interview-context").value.trim();
    const language = document.getElementById("interview-language").value;

    if (!context) {
        showError("interview-error", "Veuillez indiquer le type d'entretien.");
        return;
    }

    const btn = document.getElementById("btn-add-interview");
    btn.disabled = true;
    btn.textContent = "Génération en cours...";

    try {
        const response = await fetch(`/api/sessions/${state.currentSessionId}/interviews`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ context, language }),
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || "Erreur lors de la génération.");
        }

        document.getElementById("interview-context").value = "";
        document.getElementById("interview-language").value = "fr";
        document.getElementById("add-interview-form").classList.add("hidden");
        document.getElementById("btn-toggle-add-interview").textContent = "+ Ajouter un entretien";

        await loadOfferDetail(state.currentSessionId);
    } catch (err) {
        showError("interview-error", err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = "Générer les questions";
    }
}

async function loadInterview(interviewId) {
    hideError("interview-error");

    try {
        const response = await fetch(`/api/interviews/${interviewId}`);
        const data = await response.json();

        if (response.status === 404) {
            showError("interview-error", "Cet entretien n'existe plus.");
            await loadOfferDetail(state.currentSessionId);
            return;
        }

        if (!response.ok) {
            throw new Error(data.error || "Erreur lors du chargement de l'entretien.");
        }

        state.currentInterviewId = data.interview_id;
        state.currentInterviewContext = data.context;
        state.currentInterviewLanguage = data.language;
        state.questions = data.questions || [];
        state.feedbacks = data.feedbacks || {};
        state.currentQuestionIndex = null;
        renderSpeechDashboard(data.speech_stats);

        renderQuestions();
        showView("questions");
    } catch (err) {
        showError("interview-error", err.message);
    }
}

function renderQuestions() {
    const grid = document.getElementById("questions-grid");
    grid.innerHTML = "";

    const hasValidatedPlan = state.questions.some((_, i) => getFeedback(i)?.validated_plan_text);
    const hasValidatedAnswer = state.questions.some((_, i) => getFeedback(i)?.validated_answer_text);

    const plansLink = document.getElementById("export-plans-link");
    plansLink.href = `/api/interviews/${state.currentInterviewId}/export/plans`;
    plansLink.classList.toggle("hidden", !hasValidatedPlan);

    const answersLink = document.getElementById("export-answers-link");
    answersLink.href = `/api/interviews/${state.currentInterviewId}/export/answers`;
    answersLink.classList.toggle("hidden", !hasValidatedAnswer);

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

let questionSearchDebounce = null;

function openQuestionSearch() {
    showView("questionSearch");
    document.getElementById("question-search-input").focus();
}

function performQuestionSearch() {
    const query = document.getElementById("question-search-input").value.trim();
    const loadingEl = document.getElementById("question-search-loading");
    const resultsEl = document.getElementById("question-search-results");
    const emptyEl = document.getElementById("question-search-empty");
    const hintEl = document.getElementById("question-search-hint");
    hideError("question-search-error");

    if (query.length < 2) {
        resultsEl.innerHTML = "";
        emptyEl.classList.add("hidden");
        loadingEl.classList.add("hidden");
        hintEl.classList.remove("hidden");
        return;
    }

    hintEl.classList.add("hidden");
    emptyEl.classList.add("hidden");
    loadingEl.classList.remove("hidden");
    resultsEl.innerHTML = "";

    fetch(`/api/search/questions?q=${encodeURIComponent(query)}`)
        .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Erreur lors de la recherche.");
            const results = data.results || [];
            if (results.length === 0) {
                emptyEl.classList.remove("hidden");
            } else {
                renderQuestionSearchResults(results);
            }
        })
        .catch((err) => showError("question-search-error", err.message))
        .finally(() => loadingEl.classList.add("hidden"));
}

function renderQuestionSearchResults(results) {
    const resultsEl = document.getElementById("question-search-results");
    resultsEl.innerHTML = "";

    results.forEach((result) => {
        const isFr = result.language === "fr";
        const langLabel = isFr ? "FR" : "EN";
        const langClass = isFr ? "bg-indigo-100 text-indigo-700" : "bg-amber-100 text-amber-700";
        const statusBadge = result.answered
            ? '<span class="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">Complétée 🔊</span>'
            : '<span class="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">Non répondue</span>';

        const card = document.createElement("button");
        card.type = "button";
        card.className = "w-full text-left rounded-xl shadow-sm border border-slate-200 bg-white p-4 hover:ring-2 hover:ring-indigo-400 transition";
        card.innerHTML = `
            <div class="flex items-center justify-between gap-2 flex-wrap">
                <span class="text-xs text-slate-500">${result.offer_title} · ${result.context}</span>
                <div class="flex items-center gap-2">
                    <span class="text-xs font-semibold ${langClass} px-2 py-0.5 rounded-full">${langLabel}</span>
                    ${statusBadge}
                </div>
            </div>
            <p class="mt-2 text-slate-700">${result.question}</p>
        `;
        card.addEventListener("click", () => jumpToSearchResult(result));
        resultsEl.appendChild(card);
    });
}

async function jumpToSearchResult(result) {
    hideError("question-search-error");
    try {
        const response = await fetch(`/api/interviews/${result.interview_id}`);
        const data = await response.json();

        if (response.status === 404) {
            showError("question-search-error", "Cet entretien n'existe plus.");
            return;
        }
        if (!response.ok) throw new Error(data.error || "Erreur lors du chargement de l'entretien.");

        state.currentSessionId = result.session_id;
        state.offerTitle = result.offer_title;
        state.currentInterviewId = data.interview_id;
        state.currentInterviewContext = data.context;
        state.currentInterviewLanguage = data.language;
        state.questions = data.questions || [];
        state.feedbacks = data.feedbacks || {};

        selectQuestion(result.question_index);
    } catch (err) {
        showError("question-search-error", err.message);
    }
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
        updateRecordingReferencePanel(index);
        resetRecordingView();
        showRecordingMode();
    }

    showView("recording");
}

function resetRecordingView() {
    hideError("recording-error");
    setRecordingModeLocked(false);
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
    document.getElementById("video-preview-note").classList.add("hidden");
}

function startRerecording() {
    if (state.isAnalyzing) return;
    if (!confirmDiscardValidated()) return;
    stopMicrophone();
    updateRecordingReferencePanel(state.currentQuestionIndex);
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
            document.getElementById("video-preview-note").classList.remove("hidden");
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
        setRecordingModeLocked(true);

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
        setRecordingModeLocked(false);
        document.getElementById("recording-controls").classList.add("hidden");
        document.getElementById("analysis-loading").classList.remove("hidden");
        startAnalysisProgress();
    }
}


function setRecordingModeLocked(locked) {
    document.querySelectorAll('input[name="recording-mode"]').forEach((radio) => {
        radio.disabled = locked;
    });
}

function startAnalysisProgress() {
    const el = document.getElementById("analysis-step-text");
    let i = 0;
    el.textContent = ANALYSIS_STEPS[0];
    analysisStepInterval = setInterval(() => {
        i = Math.min(i + 1, ANALYSIS_STEPS.length - 1);
        el.textContent = ANALYSIS_STEPS[i];
    }, 4000);
}

function stopAnalysisProgress() {
    if (analysisStepInterval) {
        clearInterval(analysisStepInterval);
        analysisStepInterval = null;
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
    document.getElementById("video-preview-note").classList.add("hidden");
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
    formData.append("interview_id", state.currentInterviewId);
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
            showError("recording-error", "Entretien introuvable (serveur redémarré). Retournez à l'accueil.");
            document.getElementById("analysis-loading").classList.add("hidden");
            document.getElementById("recording-controls").classList.remove("hidden");
            await loadSessions();
            return;
        }

        if (!response.ok) {
            throw new Error(data.error || "Erreur lors de l'analyse.");
        }

        state.feedbacks[state.currentQuestionIndex] = data;
        renderSpeechDashboard(data.speech_stats);
        showConsultationMode(data);
    } catch (err) {
        document.getElementById("analysis-loading").classList.add("hidden");
        document.getElementById("recording-controls").classList.remove("hidden");
        showError("recording-error", err.message);
    } finally {
        state.isAnalyzing = false;
        setNavigationLocked(false);
        stopAnalysisProgress();
    }
}

function renderSpeechDashboard(speechStats) {
    const card = document.getElementById("speech-dashboard");
    const empty = document.getElementById("speech-dashboard-empty");
    const content = document.getElementById("speech-dashboard-content");
    const ticsBody = document.getElementById("speech-dashboard-tics");
    const advice = document.getElementById("speech-dashboard-advice");

    if (!speechStats) {
        card.classList.add("hidden");
        return;
    }
    card.classList.remove("hidden");

    const tics = speechStats.tics || [];
    if (tics.length === 0) {
        empty.classList.remove("hidden");
        content.classList.add("hidden");
        return;
    }
    empty.classList.add("hidden");
    content.classList.remove("hidden");
    ticsBody.innerHTML = tics
        .map(
            (t) =>
                `<tr><td class="text-slate-600 pr-2">"${t.phrase}"</td><td class="text-slate-500">${t.count} occurrences</td></tr>`
        )
        .join("");
    advice.textContent = speechStats.advice || "";
}

function displayFeedback(data) {
    document.getElementById("feedback-transcription").textContent = data.transcription;
    document.getElementById("feedback-content").innerHTML = marked.parse(data.analysis_content || "");
    document.getElementById("feedback-form").innerHTML = marked.parse(data.analysis_form || "");

    const sparklineContainer = document.getElementById("pacing-sparkline");
    const statsTable = document.getElementById("speech-stats-table");
    const segments = data.pacing_segments || [];
    if (segments.length > 0) {
        const width = 300;
        const height = 60;
        const maxWpm = Math.max(...segments.map((s) => s.wpm), 1);
        const points = segments
            .map((s, i) => {
                const x = (i / (segments.length - 1 || 1)) * width;
                const y = height - (s.wpm / maxWpm) * height;
                return `${x.toFixed(1)},${y.toFixed(1)}`;
            })
            .join(" ");
        sparklineContainer.innerHTML = `
            <svg viewBox="0 0 ${width} ${height}" class="w-full h-16">
                <polyline points="${points}" fill="none" stroke="#6366f1" stroke-width="2" />
            </svg>
        `;
        statsTable.classList.remove("hidden");
        document.getElementById("speech-stats-hesitations").textContent = data.hesitation_count ?? 0;
        const fillerCount = data.filler_word_count || {};
        const fillerText = Object.entries(fillerCount)
            .map(([word, count]) => `${word} (${count})`)
            .join(", ");
        document.getElementById("speech-stats-fillers").textContent = fillerText || "Aucun détecté";
    } else {
        sparklineContainer.innerHTML = "";
        statsTable.classList.add("hidden");
    }

    document.getElementById("feedback-ideal").textContent = data.ideal_answer_text;
    document.getElementById("feedback-plan").textContent = data.ideal_plan_text || "";
    document.getElementById("validated-plan-input").value = data.validated_plan_text ?? "";
    document.getElementById("validated-answer-input").value = data.validated_answer_text ?? "";
    hideError("validated-save-error");
    state.validatedDirty = false;

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
        document.getElementById("feedback-visual").innerHTML = marked.parse(data.analysis_visual || "");
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

    hideError("neutral-answer-error");
    const neutralBlock = document.getElementById("neutral-answer-block");
    const neutralBtn = document.getElementById("btn-neutral-answer");
    if (data.neutral_answer_text) {
        document.getElementById("feedback-neutral").textContent = data.neutral_answer_text;
        if (data.neutral_audio_url) {
            document.getElementById("neutral-audio").src = `${data.neutral_audio_url}?t=${Date.now()}`;
        }
        neutralBlock.classList.remove("hidden");
        neutralBtn.textContent = "Régénérer la réponse neutre";
    } else {
        neutralBlock.classList.add("hidden");
        neutralBtn.textContent = "Voir une réponse neutre basée sur le CV/l'offre";
    }
    neutralBtn.disabled = false;
}

async function generateNeutralAnswer() {
    const btn = document.getElementById("btn-neutral-answer");
    hideError("neutral-answer-error");
    btn.disabled = true;
    const previousLabel = btn.textContent;
    btn.textContent = "Génération en cours...";

    try {
        const response = await fetch("/api/generate-neutral-answer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                interview_id: state.currentInterviewId,
                question_index: state.currentQuestionIndex,
            }),
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || "Erreur lors de la génération.");
        }

        document.getElementById("feedback-neutral").textContent = data.neutral_answer_text;
        document.getElementById("neutral-audio").src = `${data.neutral_audio_url}?t=${Date.now()}`;
        document.getElementById("neutral-answer-block").classList.remove("hidden");

        const feedback = state.feedbacks[state.currentQuestionIndex];
        if (feedback) {
            feedback.neutral_answer_text = data.neutral_answer_text;
            feedback.neutral_audio_url = data.neutral_audio_url;
        }
        btn.textContent = "Régénérer la réponse neutre";
    } catch (err) {
        showError("neutral-answer-error", err.message);
        btn.textContent = previousLabel;
    } finally {
        btn.disabled = false;
    }
}

async function saveValidated() {
    const btn = document.getElementById("btn-save-validated");
    hideError("validated-save-error");
    btn.disabled = true;
    const previousLabel = btn.textContent;

    try {
        const response = await fetch("/api/save-validated", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                interview_id: state.currentInterviewId,
                question_index: state.currentQuestionIndex,
                validated_plan_text: document.getElementById("validated-plan-input").value,
                validated_answer_text: document.getElementById("validated-answer-input").value,
            }),
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || "Erreur lors de l'enregistrement.");
        }

        const feedback = state.feedbacks[state.currentQuestionIndex];
        if (feedback) {
            feedback.validated_plan_text = data.validated_plan_text;
            feedback.validated_answer_text = data.validated_answer_text;
        }
        state.validatedDirty = false;
        btn.textContent = "Enregistré ✓";
        setTimeout(() => { btn.textContent = previousLabel; }, 1500);
    } catch (err) {
        showError("validated-save-error", err.message);
        btn.textContent = previousLabel;
    } finally {
        btn.disabled = false;
    }
}

function updateRecordingReferencePanel(index) {
    const panel = document.getElementById("recording-reference-panel");
    const content = document.getElementById("recording-reference-content");
    const feedback = getFeedback(index);
    const plan = feedback ? feedback.validated_plan_text : "";
    const answer = feedback ? feedback.validated_answer_text : "";

    if (!plan && !answer) {
        panel.classList.add("hidden");
        return;
    }

    document.getElementById("recording-reference-plan").textContent = plan || "";
    document.getElementById("recording-reference-answer").textContent = answer || "";
    content.classList.remove("hidden");
    panel.classList.remove("hidden");
}

document.getElementById("btn-create-offer").addEventListener("click", createOffer);
document.getElementById("btn-record").addEventListener("click", toggleRecording);
document.getElementById("btn-rerecord").addEventListener("click", startRerecording);
document.getElementById("btn-neutral-answer").addEventListener("click", generateNeutralAnswer);
document.getElementById("btn-back-home-offer").addEventListener("click", goToSetup);
document.getElementById("nav-home").addEventListener("click", goToSetup);
document.getElementById("btn-back-to-offer").addEventListener("click", goToOffer);
document.getElementById("btn-back-to-questions").addEventListener("click", goToQuestions);
document.getElementById("btn-back-questions-consult").addEventListener("click", goToQuestions);
document.getElementById("btn-show-archived").addEventListener("click", showArchivedSection);
document.getElementById("btn-hide-archived").addEventListener("click", hideArchivedSection);
document.getElementById("btn-toggle-add-interview").addEventListener("click", toggleAddInterviewForm);
document.getElementById("btn-toggle-offer-content").addEventListener("click", toggleOfferContent);
document.getElementById("btn-edit-offer-content").addEventListener("click", startEditOfferContent);
document.getElementById("btn-save-offer-content").addEventListener("click", saveOfferContent);
document.getElementById("btn-cancel-offer-content").addEventListener("click", cancelEditOfferContent);
document.getElementById("btn-add-interview").addEventListener("click", addInterview);
document.getElementById("sessions-search").addEventListener("input", applySessionsFilter);
document.getElementById("btn-open-question-search").addEventListener("click", openQuestionSearch);
document.getElementById("btn-back-home-search").addEventListener("click", goToSetup);
document.getElementById("question-search-input").addEventListener("input", () => {
    clearTimeout(questionSearchDebounce);
    questionSearchDebounce = setTimeout(performQuestionSearch, 300);
});
document.getElementById("breadcrumb").addEventListener("click", (e) => {
    const offerEl = e.target.closest("#breadcrumb-offer");
    if (!offerEl || !state.currentSessionId) return;
    e.stopPropagation();
    startTitleEdit(offerEl, state.currentSessionId, () => loadSessions());
});

document.getElementById("btn-save-validated").addEventListener("click", saveValidated);
["validated-plan-input", "validated-answer-input"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
        state.validatedDirty = true;
    });
});

document.querySelectorAll('input[name="recording-mode"]').forEach((radio) => {
    radio.addEventListener("change", (e) => {
        state.recordingMode = e.target.value;
    });
});

window.addEventListener("beforeunload", (e) => {
    if (!state.validatedDirty) return;
    e.preventDefault();
    e.returnValue = "";
});

document.addEventListener("DOMContentLoaded", loadSessions);
