# Private Pricing Customer Onboarding

A Sales portal for onboarding a customer onto a **private (committed-spend) pricing
agreement**. Sales authors the deal, the tool produces a signable agreement, the
customer signs (mocked), and the onboarding is set up for billing.

Built as a **stateful workflow**: each onboarding is a record that carries its
state through the steps, persists across restarts, and shows up on a tracker.

```
DRAFT ──generate──▶ AGREEMENT_READY ──send──▶ PENDING_SIGNATURE ──sign──▶ SIGNED ──provision──▶ ACTIVE
```

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Opens at http://localhost:8501. State is written to `data/onboardings.json`
(git-ignored) — delete it to reset.

Run the state-machine tests (stdlib only, no extra deps):

```bash
python -m unittest discover -s tests
```

## What's built (this iteration)

- **Onboarding tracker** — sidebar list of every in-flight onboarding with status + commitment; open one to resume.
- **Step 1 · Author agreement** — a minimal form:
  - Customer name (auto-filled `John Doe` / `Jane Doe`, editable) · Company name
  - Start date · Term length (12 / 24 / 36 mo → end date derived)
  - Annual committed spend (USD)
  - Pricing: `Cross-service` / `Per-service` / `Both`; cross-service % and/or per-service `service + %` rows
  - System-stamped: currency = USD, billing = monthly in arrears
- **Step 2 · Generate agreement** — validation guard, then a one-page **Private Pricing Agreement PDF** (downloadable). Editing after this reverts to Draft.
- **Step 3 · Send for signature** — marks it sent (stands in for DocuSign).
- **Step 4 · Mark as signed** — a mock button for the customer action; records signer + timestamp.
- **Step 5 · Provision billing** (`SIGNED → ACTIVE`) — resolve the agreement's
  discounts into a **billing config** (JSON) and a derived **private pricing table**:
  - the cross-service discount is a flat `cross_service_discount_pct`
  - each service-specific discount is a rule with a `match` expression
    (`{field: service_code, op: eq, value: CLAUDE_CODE}`) the billing engine
    filters the catalog with — SKUs are never hard-listed
  - per SKU: first matching rule → else the cross-service baseline → else list price
  - the per-SKU rate table is **derived on demand**, never stored (list prices can
    change; the config still resolves correctly)
  - exports: billing config JSON + rate table CSV
- **Invoicing** (on the ACTIVE screen, "Invoicing" tab) — pick a billing month,
  enter per-SKU usage (editable table, or "Load sample usage"), and generate that
  month's invoice: `amount = quantity × net unit price`, with each line and the
  totals showing **gross (list) and net (post-discount)**. One invoice per month
  (regenerating replaces it). Simple metered billing — no commitment drawdown /
  true-up / overage. Each invoice downloads as a PDF.
- **History** — every transition is logged on the record (audit trail).
- Persistence in one JSON file; atomic writes.

## Layout

```
app.py         Streamlit UI (thin — the wizard glue)
workflow.py    pure state machine: new_record, validate_agreement, apply(record, action)
engine.py      billing config builder + match-expression evaluator + rate resolver + invoice builder (pure)
store.py       JSON persistence (dict of records by id)
pdf.py         agreement PDF + invoice PDF via fpdf2 (pure functions)
catalog.py     the public product catalog (5 SKUs, one per service area) + service-code enum
tests/         unittest for workflow.py and engine.py
```

`workflow.py` has no Streamlit or I/O imports — the state machine is testable in
isolation and could move to a service later unchanged.

## Stack

Python 3.11 · Streamlit · fpdf2. No backend, no database.
