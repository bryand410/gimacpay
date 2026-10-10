# gimacpay

[![CI](https://github.com/bryand410/gimacpay/actions/workflows/ci.yml/badge.svg)](https://github.com/bryand410/gimacpay/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![Zero dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](#zero-dependencies)
[![Licence](https://img.shields.io/badge/licence-Apache--2.0-blue)](LICENSE)

**Client Python pour GIMACPAY, le réseau de paiement interbancaire de la CEMAC.**

GIMACPAY est opéré par GIMAC (Groupement Interbancaire Monétique de l'Afrique Centrale) et
relie **59 banques commerciales, six trésoreries nationales** et les portefeuilles mobile money
des **six États de la CEMAC** : Cameroun, Tchad, République centrafricaine, Guinée équatoriale,
Gabon et Congo.

Depuis juillet 2026 il porte aussi le **QR code communautaire** de la BEAC, et depuis juillet
2026 la BEAC l'a connecté à **PAPSS** pour le règlement transfrontalier continental.

Il n'existait aucune bibliothèque cliente publique pour cette API. Celle-ci implémente la
spécification publiée *GIMACPay Swagger for payments issuers* version 1.8.

---

## Installation

```bash
pip install gimacpay
```

Python 3.9 ou plus. **Aucune dépendance.**

---

## Démarrage

```python
from gimacpay import GimacPayClient, wallet_to_wallet

client = GimacPayClient(
    base_url="https://<votre-endpoint>/stdendpointfacade/v1/external",
    client_id="...",
    client_secret="...",
    username="...",
    password="...",
    default_dial_code="237",  # Cameroun
)

payment = client.send_and_resolve(
    wallet_to_wallet(
        amount=500,  # en unités mineures : 500 = 5,00 XAF
        walletsource="237699947943",
        walletdestination="2356789009",
        tomember="22001",
        issuertrxref="ORD-2026-0001",
    )
)

if payment.is_accepted:
    print("payé")
else:
    print(payment.state, payment.rejectmessage)
```

---

## La règle que cette bibliothèque est construite autour

La spécification est catégorique, dans la description de `/payment/send` :

> For all other responses codes, participants should keep the payment in PENDING state and
> perform a payment inquiry to GET the state. **Participants should not guess the state if
> it's not given by GIMACPay.**

Un code de réponse non documenté — un 500, un 503, une passerelle qui répond n'importe quoi —
ne veut pas dire « échec ». Il veut dire **« on ne sait pas »**. Une bibliothèque qui transforme
ça en échec dit à son opérateur que l'argent n'a pas bougé alors qu'il a peut-être bougé.
C'est comme ça qu'on produit des doubles débits.

Donc :

| Réponse | Exception | Signification |
|---|---|---|
| `200` | — | Accepté **ou** en attente. Lire `payment.state`. |
| `400` | `PaymentRejected` | Rejeté. La raison est dans `error_description`. |
| `401` | `GimacPayAuthError` | Jeton absent ou expiré. Rafraîchi une fois, puis signalé. |
| `403` | `GimacPayForbiddenError` | **L'IP source n'est pas autorisée.** Rafraîchir le jeton n'y changera rien. |
| **tout le reste** | **`PaymentStateUnknown`** | **On ne sait pas.** Interroger, ne pas supposer. |

`PaymentStateUnknown` et `PaymentRejected` sont **frères, jamais liés** — un `except
PaymentRejected` ne peut pas attraper un état inconnu par accident. C'est testé.

### `send_and_resolve`

Pour tout ce qui déplace de l'argent, utilisez `send_and_resolve` plutôt que `send_payment`.
Il envoie, puis suit le paiement par interrogation jusqu'à un état terminal — et il couvre
le cas que la spécification décrit : une réponse qui ne dit rien.

```python
payment = client.send_and_resolve(payload, timeout=120, interval=3)
```

Si l'envoi renvoie un état inconnu, il ne lève pas : il interroge, parce que c'est
littéralement ce que la spécification demande. Si le délai expire, il lève `TimeoutError` —
et le message dit explicitement que le paiement **n'a pas échoué**, il est non résolu.

---

## Les 24 `intent`

`/payment/send` accepte un `oneOf` de 24 schémas, sélectionnés par un seul champ : `intent`.
C'est le discriminateur. Se tromper dessus, c'est envoyer le mauvais type de paiement.

Les constructeurs règlent `intent` eux-mêmes :

```python
from gimacpay import (
    wallet_to_wallet,
    merchant_purchase,
    request_to_pay,
    cash_in,
    cash_deposit,
    cash_out,
    bill_inquiry,
    bill_payment,
    mobile_reload,
    account_inquiry,
    build,
)
```

| Constructeur | `intent` | Usage |
|---|---|---|
| `wallet_to_wallet` | `mobile_transfer` | Portefeuille → portefeuille |
| `merchant_purchase` | `merchant_purchase` | Payer un marchand |
| `request_to_pay` | `request_to_pay` | Demander un paiement |
| `bill_inquiry` | `bill_inquiry` | Consulter une facture (sans montant) |
| `bill_payment` | `bill_payment` | Payer une ou plusieurs factures |
| `cash_in` | `cash_in` | Espèces → portefeuille, au guichet |
| `cash_deposit` | `cash_deposit` | Dépôt d'espèces |
| `cash_out` | `cash_out` | Retrait d'espèces |
| `mobile_reload` | `mobile_reload` | Achat de crédit téléphonique |
| `account_inquiry` | `account_inquiry` | Résoudre un portefeuille ou un compte |
| `build` | *le vôtre* | Les 8 transferts et tout ce qui viendra |

Pour lister ce que la spécification définit, et les champs requis de chacun :

```bash
gimacpay intents
gimacpay intents mobile_transfer
```

---

## Deux pièges de terrain, traités

**La devise.** L'énumération `currency` de la spécification n'a qu'un membre : la chaîne
`"950"` — le code ISO 4217 **numérique** du franc CFA d'Afrique centrale (XAF). Pas `"XAF"`,
pas `"FCFA"`. La constante `CURRENCY_XAF` est là pour ça.

**Les numéros de téléphone.** La spécification est incohérente : les exemples de transfert
envoient `"+336575950505"` avec un `+`, tandis que `MobileReloadRequestExample` envoie
`"677457857"` et `CashInToWalletRequestExample` `"2367890899"` — des numéros locaux, sans
indicatif. Les trois sont donc valides.

`normalise_phone` retire la mise en forme (`+`, espaces, tirets, préfixe `00`) et **n'invente
jamais d'indicatif**. Pour obtenir du E.164, demandez-le explicitement :

```python
from gimacpay import normalise_phone

normalise_phone("+237 699 947 943")  # '237699947943'
normalise_phone("677457857")  # '677457857' — inchangé
normalise_phone("677457857", default_dial_code="237")  # '237677457857'
```

---

## Ligne de commande

```bash
gimacpay intents                     # les 24 intent et leurs champs requis
gimacpay intents mobile_transfer     # le détail d'un intent
gimacpay doctor                      # vérifier la configuration et s'authentifier
gimacpay build --intent mobile_transfer --amount 500 \
    --walletsource 2356789009 --walletdestination 237699947943 \
    --tomember 22001 --ref ORD-1     # construire et afficher, SANS envoyer
gimacpay send ... --confirm          # envoyer (--confirm obligatoire)
```

`send` refuse d'agir sans `--confirm`. Envoyer de l'argent depuis un shell doit demander
un geste explicite.

Configuration par variables d'environnement : `GIMACPAY_BASE_URL`, `GIMACPAY_CLIENT_ID`,
`GIMACPAY_CLIENT_SECRET`, `GIMACPAY_USERNAME`, `GIMACPAY_PASSWORD`, `GIMACPAY_DIAL_CODE`.

---

## Zéro dépendance

Ce n'est pas un choix esthétique. C'est une propriété de sécurité.

Un client de paiement qui tire un arbre de dépendances importe la surface d'attaque de
chacune. `event-stream`, `ua-parser-js`, `xz-utils` : les attaques de chaîne
d'approvisionnement sont exactement le vecteur contre lequel l'équipe qui intègre cette
bibliothèque passera son temps à se défendre. Une bibliothèque qui déplace de l'argent dans
six pays ne devrait pas avoir de dépendances transitives.

Tout est en `urllib` et `json` de la bibliothèque standard. Vérifiable :

```bash
PYTHONPATH=src python -S -c "import gimacpay; print(gimacpay.__version__)"
```

`-S` retire `site-packages` du chemin d'import, donc cet import ne peut réussir que par
`PYTHONPATH=src`. Si la bibliothèque tirait quoi que ce soit de tiers, ça échouerait ici.

Voir [SECURITY.md](SECURITY.md).

---

## Ce que la spécification ne dit pas

Deux incohérences trouvées en écrivant cette bibliothèque, verrouillées par des tests
plutôt que laissées en commentaires :

1. **`mobile_reload` manque à l'énumération `Payment.intent`.** Le schéma
   `MobileReloadRequest` figure bien dans le `oneOf` de `/payment/send`, et
   `MobileReloadRequestExample` est un exemple travaillé — mais l'énumération de réponse
   l'omet. Un participant qui enverrait un achat de crédit puis lirait l'énumération
   conclurait que c'est impossible.
2. **`wallet_to_account` apparaît deux fois** dans la même énumération.

Si GIMAC corrige l'un ou l'autre, `tests/test_intents.py` échoue et le dit.

Trois autres points relevés, sans être des bugs :

- `Payment.issuertrxref` est typé `integer`, mais **tous** les exemples envoient une chaîne.
  La bibliothèque convertit en `str` à la frontière.
- `receivercustomerdata` / `sendercustomerdata` sont typés `object`, mais les exemples
  envoient un tableau d'un élément. Les deux formes sont acceptées.
- La réponse 200 de `/payment/update` est typée `Http400Response` (une paire
  `error` / `error_description`), ce qui ressemble à une erreur de documentation.
  La méthode renvoie donc le corps brut plutôt que de deviner.

---

## État

- 24 `intent`, 3 points d'entrée, 0 dépendance
- Tests contre un serveur HTTP local qui parle le protocole réel (pas de mock du transport)
- `ruff` propre

## Licence

Le code de cette bibliothèque est sous **Apache-2.0** — voir [LICENSE](LICENSE).

La spécification GIMACPay (`docs/reference/gimac-api-1.10.yaml`) est la propriété de GIMAC.
Son champ `license` indique `Private`. Elle est présente dans ce dépôt **comme référence de
développement uniquement** et **exclue de tout artefact publié** (voir l'exclusion `sdist`
dans `pyproject.toml`). Elle n'est pas redistribuée sur PyPI.

---

## Projet non affilié

Cette bibliothèque n'est ni éditée, ni approuvée, ni soutenue par GIMAC ou GIMACPAY. C'est
un client indépendant écrit à partir de la spécification publique. Pour toute question sur
le réseau lui-même : `info@gimac-afr.org`.
