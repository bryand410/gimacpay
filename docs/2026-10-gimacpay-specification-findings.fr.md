# Six choses que la spécification GIMACPay ne vous dit pas

*Ce que j'ai trouvé en implémentant l'API de paiement interbancaire de la CEMAC — et
ce qu'un participant ferait de travers sans le savoir.*

> **English version:**
> [2026-10-gimacpay-specification-findings.md](2026-10-gimacpay-specification-findings.md)

---

GIMACPAY est le réseau de paiement interbancaire d'Afrique centrale. Il est exploité
par le GIMAC (*Groupement Interbancaire Monétique de l'Afrique Centrale*) et relie
**59 banques commerciales, six trésors publics** et les portefeuilles de monnaie
électronique des six États membres de la CEMAC : Cameroun, Tchad, République
centrafricaine, Guinée équatoriale, Gabon et Congo.

En juillet 2026, la BEAC y a lancé son **QR code commun**, à Douala. Le même mois, elle
a raccordé la CEMAC à **PAPSS** pour le règlement transfrontalier continental. SYSTAC 2,
la plateforme centralisée de compensation de détail construite avec ProgressSoft, est
entrée en service en août avec 59 banques et six trésors publics — et elle embarque un
module temps réel documenté comme *pas encore activé*.

Les rails sont donc neufs, régionaux, et en cours d'extension.

J'ai cherché une bibliothèque cliente pour écrire contre eux. Il n'y en avait pas. Le
seul artefact public que j'aie trouvé était un fichier OpenAPI, `gimac-api-1.10.yaml`,
publié dans un dépôt contenant deux fichiers et un README de deux lignes.

J'ai lu ses 2 423 lignes, puis j'ai écrit un client Python. Cet article est ce que j'en
ai appris : les endroits où la spécification se trompe, et la règle unique que la
plupart des implémentations rateront parce qu'elle se lit en diagonale.

Si vous intégrez GIMACPAY, cela devrait vous économiser un ou deux tickets de support.

---

## 1. La règle qui compte le plus, et c'est facile à manquer

Voici comment la spécification décrit elle-même la réponse `200` de `/payment/send` :

> **ACCEPTED or PENDING payment**

Un `200` n'est pas un succès. C'est « nous l'avons reçu, et cela peut encore changer ».

Et voici la description de tous les codes de réponse qu'elle ne définit pas :

> For all other responses codes, participants should keep the payment in PENDING state
> and perform a payment inquiry to GET the state. **Participants should not guess the
> state if it's not given by GIMACPay.**

Relisez-le, parce que c'est inhabituel et c'est délibéré. Un `500`. Un `502`. Un `503`
venu d'un répartiteur de charge. Un `418` d'un mandataire que personne n'attendait sur
le chemin. **Aucun de ces codes ne signifie que le paiement a échoué.**

Ils signifient que vous ne savez pas.

C'est toute la différence entre une intégration de paiement qui fonctionne et une qui
produit des doubles débits. Si votre code traduit « statut HTTP inattendu » par
« transaction échouée », alors quand le réseau lâche entre votre requête et la réponse,
vous marquerez comme échoué un paiement en réalité accepté — et votre réconciliation
sera fausse dans la direction la plus coûteuse.

La bonne forme est un modèle à trois états, pas à deux :

| Réponse | Signification | Que faire |
|---|---|---|
| `200` avec `state: ACCEPTED` | Accepté | Terminé |
| `200` avec `state: PENDING` | En vol | Interroger `/payment/inquiry` |
| `400` | Rejeté, motif dans `error_description` | Terminé — les fonds n'ont pas bougé |
| `401` | Jeton absent ou expiré | Rafraîchir, réessayer une fois |
| `403` | **IP source non autorisée** | Arrêter. Réessayer ne servira à rien |
| tout le reste | **Inconnu** | Interroger `/payment/inquiry` jusqu'à un état terminal |

Notez le `403`. La spécification en donne la cause : *« Check if the source IP address is
authorized on GIMACPay's server. »* C'est un problème de liste d'autorisation de votre
côté, pas un problème d'identifiants. Rafraîchir votre jeton en boucle n'y changera
jamais rien.

Et notez les états. `Payment.state` en compte six : `ACCEPTED`, `REJECTED`, `PENDING`,
`REVERSED`, `EXPIRED`, `CANCELLED`. **Un seul n'est pas terminal.** C'est là toute la
conception de l'interrogation, et cela vaut la peine d'être encodé explicitement plutôt
que comparé à la chaîne littérale `"PENDING"` à six endroits du code.

---

## 2. `mobile_reload` manque dans l'énumération des réponses

`/payment/send` accepte un `oneOf` de **24 schémas de requête**, sélectionnés par un
seul champ : `intent`. C'est le discriminant, et se tromper envoie le mauvais type de
paiement.

`MobileReloadRequest` est l'un des 24. Il existe un `MobileReloadRequestExample` —
l'achat de crédit téléphonique :

```yaml
MobileReloadRequestExample:
  value:
    intent: mobile_reload
    issuertrxref: "5575959595055005"
    sendermobile: "677457857"
    receivermobile: "677678789"
    tomember: "12101"
    amount: 700
    currency: "950"
```

L'intent existe donc, il est documenté, et il a un exemple travaillé.

Voici maintenant `Payment.intent`, l'énumération de l'objet en **réponse** :

```
mobile_transfer, merchant_purchase, inc_wal_remit, cardless_withdrawal,
bill_inquiry, bill_payment, cash_out, purchase_voucher, pp_reload,
inc_acc_remit, inc_card_remit, inc_voucher_remit, outg_acc_remit,
outg_card_remit, outg_wal_remit, outg_voucher_remit, cash_deposit,
cash_in, wallet_to_account, account_to_wallet, account_transfer,
wallet_to_account, request_to_pay, account_inquiry
```

Vingt-quatre entrées. `mobile_reload` n'y figure pas.

La conséquence pratique : un participant envoie un achat de crédit, reçoit un `200`,
relit le champ `intent` — et tombe sur une valeur que sa propre validation, écrite
d'après la spécification, rejette comme impossible. Selon la façon dont il l'a écrite,
il abandonne un paiement réussi, ou il plante dessus.

**Correction :** ajouter `mobile_reload` à `Payment.intent`.

---

## 3. `wallet_to_account` est listé deux fois

Reprenez l'énumération ci-dessus. Comptez les entrées : vingt-quatre. Comptez les
valeurs distinctes : vingt-trois. `wallet_to_account` apparaît en position 19, puis de
nouveau en position 22.

C'est sans conséquence en pratique — un membre dupliqué n'est qu'un doublon. Mais c'est
le genre de détail qui fait se demander à un lecteur attentif si l'énumération a été
générée à partir d'une liste modifiée à la main, et si autre chose s'est perdu dans la
même modification. Vu le § 2, le soupçon n'est pas infondé.

**Correction :** en supprimer un.

---

## 4. `issuertrxref` est typé entier, et toujours envoyé comme chaîne

Le schéma `Payment` déclare :

```yaml
issuertrxref:
  type: integer
  format: integer
  example: 1234578999
  maxLength: 20
```

Trois choses ne vont pas dans ces quatre lignes. Le champ est déclaré `integer` mais
porte un `maxLength`, qui est une contrainte de chaîne. L'exemple n'est pas entre
guillemets. Et **tous les exemples travaillés de la spécification envoient une chaîne
entre guillemets** :

```yaml
issuertrxref: "133759595959595"     # WalletToWalletRequestExample
issuertrxref: "5575959595055005"    # CashInToWalletRequestExample
issuertrxref: "4575759558958595050" # PrepaidCardReloadRequestExample
```

Ces valeurs font 15, 16 et 19 chiffres. Un entier de 19 chiffres dépasse la plage
exacte d'un flottant 64 bits et celle d'un `Number` JavaScript — ce qui signifie qu'un
participant implémentant le schéma à la lettre, en JavaScript ou dans tout langage
adossé à un double, **corrompra silencieusement le seul champ dont il a besoin pour
réconcilier le paiement ensuite**.

`issuertrxref` est **votre propre référence**. C'est la seule prise que vous avez sur le
paiement après l'avoir envoyé. La corrompre est irréparable.

**Correction :** déclarer `type: string` et mettre l'exemple entre guillemets.

---

## 5. `customerdata` est typé objet, et toujours envoyé comme tableau

Le schéma `Payment` déclare :

```yaml
sendercustomerdata:
  $ref: '#/components/schemas/CustomerData'
receivercustomerdata:
  $ref: '#/components/schemas/CustomerData'
```

Un objet. Mais les exemples travaillés envoient un **tableau à un élément** :

```yaml
receivercustomerdata:
  - firstname: "Lara"
    secondname: "James"
sendercustomerdata:
  - firstname: "Infinte"
    secondname: "Game machine"
    idnumber: "10945888"
    idtype: "National ID"
```

Et `Payment.dstaccounts` / `Payment.srcaccounts` portent des contraintes qui sonnent
bizarre pour un tableau :

```yaml
dstaccounts:
  type: array
  maxLength: 1
  minLength: 1
```

`maxLength` et `minLength` sur un tableau, là où OpenAPI définit `maxItems` et
`minItems`. L'intention est claire — exactement un élément — mais un validateur strict
ne l'appliquera pas, et un *générateur* strict peut rejeter le document.

**Correction :** choisir une seule forme pour `customerdata` et l'employer partout ;
remplacer `maxLength`/`minLength` par `maxItems`/`minItems` sur les tableaux.

---

## 6. `/payment/update` documente un `200` comme un objet d'erreur

La requête est typée `UpdateRequest`, ce qui est cohérent. La réponse ne l'est pas :

```yaml
'200':
  description: ACCEPTED or PENDING payment
  content:
    application/json:
      schema:
        $ref: '#/components/schemas/Http400Response'
```

Un `200` dont le corps est documenté comme une paire d'erreur, avec une description qui
annonce « ACCEPTED or PENDING payment ». Une de ces trois affirmations est fausse, et le
document ne permet pas de savoir laquelle.

Je soupçonne un copier-coller du bloc `/payment/send` pendant un renommage, parce que
`/payment/update` porte aussi `summary: Send a new payment` — identique à
`/payment/send`, et décrivant une chose que l'opération ne fait pas.

**Correction :** typer le `200` en `Payment`, et donner à l'opération son propre
résumé.

---

## Deux choses plus petites

**L'énumération des devises n'a qu'un membre.** `currency` est contraint à la chaîne
`"950"` — le code ISO 4217 **numérique** du franc CFA d'Afrique centrale. Pas `"XAF"`,
pas `"FCFA"`, pas un symbole. C'est correct, et c'est le genre de détail qui coûte un
après-midi quand on suppose le code alphabétique.

**Les numéros de téléphone sont formatés de deux façons.** Les exemples de remittance
envoient `"+336575950505"`, avec un `+` initial. L'exemple `mobile_reload` envoie
`"677457857"` et l'exemple `cash_in` envoie `"2367890899"` — des numéros locaux nus,
sans indicatif. Les trois sont donc valides, et un client qui impose une seule
convention rejettera des exemples venus de la spécification elle-même. Quoi que vous
construisiez, normalisez en retirant la mise en forme et **n'inventez jamais
d'indicatif** : préfixer un numéro local par un indicatif deviné envoie de l'argent à
un inconnu.

---

## Ce que j'ai construit, et pourquoi c'est taillé comme ça

J'ai écrit un client Python à partir de la spécification — `gimacpay`, sur
**github.com/bryand410/gimacpay**. Deux décisions de conception viennent directement des
sections ci-dessus.

**Zéro dépendance d'exécution.** Ce n'est pas du minimalisme pour le plaisir. Un client
de paiement qui tire un arbre de dépendances importe la surface d'attaque de chaque
paquet qui s'y trouve — et c'est précisément le vecteur contre lequel l'équipe qui
l'intègre passe son temps à se défendre. `event-stream`, `ua-parser-js`, `xz-utils` :
dans chaque cas le code vulnérable n'était pas dans le projet que quiconque avait
choisi, il était dans ce que ce projet avait choisi de tirer. La bibliothèque utilise
`urllib` et `json`, rien d'autre, ce qui est vérifiable :

```bash
PYTHONPATH=src python -S -c "import gimacpay; print(gimacpay.__version__)"
```

`-S` retire `site-packages` du chemin d'import, donc cette commande ne peut réussir que
par `PYTHONPATH`. Si quoi que ce soit de tiers était importé, elle échouerait.

**Un rejet et un état inconnu sont deux classes d'exception sœurs.** `PaymentRejected`
est un `400` : définitif, les fonds n'ont pas bougé. `PaymentStateUnknown` est tout le
reste : indéfini, il faut interroger. Elles partagent une base commune et aucune
n'hérite de l'autre, de sorte que `except PaymentRejected:` ne peut pas avaler
accidentellement une issue inconnue. Un test vérifie la relation entre les classes,
précisément pour que personne ne « range » cela plus tard.

Et `send_and_resolve()` envoie un paiement puis l'interroge jusqu'à un état terminal. Si
l'envoi renvoie un statut inconnu, la méthode ne lève pas — elle interroge, parce que
c'est ce que la spécification demande. Si elle expire, le message d'exception dit
explicitement que le paiement **n'a pas** échoué, il est non résolu.

Le dépôt est sur **github.com/bryand410/gimacpay** : **171 tests**, zéro dépendance, CI
verte de Python 3.9 à 3.13. Ce n'est pas encore sur PyPI — voir la note ci-dessous sur
la licence de la spécification.

---

## Une note sur la licence de la spécification

`gimac-api-1.10.yaml` porte `license: {name: Private}`. Le fichier est publié
publiquement, mais le champ de licence dit « privé », donc je ne l'ai pas redistribué.
Le dépôt de la bibliothèque le contient comme référence de développement uniquement,
exclu de tout artefact publié, et trois tests le lisent pour vérifier que les tables du
client correspondent toujours à la spécification. Une table périmée doit être un test
rouge, pas un paiement rejeté en production.

J'ai écrit au GIMAC pour demander si une bibliothèque cliente publique est bienvenue, et
quelle licence ils préféreraient. Si la réponse est oui, la bibliothèque est prête.

---

## Le point

Aucun des six points ci-dessus n'est spectaculaire. Ce n'est pas là l'essentiel.

L'essentiel, c'est qu'une API servant **59 banques et six trésors publics** dans six
pays, reliée à un système de règlement continental et portant le QR code d'une banque
centrale, dispose d'une spécification publique dans laquelle une opération documentée
manque à l'énumération qui décrit ses propres réponses.

Ce n'est pas une critique du GIMAC. C'est à quoi ressemble toute spécification vue de
l'intérieur, et c'est pourquoi le travail ennuyeux — lire les 2 423 lignes, confronter
l'énumération aux schémas de requête, écrire la première semaine du participant — est le
travail qui compte.

Si vous construisez sur GIMACPAY et que l'un de ces points vous a coûté un après-midi,
l'article aura fait son travail.

---

*Ulrich Bryand Tamouffe Teyo — Douala, Cameroun. Ingénierie sécurité, systèmes de
paiement, et les parties ingrates de l'infrastructure en Afrique francophone.*
