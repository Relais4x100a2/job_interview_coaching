# Analyse d'élocution post-enregistrement et refonte dashboard

Date : 2026-09-24

## Contexte

Une première itération avait ajouté un coaching *live* pendant l'enregistrement
(débit de parole en direct via Web Speech API, détection de "euh" via
transcription puis via analyse audio Web Audio API). Après test manuel, ce
coaching en direct s'est révélé peu utile ("ce n'est pas très intéressant
d'avoir ces retours en live") et doit être retiré intégralement.

À la place, l'analyse de l'élocution se fait **après coup**, à partir du
fichier audio déjà envoyé à Whisper pour la transcription — sans nouveau flux
audio, sans dépendance à la reconnaissance vocale du navigateur.

Par ailleurs, l'écran d'enregistrement et l'écran de feedback souffrent d'un
empilement vertical dense ("on s'y perd") et doivent passer en mise en page
dashboard multi-colonnes.

## Objectifs

1. Par réponse : débit de parole **glissant** dans le temps (pas juste une
   moyenne mots/durée), détection d'hésitations, comptage best-effort des
   mots de remplissage ("euh", "um"...), le tout affiché dans le feedback.
2. Par entretien : détection des tics de langage récurrents (tournures qui
   reviennent) sur l'ensemble des réponses déjà analysées, avec des conseils
   de reformulation générés par le LLM. Recalculé automatiquement après
   chaque nouvelle réponse analysée.
3. Fonctionne aussi bien en français qu'en anglais (langue de l'entretien).
4. Écran d'enregistrement en 2 colonnes (caméra/contrôles à gauche, plan et
   réponse validés à droite).
5. Écran de feedback en grille de cartes (dashboard), plus lisible qu'une
   colonne unique d'accordéons.
6. Suppression complète du coaching live (WPM live + hésitation live)
   ajouté dans l'itération précédente.

## Non-objectifs

- Pas de refonte de l'écran d'accueil ni de l'écran de détail d'offre.
- Pas de librairie de graphes externe (sparkline en `<svg>` inline).
- Pas de migration de schéma SQL (tout passe par les colonnes JSON
  existantes `interviews.data` / `feedbacks`).

## Architecture

### Pipeline backend (`services/ai_service.py`)

`transcribe_audio` change de signature : au lieu de renvoyer seulement le
texte, il demande à Whisper `response_format="verbose_json"` avec
`timestamp_granularities=["word"]` et renvoie `(text, words)` où `words` est
une liste `{word, start, end}`. Même modèle, même coût, une seule requête.

Deux nouvelles fonctions pures (pas d'appel LLM, testables isolément) :

- `analyze_speech_pacing(words: list[dict]) -> dict`
  - Débit glissant : fenêtre roulante de 10s, pas de 2s, sur toute la durée
    de la réponse → liste `{start_s, end_s, wpm}`.
  - Hésitations : un silence entre deux mots consécutifs de 250 à 1200 ms,
    survenant après au moins 400 ms de parole continue, compte comme une
    hésitation. Retourne le nombre total et la liste des timestamps.
  - Si `words` est vide (échec Whisper, silence total), retourne des
    structures vides plutôt que de lever une exception.

- `detect_tics(transcriptions: list[str], language: str) -> list[{phrase, count}]`
  - Recherche de n-grammes (2 à 4 mots) qui se répètent au moins 2 fois dans
    l'ensemble des transcriptions fournies.
  - Filtre les n-grammes composés uniquement de mots vides, à partir d'une
    liste de stopwords **par langue** (`fr`/`en`).
  - Utilisée à la fois pour une réponse seule (liste à un élément) et pour
    l'agrégat de l'entretien (toutes les transcriptions déjà sauvegardées).

Comptage best-effort des mots de remplissage littéraux, par regex sur le
texte transcrit, avec un jeu de motifs par langue (reprend l'esprit de
`LIVE_FILLER_PATTERNS` de l'itération précédente, mais appliqué côté serveur
au texte Whisper — accepté comme indicatif, peut sous-estimer si Whisper
« nettoie » le mot).

Nouvelle fonction avec appel LLM, courte :

- `generate_tics_advice(tics: list[dict], filler_counts: dict, language: str) -> str`
  - Toujours rédigée en français (même convention que `analysis_content` /
    `analysis_form` existants), même si l'entretien est en anglais — cite les
    tics dans leur langue d'origine.
  - Prend en entrée les tics + compteurs de fillers détectés, produit un
    texte de conseils concrets de reformulation.

### Modèle de données (JSON existant, pas de migration)

Par réponse, le dict `feedback` (déjà stocké via `save_feedback`) gagne :
`pacing_segments`, `hesitation_count`, `hesitation_timestamps`,
`filler_word_count`.

Par entretien, nouveau champ `speech_stats` dans `interviews.data` :
```json
{
  "tics": [{"phrase": "du coup", "count": 5}],
  "filler_totals": {"euh": 12, "du coup": 5},
  "advice": "texte généré par le LLM"
}
```
Recalculé et réécrit intégralement à chaque nouvelle réponse analysée, à
partir de **toutes** les transcriptions déjà sauvegardées pour cet entretien
(pas de fusion incrémentale — recalcul complet, source de vérité simple).

### API

- `POST /api/analyze-answer` : la réponse JSON gagne `pacing_segments`,
  `hesitation_count`, `filler_word_count` (mergés dans le feedback comme les
  champs existants), et `speech_stats` (agrégat entretien recalculé), pour
  que le frontend mette à jour le dashboard sans refetch.
- `GET /api/interviews/<interview_id>` : la réponse gagne `speech_stats`.
- Pas de nouvel endpoint.

### Gestion des erreurs

Si `analyze_speech_pacing`, `detect_tics` ou `generate_tics_advice`
échouent (timeout LLM, réponse Whisper sans timestamps, etc.), l'erreur est
capturée et loguée sans faire échouer `/api/analyze-answer` dans son
ensemble : le feedback principal (transcription, fond, forme, réponse
idéale) reste produit normalement, avec les champs de stats à `null`/vides.

## Frontend

### Écran d'enregistrement (`templates/index.html`, `#recording-mode`)

Passe de `space-y-4` à `grid md:grid-cols-2 gap-4` :
- **Gauche** : `#recording-controls` inchangé, sans le bloc `#live-coaching`
  (supprimé, voir section suppression).
- **Droite** : `#recording-reference-panel`, dépliée par défaut (le toggle
  "Afficher mes notes validées" disparaît — la colonne dédiée a la place de
  l'afficher directement).

`#analysis-loading` et `#recording-error` restent en pleine largeur sous la
grille.

### Écran de feedback (`#consultation-mode`)

Passe d'une liste de `<details>` empilés à `grid md:grid-cols-2 xl:grid-cols-3
gap-4`, cartes toujours visibles (`bg-white rounded-xl shadow-md p-4`) :

1. Votre enregistrement (lecteur audio/vidéo)
2. Transcription
3. Analyse du fond
4. Analyse de la forme — texte LLM + sparkline du débit glissant (SVG inline
   généré en JS à partir de `pacing_segments`) + tableau hésitations/fillers
5. Analyse du non-verbal (mode vidéo uniquement, conditionnel comme
   aujourd'hui)
6. Réponse idéale du LLM — fusion plan idéal + réponse idéale + audio +
   bouton réponse neutre
7. Vos notes validées — fusion plan validé + réponse validée (2 textareas +
   bouton enregistrer)

Boutons "Recommencer" / "Choisir une autre question" en pleine largeur sous
la grille.

### Dashboard agrégé de l'entretien (`view-questions`)

Nouvelle carte `#speech-dashboard` au-dessus de `#questions-grid`, masquée
tant qu'aucune réponse n'a été analysée pour l'entretien. Remplie depuis
`speech_stats` (chargé via `GET /api/interviews/<id>`, mis à jour en place
après chaque `POST /api/analyze-answer` sans refetch) :
- Tableau des tics récurrents (phrase / occurrences).
- Totaux des mots de remplissage par type.
- Texte de conseils du LLM.

Si `speech_stats` est vide ou sans tics significatifs, message neutre
("Pas encore assez de matière pour dégager des tendances").

### Suppression du coaching live

Retrait complet dans `static/js/app.js` : `startLiveCoaching`,
`stopLiveCoaching`, `startWpmTracking`, `stopWpmTracking`,
`registerLiveWords`, `startHesitationDetector`, `stopHesitationDetector`,
`registerHesitation`, les constantes associées (`LIVE_WPM_*`,
`HESITATION_*`, `AUDIO_SAMPLE_INTERVAL_MS`, `SILENCE_RMS_THRESHOLD`), les
champs `state` correspondants (`speechRecognition`, `liveCoachingActive`,
`liveCoachingInterval`, `liveWordEvents`, `liveFillerCount`,
`liveInterimResultIndex`, `liveInterimWordCount`, `hesitationAudioCtx`,
`hesitationInterval`), et leurs appels dans `toggleRecording`,
`resetRecordingView`, `stopRecording`.

Dans `templates/index.html` : suppression du bloc `#live-coaching`.

`state.currentInterviewLanguage` est conservé (utile si le frontend a besoin
de la langue pour l'affichage ; la détection des tics/fillers elle-même est
entièrement côté backend via `interview["language"]`).

## Plan de tests

- Nouveau : tests unitaires purs pour `analyze_speech_pacing` (fenêtre
  glissante, silences dans/hors bornes) et `detect_tics` (n-grammes répétés,
  filtrage stopwords fr/en) — fonctions déterministes sans dépendance
  externe.
- `tests/test_app.py` : mock de `transcribe_audio` (renvoie désormais
  `(text, words)`), `analyze_answer`, `generate_tics_advice` ; vérifie que
  `/api/analyze-answer` renvoie `pacing_segments`/`hesitation_count`/
  `filler_word_count`/`speech_stats`, et que `GET /api/interviews/<id>`
  renvoie `speech_stats`.
- `tests/test_storage.py` : sauvegarde/lecture de `speech_stats`, valeur par
  défaut si jamais calculé.
- Frontend : pas de suite de tests JS existante ; vérification par
  `node --check` + test manuel navigateur (sparkline, grilles, panneau de
  référence).

## Risques et limites connues

- Les seuils de détection d'hésitation (250–1200 ms, 400 ms de parole
  minimum) sont des valeurs de départ ; à ajuster après retour terrain de
  l'utilisateur, comme pour l'itération précédente.
- Le comptage littéral des mots de remplissage reste best-effort (dépend de
  ce que Whisper transcrit verbatim ou non) ; le signal principal et fiable
  reste la détection de silence par timestamps.
- Impossible de valider avec un audio réel dans le bac à sable navigateur
  automatisé (`getUserMedia` bloque sur la demande de permission micro) ;
  validation manuelle par l'utilisateur nécessaire comme précédemment.
