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
DRAFT  ──generate_agreement──▶  AGREEMENT_READY  ──send_for_signature──▶  PENDING_SIGNATURE  ──mark_signed──▶  SIGNED  ──provision_billing──▶  ACTIVE
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

## Billing setup (`SIGNED → ACTIVE`) — built

`provision_billing` builds a **billing config** JSON stored on the record:

```jsonc
{
  "kind": "private-pricing-billing-config", "version": "1.0",
  "onboarding_ref", "account_number", "customer",
  "currency", "billing", "effective_from", "effective_to",
  "annual_committed_spend_usd", "price_book_date", "provisioned_at",
  "cross_service_discount_pct": 12 | null,     // flat baseline
  "discount_rules": [                          // service-specific only
    { "id": "ssd-claude-code", "type": "service_specific_discount",
      "description": "...", "discount_pct": 20,
      "match": { "all": [ { "field": "service_code", "op": "eq", "value": "CLAUDE_CODE" } ] } }
  ]
}
```

- **`match` grammar:** leaf `{field, op: eq|in, value}` over catalog fields
  (`service_code`, `id`, `unit`, `price_source`); combinators `{all:[...]}` / `{any:[...]}`.
- **Resolution (per SKU):** first matching `discount_rules` entry → else
  `cross_service_discount_pct` if set → else list price. Precedence is by rule type
  (service-specific beats cross-service); no explicit priority field.
- The per-SKU **rate table is derived on demand** from config + current catalog —
  never persisted. Exports: config JSON, rate table CSV.
- The account number is entered by Sales on the Step 1 form.

## Billing preview (within ACTIVE) — built

A **non-binding estimate**, not an invoice: usage is hand-entered and Sales, not
finance, runs it. `record_billing_preview` (a guarded mutation, not a state
transition — status stays `ACTIVE`) takes a billing month + per-SKU usage and
appends a `private-pricing-billing-preview` to `record["billing_previews"]` (one
per month; regenerating a month replaces it; logged in history).

- `build_billing_preview(config, month, usage, catalog)` — for each SKU with
  usage > 0: resolve its rate; `gross_amount = qty × list_price`,
  `amount = qty × net_unit_price`. Carries `gross_subtotal` (at list),
  `discount_total` + `savings_pct` (what the agreement saves), `subtotal`/`total`
  (at negotiated rates).
- **Simple metered math** — no commitment drawdown, true-up, or overage.
- UX: editable full-catalog usage table (net unit price read-only) + "Load sample
  usage"; a live "list vs your rate vs saving" total updates as quantities change.
- PDF titled "Billing Preview" with a "not an invoice" disclaimer; per-line
  list/discount/net and list-vs-negotiated totals.

Later: per-SKU override rules; usage/volume tiers evaluated at rating time;
commitment drawdown + true-up; real e-signature; multi-user.
