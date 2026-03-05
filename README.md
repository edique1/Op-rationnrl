# CPGE MP Concours FAQ Analyzer

Mini site statique pour classer les themes les plus frequents (mots cles) en Maths/Physique dans les banques:
- X-ENS
- Centrale
- Mines-Ponts
- CCINP

## Fonctions
- Filtre par banque
- Filtre par annees (inclusion/exclusion annee par annee)
- Filtre par matiere (Maths XOR Physique, choix unique)
- Filtre par type(s) de sujet(s) (Exercice, TP, etc.)
- Recherche texte sur le theme
- Calcul automatique du nombre d'apparitions
- Classement des themes strictement par nombre d'occurrences
- Details exacts de chaque apparition (annee, banque, epreuve, section)

## Lancer le site
Depuis ce dossier:

```bash
cd "/Users/vkank/Documents/app projects/cpge-concours-faq"
python3 -m http.server 8080
```

Puis ouvrir `http://localhost:8080`.

## Mettre a jour les donnees BEOS brutes
Le dataset brut est extrait depuis BEOS (filiere MP, matieres Maths/Physique, concours cibles).

Commande:

```bash
python3 scripts/fetch_beos.py
```

## Appliquer une classification GPT (recommande)
Pour reconstruire `data.js` avec les themes classes par ChatGPT (fichier par exercice avec champ `id` + `theme`):

```bash
python3 scripts/apply_gpt_classification.py \
  --classified "json exports from gpt/all_exercises_classified.json"
```

Le site classe alors les themes par nombre d'occurrences en utilisant cette classification.

## Extraire les details exercice (optionnel, hors interface principale)
Etape 1: parser chaque page `sujet.php?id=...`:

```bash
python3 scripts/build_exercise_analysis.py --resume
```

Etape 2: produire une proposition de regroupement contextuel depuis le detail:

```bash
python3 scripts/reclassify_by_context.py
```

Fichiers produits:
- `exercise_analyses.json`: details complets (enonce, indications, commentaires, propositions contextuelles)
- `exercise_analyses.js`: version compacte (non utilisee par l'interface principale)
- `exercise_analyses_cache.jsonl`: checkpoint de reprise

## Exporter un paquet complet pour classification ChatGPT
Pour generer un fichier unique avec chaque exercice + mots-cles + detail complet:

```bash
python3 scripts/export_chatgpt_payload.py
```

Fichiers exportes dans `chatgpt_exports/`:
- `chatgpt_classification_input.json` (fichier principal complet)
- `chatgpt_classification_input.jsonl`
- `chatgpt_classification_prompt.md` (prompt conseille a coller dans ChatGPT)
- `chunks/chatgpt_input_chunk_XXX.json` (version morcelee si besoin)
