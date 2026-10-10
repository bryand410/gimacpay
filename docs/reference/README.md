# Référence — la spécification GIMACPay

## Provenance

`gimac-api-1.10.yaml` est la spécification OpenAPI de GIMACPAY, le réseau de paiement
interbancaire de la CEMAC.

- **Titre déclaré :** `GIMACPay Swagger for payments issuers 1.8`
- **`version` dans le fichier :** `1.8`
- **Nom de fichier :** `gimac-api-1.10.yaml`
- **OpenAPI :** 3.0.3
- **Téléchargée depuis :** `github.com/ndziePatrickJoel/gimacpay` le 10 octobre 2026
- **Taille :** 2 423 lignes

## Licence — à lire avant de réutiliser ce fichier

Le champ `license` de la spécification indique :

```yaml
license:
  name: Private
  url: https://gimac-afr.com/#
```

**La spécification appartient à GIMAC.** Elle est présente dans ce dépôt **uniquement comme
référence de développement**, pour que les tests puissent vérifier que les tables du SDK
correspondent à la spécification qu'il implémente.

Elle est **exclue de tout artefact publié** — voir l'exclusion `sdist` dans `pyproject.toml`.
Elle n'est pas distribuée sur PyPI et ne doit pas l'être.

Ne la déplacez pas dans `src/`, ne l'embarquez pas dans le paquet, ne la republiez pas
ailleurs. Si vous voulez la redistribuer, demandez à GIMAC : `info@gimac-afr.org`.

## Pourquoi elle est ici plutôt que dans un README

Trois tests de `tests/test_intents.py` lisent ce fichier :

| Test | Ce qu'il vérifie |
|---|---|
| `test_the_response_enum_is_a_subset_of_the_sdk` | Le SDK connaît tout ce que GIMACPay peut rapporter |
| `test_the_only_intent_missing_from_the_response_enum_is_mobile_reload` | Verrouille l'incohérence connue |
| `test_the_declared_api_version_is_still_what_we_built_against` | Une montée de version doit faire échouer la CI |

Une table d'`intent` périmée doit être un test rouge, pas un paiement rejeté en production.

## Ce que la spécification contient

- 3 points d'entrée : `/payment/inquiry`, `/payment/send`, `/payment/update`
- 24 `intent` différents, discriminés par le champ `intent` du corps de requête
- Un schéma d'authentification : OAuth 2.0, flux `password`, `.../oauth/token`
- Les schémas `Payment`, `Bill`, `AccountInfo`, `CustomerData`, `UpdateRequest`,
  `PaymentInquiryRequest`, et les réponses d'erreur `Http400Response`,
  `Http401Response`, `Http403Response`

## Le serveur de référence

```yaml
servers:
  - url: http://localhost:8005/stdendpointfacade/v1/external
```

`localhost` parce que la spécification circule à l'intérieur du réseau de GIMAC. **Il n'y a
pas de sandbox publique.** En pratique, vous remplacez cette URL par l'endpoint que GIMAC
attribue à votre institution.
