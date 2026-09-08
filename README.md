# Private Pricing Customer Onboarding

A Sales portal for onboarding a customer onto a **private (committed-spend) pricing
agreement**. Sales authors the deal, the tool produces a signable agreement, the
customer signs (mocked), and the onboarding is provisioned for billing.

One structured record drives the whole thing: the same discount parameters render
the agreement PDF, compile the billing configuration, and track workflow status.

```
DRAFT ──generate──▶ AGREEMENT_READY ──send──▶ PENDING_SIGNATURE ──sign──▶ SIGNED ──provision──▶ ACTIVE
```

Full spec: [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md). Design rationale:
[`docs/RATIONALE.md`](docs/RATIONALE.md).

## Requirements

- Python **3.11 or later**
- Nothing else — two pip packages (`streamlit`, `fpdf2`), no database, no backend

## Run it locally

```bash
git clone https://github.com/vksatish-lab/private-pricing-customer-onboarding.git
cd private-pricing-customer-onboarding

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

pip install -r requirements.txt
streamlit run app.py
```

Streamlit opens a browser tab at **http://localhost:8501**. Stop with `Ctrl-C`.

State is written to `data/onboardings.json` (git-ignored). Delete that file to
reset to an empty tracker.

## First run

**Fastest:** sidebar → **🧪 Load sample onboarding**. This creates a
provisioned account (Globex Corporation, $5M/yr, cross-service 12% + Claude Code
20%) with a billing preview already generated, so the resolved rate table, the
billing-config JSON, and the preview PDF are one screen away. Open **History** to
see every transition that built it.

**To walk the workflow yourself:**

1. Sidebar → **➕ New onboarding**. A draft opens with a random signer name.
2. Fill **Company name**, **Account number** (e.g. `GLBX-004417`), **Annual
   committed spend** (e.g. `5000000`). Pick a **Discount model** — try
   *Cross-service + per-service*, set the cross-service % and add one per-service
   row (e.g. Claude Code, 20%). Click **📄 Generate agreement**.
3. **⬇ Download agreement PDF** to see the generated contract, then **📧 Send for
   signature**.
4. **🖊 Mark as signed** (stands in for the customer signing).
5. **💳 Provision billing account**. The **Rate table** tab shows each catalog SKU
   with its resolved discount, its `service_code`, and which rule applied.
   Download the **billing config JSON** and **rate table CSV**.
6. **Billing preview** tab → **Load sample usage** → **Generate billing preview
   for <month>**. The preview shows list price vs negotiated rate vs the saving,
   and downloads as a PDF.

The **History** expander on every screen shows the full transition log.

## Run the tests

```bash
python -m unittest discover -s tests
```

33 tests, standard library only — no packages needed beyond what `streamlit run`
already installs. They cover the state machine, the discount-match grammar, the
rate-table precedence, and the billing-preview math.

## Layout

```
app.py         Streamlit UI — sidebar tracker + one screen per status.
workflow.py    Pure state machine: new_record, validate_agreement, apply(record, action).
engine.py      Pure: build_billing_config, match_sku, resolve_rate_table,
               rate_table_to_csv, build_billing_preview.
catalog.py     The public product catalog (5 SKUs, one per service area) + service-code enum.
store.py       JSON persistence (one file, atomic writes).
pdf.py         Agreement PDF + billing-preview PDF via fpdf2 (pure functions).
tests/         unittest for workflow.py and engine.py.
docs/          REQUIREMENTS.md, RATIONALE.md, AI-TRANSCRIPT.txt.
```

`workflow.py` and `engine.py` import no Streamlit and do no file or network I/O —
the logic is tested without the UI and could move to a service unchanged.

## What it does

- **Onboarding tracker** — every in-flight onboarding with its status; open one to resume.
- **Author agreement** — company, account number, start date, term (12/24/36 mo →
  end date derived), annual committed spend, discount model (`cross_service` /
  `per_service` / `both`) with a cross-service % and/or per-service rows.
  Currency (USD) and billing cadence (monthly in arrears) are stamped by the system.
- **Generate agreement** — validated, then a one-page agreement PDF.
- **Send for signature** / **Mark as signed** — mocked; records signer + timestamp.
- **Provision billing** — compiles the discounts into a billing configuration:
  a flat `cross_service_discount_pct` plus one rule per service-specific discount,
  each rule a `match` expression over product attributes (`{field: service_code,
  op: eq, value: CLAUDE_CODE}`). SKUs are never hard-listed. The per-SKU rate
  table is derived on demand from the config and the current catalog; it is never
  stored. Exports: config JSON, rate table CSV.
- **Billing preview** — a non-binding monthly estimate from hand-entered usage:
  list price vs negotiated rate vs the saving, live as you type; one saved preview
  per month; PDF download. No commitment drawdown / true-up / overage.
- **History** — every transition logged on the record.

## Stack

Python 3.11 · Streamlit · fpdf2. No backend, no database, no auth.
