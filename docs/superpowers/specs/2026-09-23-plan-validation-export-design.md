# Plan idéal, versions validées et export — Design

Date: 2026-09-23

## Contexte et objectif

Aujourd'hui, l'écran de consultation d'une réponse (`view-recording` /
`consultation-mode`) affiche uniquement une "Réponse idéale" générée par le
LLM à chaque analyse, régénérée intégralement (donc perdue) à chaque
réenregistrement.

L'utilisateur veut pouvoir :
1. Voir non seulement la réponse idéale du LLM mais aussi le plan qui la
   structure.
2. Conserver ses propres versions retravaillées du plan et de la réponse
   ("validées"), qui survivent aux réenregistrements et ne sont modifiables
   que par lui.
3. Se resservir de ces versions validées comme support visuel pendant qu'il
   se réenregistre.
4. Exporter, entretien par entretien, l'ensemble des plans validés d'un
   côté et l'ensemble des réponses validées de l'autre.

La fonctionnalité "réponse neutre" (CV/offre, indépendante de la
transcription du candidat) est explicitement laissée telle quelle, en
dehors de ce nouveau flux.

## Modèle de données

Le blob JSON `feedback` d'une question (`sessions.feedbacks` /
`InMemoryStorage`) gagne 3 clés, sans migration de schéma nécessaire
(cohérent avec le schéma hybride décrit dans `CLAUDE.md`) :

- `ideal_plan_text` (str) — plan structuré généré par le LLM, régénéré à
  chaque analyse au même titre que `ideal_answer_text`.
- `validated_plan_text` (str) — version retravaillée par l'utilisateur.
- `validated_answer_text` (str) — version retravaillée par l'utilisateur.

Règle de persistance (le point le plus important du design) :

- Si `validated_plan_text` / `validated_answer_text` **n'existent pas
  encore** dans le feedback existant d'une question (premier passage), ils
  sont initialisés avec la valeur LLM fraîchement générée
  (`ideal_plan_text` / `ideal_answer_text`) au moment de l'analyse.
- Si ces clés **existent déjà** — y compris si leur valeur est une chaîne
  vide `""` volontairement effacée par l'utilisateur — elles sont
  recopiées telles quelles dans le nouveau feedback à chaque
  réenregistrement, quel que soit le nombre de réenregistrements
  effectués depuis : jamais régénérées, jamais écrasées par une nouvelle
  analyse LLM. Seule la sauvegarde explicite via le nouvel endpoint dédié
  peut les modifier. Ce comportement est voulu : les box "... selon LLM"
  donnent accès à la version fraîche à tout moment, et l'utilisateur
  reporte manuellement ce qu'il veut garder dans sa version validée — le
  système ne doit jamais décider à sa place de rafraîchir une version
  qu'il a déjà figée.
- Implémentation : le report doit tester la **présence de la clé**
  (`"validated_plan_text" in existing_feedback`), pas sa valeur "truthy",
  pour distinguer une chaîne vide déjà validée d'une clé jamais créée.

## Backend

### `services/ai_service.py`

`analyze_answer()` : le prompt système demande une clé JSON
supplémentaire `ideal_plan_text` (plan en 3 à 5 points résumant la
structure de la réponse idéale, **rédigé en Markdown à puces**, dans la
langue de l'entretien, produit dans le même appel que `ideal_answer_text`
— pas d'appel LLM supplémentaire). Ajouté à `required_keys`, casté en
`str(data["ideal_plan_text"])` au retour, comme les autres champs — au
cas où le LLM renverrait autre chose qu'une chaîne (liste, objet) malgré
la consigne de prompt.

`generate_neutral_ideal_answer()` : inchangé (pas de plan pour la réponse
neutre, décision confirmée).

### `app.py`

`POST /api/analyze-answer` : après l'appel à `ai_service.analyze_answer`,
avant `storage.save_feedback` :
1. Lire le feedback existant de la question via
   `storage.get_interview(interview_id)["feedbacks"].get(question_index, {})`
   (même pattern que celui déjà utilisé par `generate_neutral_answer`).
2. Pour `validated_plan_text` et `validated_answer_text` : si la clé est
   présente dans l'existant, la recopier dans le nouveau `feedback` ; sinon
   l'initialiser avec `ideal_plan_text` / `ideal_answer_text` fraîchement
   générés.

Nouvel endpoint `POST /api/save-validated` :
- Corps JSON : `interview_id`, `question_index`, `validated_plan_text`,
  `validated_answer_text`.
- Valide les champs obligatoires comme les autres endpoints (`BadRequest`
  si manquants).
- Charge l'entretien (`get_interview_with_session`, 404 si absent), charge
  le feedback existant de la question ; si absent → 404 (une question doit
  avoir été analysée avant d'avoir une version validée).
- Met à jour uniquement `validated_plan_text` et `validated_answer_text`
  dans le feedback existant, `storage.save_feedback`, retourne le feedback
  mis à jour.

Nouveaux endpoints d'export, scope par entretien :
- `GET /api/interviews/<interview_id>/export/plans`
- `GET /api/interviews/<interview_id>/export/answers`

Les questions sont parcourues **triées par `question_index` numérique**
(les clés du dict `feedbacks` peuvent être des chaînes selon
`_deserialize_feedbacks` — trier sur `int(key)`, pas sur l'ordre naturel
du dict, pour garantir l'ordre de l'entretien dans le document généré).

Pour chaque question de l'entretien ayant un `validated_plan_text` (resp.
`validated_answer_text`) non vide, génère une section Markdown :

```
## Question <n> : <texte de la question>

<validated_plan_text ou validated_answer_text>
```

Réponse Flask avec `mimetype="text/markdown; charset=utf-8"` et
`Content-Disposition: attachment; filename="<interview_id>-plans.md"`
(resp. `-reponses.md`) — `interview_id` est déjà un identifiant sûr pour un
nom de fichier (pas de dérivation à partir du champ libre `context`). Le
charset explicite évite les problèmes d'accents à l'ouverture du fichier
sur certains lecteurs (notamment Windows).
404 si l'entretien n'existe pas. Si aucune question n'a de contenu validé,
fichier avec un message "Aucun contenu validé pour le moment." plutôt
qu'une erreur.

## Frontend

### `templates/index.html`

Dans `consultation-mode` :
- Renommer le `<h3>` de "Réponse idéale" en "Réponse idéale selon LLM"
  (id `feedback-ideal` inchangé).
- Ajouter juste au-dessus une nouvelle box "Plan idéal selon LLM"
  (lecture seule, même style que la box réponse idéale), nouvel id
  `feedback-plan`.
- Après le bloc réponse idéale / réponse neutre (inchangé), ajouter deux
  nouvelles box éditables, dans cet ordre :
  - "Plan validé (vous)" — `<textarea id="validated-plan-input">`
  - "Réponse validée (vous)" — `<textarea id="validated-answer-input">`
  - Un seul bouton "Enregistrer" (`btn-save-validated`) sous les deux
    textareas, qui poste les deux valeurs ensemble.
  - Zone d'erreur `validated-save-error` (même pattern que les autres
    zones d'erreur de l'écran).

Dans `recording-mode`, ajouter un encart optionnel avant
`recording-controls`, id `recording-reference-panel`, caché par défaut,
style visuellement "fil de fer" (fond très clair, bordure pointillée,
texte atténué) affichant en lecture seule le plan et la réponse validés de
la question en cours, quand ils existent. Le contenu est **replié par
défaut** derrière un lien "Afficher mes notes validées" (bascule vers
"Masquer mes notes validées") pour ne pas envahir l'écran pendant que
l'utilisateur s'enregistre, surtout si le plan/la réponse sont longs.

Dans `view-questions` (liste des questions d'un entretien), ajouter deux
liens/boutons "Exporter tous les plans validés" et "Exporter toutes les
réponses validées" pointant vers les endpoints d'export (navigation
directe, pas de fetch JS — le navigateur déclenche le téléchargement).

### `static/js/app.js`

- `displayFeedback(data)` : renseigner `feedback-plan` avec
  `data.ideal_plan_text`, et pré-remplir `validated-plan-input` /
  `validated-answer-input` avec `data.validated_plan_text` /
  `data.validated_answer_text`.
- Nouvelle fonction `saveValidated()` : lit les deux textareas, POST vers
  `/api/save-validated` avec `interview_id`/`question_index` courants, met
  à jour `state.feedbacks[currentQuestionIndex]` avec la réponse, affiche
  une confirmation brève (ex: texte du bouton "Enregistré ✓" puis retour à
  "Enregistrer" après un court délai) ou l'erreur dans
  `validated-save-error`.
- `selectQuestion(index)` et `startRerecording()` : avant d'appeler
  `showRecordingMode()`, lire `getFeedback(index)` ; si elle contient
  `validated_plan_text`/`validated_answer_text`, remplir
  `recording-reference-panel` (replié) ; sinon le cacher entièrement.
  C'est naturellement vide au tout premier enregistrement (aucun feedback
  existant).
- `startRerecording()` (déclenché par `btn-rerecord`) : avant de
  poursuivre, vérifier si `validated-plan-input` / `validated-answer-input`
  contiennent des modifications non enregistrées depuis le dernier
  `saveValidated()` réussi (état `isDirty` maintenu par un listener
  `input` sur les deux textareas, réinitialisé à `false` après un
  enregistrement réussi ou un chargement de feedback). Si `isDirty`,
  afficher une confirmation navigateur ("Vous avez des modifications non
  enregistrées dans le plan/la réponse validés. Continuer sans les
  enregistrer ?") avant de poursuivre ; annuler le réenregistrement si
  l'utilisateur refuse.
- Rendu de la liste des questions (`view-questions`) : ajouter les
  attributs `href` des deux liens d'export en fonction de
  `state.currentInterviewId` lors du rendu de l'écran.

## Gestion des erreurs

- `POST /api/save-validated` sur une question jamais analysée → 404,
  message clair, affiché dans `validated-save-error` côté client.
- Les endpoints d'export sur un `interview_id` inexistant → 404 (cohérent
  avec le reste de l'API, géré par le `errorhandler(NotFound)` existant).
- Aucun nouveau cas d'erreur silencieuse : les échecs de sauvegarde/export
  utilisent les mêmes handlers globaux (`BadRequest`, `NotFound`,
  `Exception`) déjà en place dans `app.py`.

## Tests

- `tests/test_app.py` : mock de `ai_service.analyze_answer` étendu avec
  `ideal_plan_text` dans le retour simulé.
- Nouveau test : deux appels successifs à `/api/analyze-answer` sur la
  même question — le second ne doit pas changer
  `validated_plan_text`/`validated_answer_text` s'ils ont été modifiés
  entre-temps via `/api/save-validated`.
- Nouveau test : premier appel à `/api/analyze-answer` initialise bien
  `validated_plan_text`/`validated_answer_text` avec les valeurs LLM.
- Nouveau test : `POST /api/save-validated` met à jour uniquement les deux
  champs concernés (le reste du feedback, ex. `analysis_content`, reste
  inchangé) et renvoie 404 si la question n'a pas de feedback existant.
- Nouveau test : si l'utilisateur vide `validated_plan_text` (chaîne vide
  enregistrée via `/api/save-validated`), un réenregistrement suivant
  préserve la chaîne vide et ne la remplace pas par le nouveau
  `ideal_plan_text`.
- Nouveau test par export : contenu Markdown correct **et ordonné par
  `question_index`** même si les questions sont analysées dans le
  désordre, question sans contenu validé exclue, entretien inexistant →
  404.
- `tests/test_storage.py` : pas de changement de comportement du stockage
  attendu (le feedback reste un dict opaque pour `save_feedback`), donc
  pas de nouveau test requis à ce niveau sauf si l'implémentation
  introduit une nouvelle méthode de storage (non prévu par ce design).

## Hors périmètre

- La fonctionnalité "réponse neutre" (CV/offre) n'est pas modifiée.
- Pas de plan pour la réponse neutre.
- Pas d'export global (toutes offres) ni par offre — uniquement par
  entretien.
- Pas de format PDF — export Markdown uniquement.
