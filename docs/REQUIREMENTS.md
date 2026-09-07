# Requirements — Private Pricing Customer Onboarding

## 1. Overview

A web tool for a Sales user to onboard a customer onto a private (committed-spend)
pricing agreement, and to run that agreement afterward. The user authors the deal
terms, the tool produces a signable agreement PDF, the customer signs (mocked),
the tool compiles a billing configuration, and the user generates a monthly
billing preview from usage.

Assignment theme: **Systems & Reliability** — a workflow tool with an explicit
state machine, guards on every transition, deterministic pure logic, an audit
trail, and no server to run.

## 2. Users

| User | Uses the tool to |
|---|---|
| Sales | Author the agreement, send it for signature, provision billing, generate a billing preview for a customer conversation. |
| Billing team (consumer, not a user of the UI) | Receive the billing configuration JSON produced at provisioning. |

## 3. Vocabulary

| Term | Meaning |
|---|---|
| Private pricing agreement | A committed-spend contract: an annual dollar commitment plus a discount structure. |
| Cross-service discount | A single percentage off list price that applies to every SKU. |
| Service-specific discount (SSD) | A percentage off list price for the SKUs of one service. |
| Service code | The stable machine identifier for a service (`CLAUDE_API`, `CLAUDE_CODE`, `CLAUDE_FOR_WORK`, `SERVER_TOOLS`). SSD rules match on this. |
| Catalog | The public product catalog: SKUs with list prices. One catalog for all customers. |
| Billing configuration | The JSON compiled at provisioning. Holds the cross-service percentage and the SSD rules. Does not hold per-SKU prices. |
| Rate table | Per-SKU discount and effective price. Derived from the billing configuration and the current catalog on demand. Never stored. |
| Billing preview | A non-binding cost estimate for one month, computed from hand-entered usage. Not an invoice. |

## 4. Scope

### 4.1 In scope

1. An onboarding tracker listing every onboarding with its status.
2. Agreement authoring: a form with the fields in section 6.
3. Agreement generation: a one-page PDF from the form.
4. A mock signature action that records a signer name and timestamp.
5. Billing configuration: compile the agreement's discounts into the JSON in section 8.
6. Rate table: resolve the billing configuration against the catalog.
7. Billing preview: one per month, from hand-entered usage, with a PDF.
8. A state machine that governs every transition, with guards.
9. Persistence to one JSON file, surviving process restart.
10. A per-record history log of every transition.
11. Exports: billing configuration JSON, rate table CSV, billing preview PDF, agreement PDF.

### 4.2 Out of scope

1. A live usage-metering feed. Usage is typed in.
2. Real electronic signature. The signature step is a button.
3. Commitment drawdown, minimum-commitment shortfall billing, true-up, overage.
4. Volume tiers, ramp schedules.
5. Per-SKU discount overrides in a contract exhibit.
6. Flat (absolute) negotiated unit prices. Discounts are percentages only.
7. Currencies other than USD.
8. Multiple users, authentication, roles.
9. Tax.
10. Editing the catalog or price book through the UI.

## 5. State machine

Statuses: `DRAFT`, `AGREEMENT_READY`, `PENDING_SIGNATURE`, `SIGNED`, `ACTIVE`.

| Action | From | To | Guard |
|---|---|---|---|
| `generate_agreement` | `DRAFT` | `AGREEMENT_READY` | Agreement passes validation (section 7). |
| `send_for_signature` | `AGREEMENT_READY` | `PENDING_SIGNATURE` | A document was generated. |
| `mark_signed` | `PENDING_SIGNATURE` | `SIGNED` | — |
| `provision_billing` | `SIGNED` | `ACTIVE` | Account number is present. |
| `update_agreement` | `DRAFT`, `AGREEMENT_READY` | `DRAFT` | Not allowed once sent for signature. From `AGREEMENT_READY` it discards the generated document. |
| `record_billing_preview` | `ACTIVE` | `ACTIVE` | Billing month is `YYYY-MM`; usage has at least one positive quantity. |

`apply(record, action, payload)` is the only function that changes a record. It
deep-copies the record, checks the transition is legal, runs the guard, applies
the change, appends a `history` entry, and returns the new record. It performs no
file or network I/O.

Every transition appends `{ at, action, from, to }` to `history`. An
`update_agreement` from `AGREEMENT_READY` also appends `{ action: "revise" }`. A
`record_billing_preview` appends `note` set to the billing month.

## 6. Agreement fields

The Sales user enters:

| Field | Rule |
|---|---|
| Customer name | Required. Pre-filled with `John Doe` or `Jane Doe` at record creation. This is the signer. |
| Company name | Required. |
| Account number | Required. The billing account the discount applies to. |
| Start date | Required. Defaults to today. |
| Term length | `12`, `24`, or `36` months. End date = start + term − 1 day. |
| Annual committed spend (USD) | Required. Greater than 0. |
| Discount model | `cross_service`, `per_service`, or `both`. |
| Cross-service discount % | Shown and required when the model is `cross_service` or `both`. 0 to 100. |
| Per-service rows | Shown when the model is `per_service` or `both`. Each row is a service (from the catalog) and a percentage 0 to 100. At least one row. |

Set by the system, not shown as inputs: `currency = USD`, `billing = monthly in
arrears`, record id, status, timestamps, history.

## 7. Agreement validation

`generate_agreement` fails, and lists every problem, if any of these hold:

1. Customer name is empty.
2. Company name is empty.
3. Account number is empty.
4. Annual committed spend is not greater than 0.
5. Term length is not 12, 24, or 36.
6. Discount model is not one of the three values.
7. Model needs a cross-service percentage and it is missing or outside 0–100.
8. Model needs per-service rows and there are none.
9. A per-service row names a service that is not in the catalog.
10. A service appears in more than one per-service row.
11. A per-service percentage is missing or outside 0–100.

## 8. Billing configuration

`provision_billing` writes this JSON to `record.billing_config`:

```jsonc
{
  "kind": "private-pricing-billing-config",
  "version": "1.0",
  "onboarding_ref": "ONB-XXXXXXXX",
  "account_number": "GLBX-004417",
  "customer": { "company_name": "...", "signer_name": "..." },
  "currency": "USD",
  "billing": "monthly in arrears",
  "effective_from": "2026-09-05",
  "effective_to": "2027-09-04",
  "annual_committed_spend_usd": 5000000.0,
  "price_book_date": "2026-08-01",
  "provisioned_at": "2026-09-07T17:42:41+00:00",
  "cross_service_discount_pct": 12,          // integer, or null when the model has no cross-service part
  "discount_rules": [                        // one per per-service row; empty when the model is cross_service
    {
      "id": "ssd-claude-code",
      "type": "service_specific_discount",
      "description": "Claude Code service discount",
      "discount_pct": 20,
      "match": { "all": [ { "field": "service_code", "op": "eq", "value": "CLAUDE_CODE" } ] }
    }
  ]
}
```

### 8.1 Match expression grammar

- Leaf: `{ "field": F, "op": OP, "value": V }`. `F` is one of `service_code`, `id`,
  `unit`, `price_source`. `OP` is `eq` or `in`. For `in`, `V` is a list.
- Combinator: `{ "all": [ expr, ... ] }` (AND) or `{ "any": [ expr, ... ] }` (OR).
- An unknown field or op is an error.

### 8.2 Resolution

For each SKU in the catalog:

1. Evaluate `discount_rules` in order. The first rule whose `match` is satisfied
   applies its `discount_pct`; record its `id` as the applied rule.
2. If no rule matched and `cross_service_discount_pct` is set, apply it; record the
   applied rule as `cross_service`.
3. Otherwise the SKU bills at list price; the applied rule is null.

`effective_price = round(list_price × (1 − pct/100), 4)` for `per_mtok` SKUs,
2 decimals otherwise.

The rate table is `{ lines: [...], summary: { skus_total, skus_discounted,
skus_at_list, skus_at_list_ids } }`. It is computed on request. It is not written
to the record or the store.

## 9. Billing preview

`record_billing_preview` takes a billing month (`YYYY-MM`) and a map of SKU id to
quantity. It appends this JSON to `record.billing_previews`:

```jsonc
{
  "kind": "private-pricing-billing-preview",
  "version": "1.0",
  "preview_number": "BP-GLBX-004417-2026-09",
  "account_number": "GLBX-004417",
  "customer": { "company_name": "...", "signer_name": "..." },
  "config_ref": "ONB-XXXXXXXX",
  "billing_period": "2026-09",
  "generated_at": "2026-09-07T17:42:41+00:00",
  "currency": "USD",
  "price_book_date": "2026-08-01",
  "lines": [
    {
      "sku_id": "API-OPUS-5-INPUT",
      "description": "Claude Opus 5 - input tokens",
      "service_code": "CLAUDE_API",
      "unit": "per_mtok",
      "quantity": 120.0,
      "list_price": 5.0,
      "discount_pct": 10,
      "unit_price": 4.5,
      "applied_rule": "cross_service",
      "gross_amount": 600.0,
      "amount": 540.0
    }
  ],
  "gross_subtotal": 5850.0,     // sum of gross_amount, at list price
  "discount_total": 783.0,      // gross_subtotal − subtotal
  "savings_pct": 13.4,          // discount_total / gross_subtotal × 100, 1 decimal
  "subtotal": 5067.0,           // sum of amount, at negotiated rates
  "total": 5067.0
}
```

Rules:

1. Only SKUs with quantity greater than 0 produce a line. Unknown SKU ids are
   dropped.
2. `gross_amount = round(quantity × list_price, 2)`. `amount = round(quantity ×
   effective_price, 2)`.
3. One preview per billing month. Generating a preview for a month that already
   has one replaces it.
4. The preview is a cost estimate. It applies no commitment drawdown, true-up, or
   overage.

## 10. Catalog

Five SKUs, one per service area:

| id | service_code | unit | list_price |
|---|---|---|---|
| `API-OPUS-5-INPUT` | `CLAUDE_API` | per_mtok | 5.00 |
| `API-OPUS-5-OUTPUT` | `CLAUDE_API` | per_mtok | 25.00 |
| `CLAUDE-CODE-USAGE` | `CLAUDE_CODE` | per_mtok | 6.00 |
| `CLAUDE-ENTERPRISE-SEAT` | `CLAUDE_FOR_WORK` | per_seat_month | 60.00 |
| `TOOL-WEB-SEARCH` | `SERVER_TOOLS` | per_1k_calls | 10.00 |

`price_book_date = 2026-08-01`. `CLAUDE-CODE-USAGE`, `CLAUDE-ENTERPRISE-SEAT`, and
`TOOL-WEB-SEARCH` list prices are illustrative; the Opus prices are public.

## 11. User interface

1. **Tracker** (sidebar): a "New onboarding" button and a row per onboarding
   showing company name, status, and annual commitment. Selecting a row opens it.
2. **Progress tracker** (top of each onboarding): five steps — Draft, Agreement,
   Signature, Signed, Billing. Completed steps are filled; the current step is
   marked.
3. **Draft screen**: the agreement form (section 6). "Save draft" persists.
   "Generate agreement" runs validation and advances on success; on failure it
   lists every problem.
4. **Agreement-ready screen**: the agreement summary, a PDF download, "Send for
   signature", and an editor that reverts to Draft.
5. **Pending-signature screen**: the sent-to line, a PDF download, and a
   "Mark as signed" button.
6. **Signed screen**: the signed-by line, a PDF download, and a
   "Billing configuration" section — the rate table, a per-rule line showing each
   rule's target service code and percentage, and "Provision billing account".
7. **Active screen**: two tabs.
   - Rate table: the resolved table (SKU, service, service code, unit, list price,
     discount, effective price, applied rule), the billing-config JSON, and
     downloads for the JSON and the CSV.
   - Billing preview: a billing-month field, "Load sample usage", an editable
     usage table (SKU, service code, unit, net unit price read-only, quantity), a
     live "list price vs your rate vs saving" total, "Generate billing preview",
     and each generated preview with its line detail and a PDF download.
8. **History** (expander on every screen): the transition log.

## 12. Documents

### 12.1 Agreement PDF

One page. Sections: Parties (both names and a representative line each), Pricing
Schedule (a two-column key/value table: account number, effective date, contract
term, end date, currency, billing, annual committed spend, discount model,
cross-service discount, one row per service-specific discount), Terms and
Conditions (eight numbered boilerplate clauses), Signatures. A footer carries the
record id, status, and generation timestamp; a `DRAFT` record is marked
"DRAFT — NOT FOR EXECUTION".

### 12.2 Billing preview PDF

One page. Title "Billing Preview" with the line "Non-binding estimate from entered
usage. Not an invoice." Metadata: reference, account, customer, billing period,
generated timestamp, currency, price book date. A line-item table: item, quantity,
list unit price, discount, net unit price, amount. Totals: "At list price",
"Agreement saving (N%)", "At your negotiated rates".

## 13. Non-functional requirements

1. **Stack**: Python 3.11 or later, Streamlit, `fpdf2`. No other runtime
   dependency.
2. **No backend**: no server process of its own, no database, no authentication.
3. **Persistence**: one JSON file, `data/onboardings.json`, holding a map of
   record id to record. Writes are atomic (write a temp file, rename over the
   target). The file is not committed.
4. **Purity**: `workflow.py` and `engine.py` import no Streamlit and perform no
   file or network I/O. They are covered by `unittest` with no third-party test
   dependency.
5. **Determinism**: amounts round to 2 decimals; `per_mtok` effective unit prices
   round to 4. The screen, the JSON, and the CSV show the same numbers.
6. **Timestamps**: ISO 8601, UTC, second precision.
7. **Run**: `pip install -r requirements.txt` then `streamlit run app.py`.
8. **Deploy**: the repository runs on Streamlit Community Cloud with no change.

## 14. Files

```
app.py         Streamlit UI. Screens, tracker, tabs.
workflow.py    State machine: new_record, validate_agreement, apply.
engine.py      build_billing_config, match_sku, resolve_rate_table, rate_table_to_csv,
               build_billing_preview.
catalog.py     The public catalog and service-code enum.
store.py       JSON persistence.
pdf.py         build_agreement_pdf, build_billing_preview_pdf.
tests/         unittest for workflow.py and engine.py.
```

## 15. Planned extensions

1. Per-SKU override rules in the billing configuration.
2. Volume and ramp tiers evaluated at rating time.
3. Commitment drawdown and true-up.
4. Real electronic signature.
5. A live usage-metering feed in place of typed usage.
6. Multiple users and roles.
