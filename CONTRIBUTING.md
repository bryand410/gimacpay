# Contribuer

Merci. Ce dépôt implémente une spécification qui n'appartient pas à ses contributeurs, donc
la première règle est simple : **la spécification est l'autorité.**

## Avant de proposer quoi que ce soit

```bash
python -m venv .venv && . .venv/bin/activate     # Windows : .venv\Scripts\activate
pip install -e ".[dev]"
pytest
ruff check .
```

Les deux doivent passer. La suite est rapide et n'a pas besoin de réseau : elle démarre un
serveur HTTP local qui parle le protocole documenté.

## Les règles du dépôt

### 1. Zéro dépendance d'exécution

Non négociable. Voir `SECURITY.md` pour le raisonnement. Une pull request qui ajoute une
entrée à `[project].dependencies` sera refusée, même pour quelque chose d'aussi banal que
`requests`. `urllib` fait le travail.

Les dépendances de développement sont libres.

### 2. Ne jamais deviner l'état d'un paiement

C'est la règle centrale, tirée de la spécification :

> Participants should not guess the state if it's not given by GIMACPay.

Concrètement, dans le code :

- Un code de réponse non documenté produit `PaymentStateUnknown`, **jamais**
  `PaymentRejected`.
- `PaymentStateUnknown` et `PaymentRejected` restent des classes **sœurs**. Ne les faites
  jamais hériter l'une de l'autre.
- Une erreur de transport ne doit pas être transformée en échec du paiement.
- Un `200` ne signifie pas « accepté ». Vérifiez `payment.state`.

Si votre changement touche à ça, ajoutez un test qui échoue sans lui.

### 3. La spécification est la source, pas la mémoire

Les tables de `intents.py` sont dérivées de `docs/reference/gimac-api-1.10.yaml`. Les tests
comparent les deux. Si GIMAC publie une nouvelle version de la spécification :

1. remplacez le fichier dans `docs/reference/` ;
2. lancez `pytest` — les tests de version et d'énumération échoueront et vous diront quoi
   mettre à jour ;
3. mettez à jour `REQUIRED_FIELDS` à partir des nouveaux exemples.

Ne devinez pas les champs requis. Ils viennent des exemples travaillés de la spécification,
qui sont les seules charges utiles normatives qu'elle publie.

### 4. La licence de la spécification

`docs/reference/gimac-api-1.10.yaml` porte `license: Private`. Il est présent comme
référence de développement et **exclu de tout artefact publié** (voir l'exclusion `sdist`
dans `pyproject.toml`). Ne le déplacez pas dans `src/`, ne l'embarquez pas dans le paquet,
ne le publiez pas ailleurs.

### 5. Style

`ruff` décide, pas vous et pas moi. `line-length = 100`, `target-version = "py39"`.

Les docstrings expliquent **pourquoi**, pas **quoi**. Le code dit déjà ce qu'il fait. Une
docstring qui paraphrase la signature est du bruit ; une docstring qui explique pourquoi le
`except` est dans cet ordre vaut de l'or.

Quand un comportement vient d'une bizarrerie de la spécification, citez la spécification.
Les numéros de ligne bougent, les citations non.

## Signaler une incohérence de la spécification

Si vous en trouvez une :

1. Ajoutez un test qui la verrouille, nommé d'après elle, avec un commentaire expliquant ce
   qu'un participant en conclurait de travers.
2. Signalez-la à GIMAC (`info@gimac-afr.org`) — c'est leur spécification.

Deux exemples déjà traités dans `tests/test_intents.py` : `mobile_reload` absent de
l'énumération `Payment.intent`, et `wallet_to_account` dupliqué.

## Signaler une faille

Pas d'issue publique. Voir `SECURITY.md`.

## Commits

Un changement par commit, un message qui dit *pourquoi*. « Corrige un bug » n'aide personne ;
« Un 500 ne doit pas être rapporté comme un rejet » dit tout.

## Publication

Les publications se font depuis `main` via GitHub Actions, avec publication de confiance
PyPI (OIDC) — aucun jeton d'API n'est stocké nulle part. Une publication est une porte à sens
unique : une version publiée sur PyPI se *yank*, elle ne se remplace pas. Étiquetez, laissez
la CI construire, vérifiez l'artefact, puis publiez.
