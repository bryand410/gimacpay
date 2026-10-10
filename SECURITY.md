# Sécurité

## Signaler une vulnérabilité

N'ouvrez **pas** d'issue publique pour une faille de sécurité.

Écrivez à l'adresse indiquée dans `pyproject.toml` (`authors`), ou utilisez l'onglet
**Security → Report a vulnerability** du dépôt GitHub.

Merci d'inclure : la version, un exemple minimal de reproduction, et l'impact que vous
imaginez. Vous recevrez une réponse sous 72 heures. Si vous n'en recevez pas, relancez —
l'absence de réponse est un bug, pas un refus.

---

## Zéro dépendance — la décision d'ingénierie principale

`gimacpay` n'a **aucune dépendance d'exécution**. Tout est en `urllib` et `json` de la
bibliothèque standard.

Ce n'est pas de la minimalisme pour le plaisir. Un client de paiement qui tire un arbre de
dépendances importe la surface d'attaque de chaque paquet de cet arbre, et cette surface est
précisément le vecteur contre lequel l'équipe qui l'intègre passera son temps à se défendre.

Trois attaques de chaîne d'approvisionnement qui ont touché des projets largement déployés :

| Incident | Mécanisme |
|---|---|
| `event-stream` (2018) | Paquet npm repris par un tiers, charge utile injectée dans une dépendance transitive |
| `ua-parser-js` (2021) | Compte mainteneur compromis, mineur de cryptomonnaie dans les versions publiées |
| `xz-utils` (2024) | Mainteneur légitime socialement ingénié pendant deux ans, porte dérobée dans les versions de distribution |

Dans les trois cas, le code vulnérable n'était **pas** dans le projet que les gens avaient
choisi d'utiliser. Il était dans quelque chose que ce projet avait choisi de tirer.

Vérifier la propriété :

```bash
PYTHONPATH=src python -S -c "import gimacpay; print(gimacpay.__version__)"
```

`-S` retire `site-packages` du chemin d'import, donc cet import ne peut réussir que par
`PYTHONPATH=src`. Si la bibliothèque importait quoi que ce soit de tiers, la commande
échouerait. C'est la preuve.

L'autre vérification, sur le paquet installé :

```bash
python -c "import importlib.metadata as md; print(md.requires('gimacpay'))"
```

Doit n'afficher que les deux extras de développement, ou `None`.

---

## Ce que cette bibliothèque ne fait pas

- **Elle ne journalise aucun secret.** Ni jeton d'accès, ni `client_secret`, ni mot de passe,
  ni code PIN. Les exceptions transportent le corps de la réponse et l'URL, jamais les
  identifiants.
- **Elle ne stocke rien sur disque.** Les jetons vivent en mémoire, dans l'instance du client.
- **Elle n'écrit rien.** Aucun appel de fichier, aucune écriture de configuration.
- **Elle ne valide pas la signature des réponses.** Il n'y en a pas dans la spécification.
  La confidentialité repose sur TLS ; c'est pour ça que `base_url` doit être en `https://`
  en production. Le serveur de référence de la spécification est en `http://` parce qu'il
  tourne à l'intérieur du réseau de GIMAC.
- **Elle n'impose pas TLS.** Vous pouvez passer une `base_url` en `http://` et la
  bibliothèque obéira. C'est délibéré — mais si vous le faites en production, le mot de
  passe du participant et le jeton d'accès circulent en clair.

---

## Le modèle de menace que la bibliothèque traite réellement

Ce n'est pas un client HTTP générique. Le risque principal ici n'est pas l'exécution de code
arbitraire : c'est **de dire à un opérateur qu'un paiement a échoué alors qu'il a peut-être
réussi**.

La spécification l'énonce elle-même :

> For all other responses codes, participants should keep the payment in PENDING state and
> perform a payment inquiry to GET the state. **Participants should not guess the state if
> it's not given by GIMACPay.**

Donc :

1. **Un code non documenté produit `PaymentStateUnknown`, jamais `PaymentRejected`.** Les
   deux classes sont sœurs ; un `except PaymentRejected` ne peut pas les confondre. C'est
   testé explicitement (`tests/test_errors.py::TestErrorHierarchy`).
2. **Une erreur de transport ne prétend pas que le paiement a échoué.** Une connexion
   coupée ne dit rien sur le sort de l'argent.
3. **Une réponse 200 ne veut pas dire « accepté ».** La spécification dit « ACCEPTED or
   PENDING payment ». `Payment.is_terminal` répond à la seule question qui compte.
4. **`send_and_resolve` ne devine jamais.** Si l'envoi ne dit rien, il interroge — parce que
   c'est ce que la spécification demande.

---

## Ce qu'il faut faire de `PaymentStateUnknown`

```python
from gimacpay import PaymentStateUnknown

try:
    payment = client.send_payment(payload)
except PaymentStateUnknown as exc:
    # exc.issuertrxref : la référence à interroger
    # exc.status       : le code reçu
    # exc.body         : le corps brut, à journaliser
    payment = client.await_state(exc.issuertrxref, timeout=300)
```

**Ne marquez pas le paiement comme échoué.** Ne le renvoyez pas. Interrogez. C'est la seule
réaction correcte, et c'est celle que la spécification prescrit.

---

## Limites connues

- **La bibliothèque ne valide pas la signature des webhooks entrants.** GIMACPay appelle vos
  endpoints pour notifier les changements d'état ; c'est votre serveur qui les reçoit, pas
  cette bibliothèque. La spécification ne documente pas de schéma de signature pour ces
  callbacks. **Traitez tout callback entrant comme non fiable** : vérifiez-le par un appel à
  `inquiry`, et rendez le traitement idempotent sur `issuertrxref`.
- **Pas de limitation de débit.** La bibliothèque ne fait pas de backoff automatique sur les
  réponses indéfinies, parce que réessayer un `POST /payment/send` sans idempotence côté
  serveur peut créer un doublon. `issuertrxref` est votre identifiant d'idempotence : gardez-le
  unique et stable.
- **Aucune sandbox publique.** Le bloc `servers` de la spécification pointe sur `localhost`.
  Cette bibliothèque a donc été développée contre un serveur local qui implémente le
  protocole documenté, et **jamais testée contre une instance réelle de GIMACPAY**. Les
  schémas viennent de la spécification ; leur comportement en production n'a pas été observé.

---

## Versions prises en charge

La version publiée la plus récente. Les correctifs de sécurité iront sur la branche `main`
et dans une publication de correctif.
