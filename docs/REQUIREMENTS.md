# Requirements & design notes

## Purpose

Onboard a customer onto a **private (committed-spend) pricing agreement**. Target
user: **Sales**, doing the onboarding themselves — authoring deal terms, producing
a signable agreement, and (after signature) handing a billing-ready configuration
to the billing team.

## Principles

- **Prototype, not a product.** Smallest thing that shows the workflow. Expand later.
- **Zero-to-low setup.** Python + `pip install` + one command; deployable to a free
  host. No database, no auth, no backend service.
- **Stateful workflow.** Each onboarding is a record with an explicit lifecycle,
  persisted, resumable, with a transition history (audit trail).
- **One public catalog.** Private customers get a discount *policy* resolved against
  the shared price book at billing time — we never fork the catalog per customer.

## Workflow

```
DRAFT  ──generate_agreement──▶  AGREEMENT_READY  ──send_for_signature──▶  PENDING_SIGNATURE  ──mark_signed──▶  SIGNED  ──▶  ACTIVE (billing)
  ▲                                    │
  └──────── update_agreement ──────────┘   (editing a generated agreement reverts it to DRAFT)
```

Guards:
- `generate_agreement` — the agreement must pass `validate_agreement` (required
  fields, %s in 0–100, ≥1 discount, commitment > 0, known/unique services).
- `send_for_signature` — a document must have been generated.
- `update_agreement` — only allowed in `DRAFT` / `AGREEMENT_READY`; locked once sent.

`apply(record, action, payload)` is the single mutation path — copies the record,
checks the transition, runs the guard, appends to `history`, returns the new record.
Pure; no I/O.

## Step 1 — Author agreement (fields)

| Field | Notes |
|---|---|
| Customer name | auto-filled `John Doe` / `Jane Doe`, editable — the signer |
| Company name | required |
| Start date | default today |
| Term length | 12 / 24 / 36 months → end date derived (start + term − 1 day) |
| Annual committed spend (USD) | > 0 |
| Discount model | `cross_service` / `per_service` / `both` |
| Cross-service % | 0–100, shown for cross-service or both |
| Per-service rows | `service` (from catalog) + `%`, ≥1 for per-service or both |

System-stamped, not shown: currency = USD, billing = monthly in arrears, account
number (assigned at billing setup), id, status, timestamps, history.

Explicitly cut for the prototype: contact email/address, sales owner field, CRM id,
auto-renew, payment terms, currency/billing-frequency choice, per-SKU exhibit
overrides, flat-rate (absolute) pricing, a live coverage helper.

## Deliverables in this iteration

Tracker · Step 1 form · generate agreement (+ PDF) · send for signature · mock
"mark signed" · history log · JSON persistence · state-machine tests.

## Next iteration — Billing setup (`SIGNED → ACTIVE`)

Capture the negotiated rates and provision the customer:
- resolve the agreement's discount policy against `catalog.py` (precedence:
  per-service > cross-service > list) into a per-SKU **rate preview**;
- the durable artifact is the compact **discount policy** (+ effective dates), not a
  materialized per-customer price list;
- assign the account number;
- export the billing config.

Later still: usage/volume tiers evaluated at rating time; real e-signature; multi-user.
