# Six things the GIMACPay specification does not tell you

*What I found implementing the CEMAC interbank payment API — and what a participant
would get wrong without knowing it.*

> **Version française :**
> [2026-10-gimacpay-specification-findings.fr.md](2026-10-gimacpay-specification-findings.fr.md)

---

GIMACPAY is the interbank payment network for Central Africa. It is operated by GIMAC
(*Groupement Interbancaire Monétique de l'Afrique Centrale*) and it connects **59 commercial
banks, six national treasuries** and the mobile-money wallets of the six CEMAC member states:
Cameroun, Tchad, République centrafricaine, Guinée équatoriale, Gabon and Congo.

In July 2026 the BEAC launched its **common QR code** on top of it, at an event in Douala.
The same month, the BEAC connected CEMAC to **PAPSS** for continental cross-border settlement.
SYSTAC 2, the centralised retail clearing platform built with ProgressSoft, went live in
August with 59 banks and six treasuries participating — and it ships with a real-time module
that is documented as *not yet activated*.

So the rails are new, they are regional, and they are being extended right now.

I went looking for a client library so I could write against it. There wasn't one. The only
public artefact I could find was an OpenAPI file, `gimac-api-1.10.yaml`, published in a
repository containing two files and a two-line README.

I read all 2,423 lines of it, then wrote a Python client. This article is what I learned —
the parts of the specification that are wrong, and the one rule that most implementations
will get wrong because it is easy to skim past.

If you are integrating GIMACPAY, this should save you a support ticket or two.

---

## 1. The rule that matters most, and it is easy to miss

Here is the specification's own description of the `200` response from `/payment/send`:

> **ACCEPTED or PENDING payment**

A `200` is not a success. It is "we have it, and it might still change".

And here is the description of every response code the specification does not define:

> For all other responses codes, participants should keep the payment in PENDING state and
> perform a payment inquiry to GET the state. **Participants should not guess the state if
> it's not given by GIMACPay.**

Read that again, because it is unusual and it is deliberate. A `500`. A `502`. A `503` from a
load balancer. A `418` from a proxy that nobody expected to be in the path. **None of these
mean the payment failed.**

They mean you do not know.

This is the difference between a payments integration that works and one that produces double
debits. If your code maps "unexpected HTTP status" onto "transaction failed", then when the
network drops between your request and the answer, you will mark a payment as failed that was
actually accepted — and your reconciliation will be wrong in the most expensive direction.

The correct shape is a three-state model, not a two-state one:

| Response | Meaning | What to do |
|---|---|---|
| `200` with `state: ACCEPTED` | Accepted | Done |
| `200` with `state: PENDING` | In flight | Poll `/payment/inquiry` |
| `400` | Rejected, reason in `error_description` | Done — the money did not move |
| `401` | Token missing or expired | Refresh, retry once |
| `403` | **Source IP not authorised** | Stop. Retrying will not help |
| anything else | **Unknown** | Poll `/payment/inquiry` until terminal |

Note the `403`. The specification spells out the cause: *"Check if the source IP address is
authorized on GIMACPay's server."* That is an allow-list problem on your side, not a
credential problem. Refreshing your token in a loop will never fix it.

And note the states. `Payment.state` has six values: `ACCEPTED`, `REJECTED`, `PENDING`,
`REVERSED`, `EXPIRED`, `CANCELLED`. Exactly one of them is non-terminal. That is the whole
polling design, and it is worth encoding explicitly rather than comparing against
`"PENDING"` in a string literal in six places.

---

## 2. `mobile_reload` is missing from the response enum

`/payment/send` accepts a `oneOf` of **24 request schemas**, selected by a single field:
`intent`. It is the discriminator, and getting it wrong sends the wrong kind of payment.

`MobileReloadRequest` is one of the 24. There is a `MobileReloadRequestExample` — buying
airtime:

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

So the intent exists, is documented, and has a worked example.

Now here is `Payment.intent`, the enum on the **response** object:

```
mobile_transfer, merchant_purchase, inc_wal_remit, cardless_withdrawal,
bill_inquiry, bill_payment, cash_out, purchase_voucher, pp_reload,
inc_acc_remit, inc_card_remit, inc_voucher_remit, outg_acc_remit,
outg_card_remit, outg_wal_remit, outg_voucher_remit, cash_deposit,
cash_in, wallet_to_account, account_to_wallet, account_transfer,
wallet_to_account, request_to_pay, account_inquiry
```

Twenty-four entries. `mobile_reload` is not among them.

The practical consequence: a participant sends an airtime purchase, gets a `200`, reads the
`intent` field back, and finds a value that their own validation — written against the
specification — rejects as impossible. Depending on how they wrote it, they either drop a
successful payment or crash on it.

**Fix:** add `mobile_reload` to `Payment.intent`.

---

## 3. `wallet_to_account` is listed twice

Look at the enum above again. Count the entries: twenty-four. Count the distinct values:
twenty-three. `wallet_to_account` appears at position 19 and again at position 22.

It is harmless in practice — a duplicate enum member is just a duplicate. But it is the kind
of thing that makes a careful reader wonder whether the enum was generated from a list that
was edited by hand, and whether anything else was lost in the same edit. Given §2, that
suspicion is not unfounded.

**Fix:** delete one.

---

## 4. `issuertrxref` is typed as an integer, and always sent as a string

The `Payment` schema declares:

```yaml
issuertrxref:
  type: integer
  format: integer
  example: 1234578999
  maxLength: 20
```

Three things are wrong with those four lines. It is declared `integer` but carries a
`maxLength`, which is a string constraint. The example is unquoted. And **every worked
example in the specification sends a quoted string**:

```yaml
issuertrxref: "133759595959595"     # WalletToWalletRequestExample
issuertrxref: "5575959595055005"    # CashInToWalletRequestExample
issuertrxref: "4575759558958595050" # PrepaidCardReloadRequestExample
```

The values are 15, 16 and 19 digits long. A 19-digit integer exceeds the exact range of a
64-bit float and of a JavaScript `Number` — which means a participant implementing the
schema literally, in JavaScript or in anything backed by a double, will silently corrupt the
one field they need in order to reconcile the payment afterwards.

`issuertrxref` is **your own reference**. It is the only handle you have on the payment after
you send it. Corrupting it is unrecoverable.

**Fix:** declare it `type: string` and quote the example.

---

## 5. `customerdata` is typed as an object, and always sent as an array

The `Payment` schema declares:

```yaml
sendercustomerdata:
  $ref: '#/components/schemas/CustomerData'
receivercustomerdata:
  $ref: '#/components/schemas/CustomerData'
```

An object. But the worked examples send a **one-element array**:

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

And `Payment.dstaccounts` / `Payment.srcaccounts` carry constraints that read oddly for an
array:

```yaml
dstaccounts:
  type: array
  maxLength: 1
  minLength: 1
```

`maxLength` and `minLength` on an array, where OpenAPI defines `maxItems` and `minItems`.
It is clear what was meant — exactly one element — but a strict validator will not enforce
it, and a strict *generator* may reject the document.

**Fix:** pick one shape for `customerdata` and use it everywhere; change `maxLength`/`minLength`
to `maxItems`/`minItems` on the arrays.

---

## 6. `/payment/update` documents a `200` as an error object

The request is typed `UpdateRequest`, which is coherent. The response is not:

```yaml
'200':
  description: ACCEPTED or PENDING payment
  content:
    application/json:
      schema:
        $ref: '#/components/schemas/Http400Response'
```

A `200` whose body is documented as an error pair, with a description that says "ACCEPTED or
PENDING payment". One of those three statements is wrong and there is no way to tell which
from the document.

I suspect a copy-paste from the `/payment/send` block during a rename, because `/payment/update`
also carries `summary: Send a new payment` — identical to `/payment/send`, and describing
something the operation does not do.

**Fix:** type the `200` as `Payment`, and give the operation its own summary.

---

## Two smaller things

**The currency enum has one member.** `currency` is constrained to the string `"950"` — the
ISO 4217 *numeric* code for the Central African CFA franc. Not `"XAF"`, not `"FCFA"`, not a
symbol. It is correct, and it is the kind of thing that costs an afternoon if you assume the
alphabetic code.

**Phone numbers are formatted two different ways.** The remittance examples send
`"+336575950505"`, with a leading `+`. The `mobile_reload` example sends `"677457857"` and the
`cash_in` example sends `"2367890899"` — bare local numbers, no country code. All three are
therefore valid, and a client that enforces one convention will reject examples from the
specification itself. Whatever you build, normalise by stripping formatting and **never
invent a country code**: prepending a guessed dial code to a local number sends money to a
stranger.

---

## What I built, and why it is shaped this way

I wrote a Python client from the specification — `gimacpay`, at
**github.com/bryand410/gimacpay**. Two design decisions came directly out of the sections
above.

**Zero runtime dependencies.** Not minimalism for its own sake. A payments client that pulls
a dependency tree imports the attack surface of every package in it — and that is precisely
the vector the team integrating it spends its time defending against. `event-stream`,
`ua-parser-js`, `xz-utils`: in each case the vulnerable code was not in the project anyone
chose, it was in something that project chose to pull. The library uses `urllib` and `json`
and nothing else, which is verifiable:

```bash
PYTHONPATH=src python -S -c "import gimacpay; print(gimacpay.__version__)"
```

`-S` removes `site-packages` from the import path, so that command can only succeed through
`PYTHONPATH`. If anything third-party were imported, it would fail.

**A rejection and an unknown state are sibling exception classes.** `PaymentRejected` is a
`400`: definite, the money did not move. `PaymentStateUnknown` is everything else:
indefinite, poll. They share a common base and neither inherits from the other, so
`except PaymentRejected:` cannot accidentally swallow an unknown outcome. There is a test
that asserts the class relationship, precisely so that nobody "tidies" it later.

And `send_and_resolve()` sends a payment and then follows it by polling until the state is
terminal. If the send returns an unknown status, it does not raise — it inquires, because
that is what the specification asks for. If it times out, the exception message says
explicitly that the payment has **not** failed, it is unresolved.

The repository is at **github.com/bryand410/gimacpay**: 171 tests, zero dependencies, CI
green on Python 3.9 through 3.13. It is not on PyPI yet — see the note below on the
specification's licence.

---

## A note on the specification's licence

`gimac-api-1.10.yaml` carries `license: {name: Private}`. The file is published publicly, but
the licence field says private, so I have not redistributed it. The library's repository
includes it as a development reference only, excluded from every published artefact, and
three tests read it to check that the client's tables still match the specification. A stale
table should be a red test, not a rejected payment in production.

I have written to GIMAC to ask whether a public client library is welcome and what licence
they would prefer. If the answer is yes, the library is ready.

---

## The point

None of the six items above are dramatic. That is not the point.

The point is that an API serving **59 banks and six national treasuries** across six
countries, connected to a continental settlement system and carrying a central bank's QR
code, has a public specification in which a documented operation is missing from the enum
that describes its own responses.

That is not a criticism of GIMAC. It is what every specification looks like from the inside,
and it is why the boring work — reading all 2,423 lines, testing the enum against the request
schemas, writing the participant's first week down — is the work that matters.

If you are building on GIMACPAY and one of these cost you an afternoon, that is the article
having done its job.

---

*Ulrich Bryand Tamouffe Teyo — Douala, Cameroun. Security engineering, payment systems, and
the unglamorous parts of infrastructure in Francophone Africa.*
