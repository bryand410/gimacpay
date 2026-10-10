# Journal des modifications

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Le versionnage suit [SemVer](https://semver.org/lang/fr/).

---

## [Non publié]

Rien pour l'instant.

---

## [0.1.0] — 2026-10-10

Première version. Implémente la spécification *GIMACPay Swagger for payments issuers*
version 1.8 (fichier `gimac-api-1.10.yaml`).

### Ajouté

- `GimacPayClient` : authentification OAuth 2.0 (flux password), cache du jeton avec marge
  de sécurité de 60 s, rafraîchissement automatique sur un 401 puis nouvel essai unique.
- Les trois points d'entrée de la spécification : `send_payment` (`/payment/send`),
  `inquiry` (`/payment/inquiry`), `update_payment` (`/payment/update`).
- `await_state` et `send_and_resolve` : suivent un paiement jusqu'à un état terminal en
  interrogeant GIMACPay, sans jamais deviner.
- Les 24 valeurs de `intent`, avec leurs champs requis dérivés des exemples travaillés de la
  spécification.
- Dix constructeurs de requêtes (`wallet_to_wallet`, `merchant_purchase`, `request_to_pay`,
  `bill_inquiry`, `bill_payment`, `cash_in`, `cash_deposit`, `cash_out`, `mobile_reload`,
  `account_inquiry`) plus `build` pour les huit transferts et tout ce qui viendra.
- Modèles typés : `Payment`, `PaymentState`, `AccountInfo`, `CustomerData`, `Bill`.
- `normalise_phone` et `validate_amount` : les deux pièges de terrain que la spécification
  laisse ouverts.
- Hiérarchie d'exceptions distinguant **rejet** (`PaymentRejected`) et **état inconnu**
  (`PaymentStateUnknown`) — des classes sœurs, jamais liées par héritage.
- Ligne de commande `gimacpay` : `intents`, `doctor`, `build`, `send` (avec `--confirm`
  obligatoire).
- **Zéro dépendance d'exécution.**

### Notes

- Aucune sandbox publique n'existe : le bloc `servers` de la spécification pointe sur
  `localhost`. La bibliothèque a été développée et testée contre un serveur local qui
  implémente le protocole documenté, **jamais contre une instance réelle de GIMACPAY**.
- Deux incohérences de la spécification sont documentées et verrouillées par des tests :
  `mobile_reload` est absent de l'énumération `Payment.intent` alors qu'il figure dans le
  `oneOf` de `/payment/send`, et `wallet_to_account` y est listé deux fois.

[Non publié]: https://github.com/bryand410/gimacpay/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/bryand410/gimacpay/releases/tag/v0.1.0
