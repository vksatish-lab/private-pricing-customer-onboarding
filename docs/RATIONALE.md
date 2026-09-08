# Design rationale

## Theme

**Systems & Reliability.** Onboarding a committed-spend customer is spread across
several systems and teams. This tool runs it as one process over one record: a
state machine with a guard on every transition, a single mutation path, a history
log, and a billing configuration that resolves against one shared catalog rather
than a per-customer price list. It fits the theme's "developer tool that solves a
real workflow pain point."

## The problem

Large customers sign committed-spend contracts: a dollar commitment per year for
negotiated discounts. A few of these customers can be a large share of revenue.

Today it is a hand-off across teams, done in spreadsheets and email. Terms get
keyed in wrong. The discount stops matching the products it was meant for. There
is no single view of where a customer is in the process.

## 1. Integrated onboarding: one record, not three systems

The work is split across separate tools: Sales in a document editor, billing
operations in the billing system, the accounts team in a spreadsheet. They fall
out of sync.

This tool keeps the onboarding as one record. From it:

- the agreement PDF is rendered — parties, a pricing-schedule table, one row per
  discount rule;
- the billing configuration is compiled — the same discount parameters, in the
  form the billing system consumes;
- the workflow status is tracked — draft, sent, signed, provisioned.

What a reviewer signs and what the billing system runs come from the same
parameters, so they stay in sync. There is no free-hand drafting and no step that
parses terms back out of a PDF. Every team reads the same record and its history.

## 2. Attribute-based discounting

One way to give a customer negotiated pricing is a private price list: clone the
SKUs, set each one's rate. It scales poorly — a copy of every priced product per
customer, and every list-price change re-applied to every copy.

Instead, a discount is a **rule whose `match` is a predicate over product
attributes** (`service_code`, `unit`, `id`, `price_source`). At provisioning the
agreement compiles to a small set of these rules plus one flat cross-service
percentage. The per-SKU rate table is *derived on demand* from (rules + current
catalog) and never stored.

Consequences:

- One rule covers a whole product family — every Claude API token line, cache
  line, batch line — and any product added to that family later, with no change
  to the configuration.
- The stored configuration stays a handful of lines regardless of catalog size.
- A list-price change reaches every customer, because no customer holds a copy of
  the price.

Today the UI only creates `service_code`-level rules. The engine evaluates
arbitrary attribute predicates (`unit`, `id`, `price_source`, `all`/`any`);
`test_engine.py` exercises those.

## 3. The workflow is a guarded state machine

`apply(record, action, payload)` is the only function that changes a record. It
copies the record, checks the transition is legal, runs the guard, applies the
change, appends to `history`, returns the new record. It does no I/O. The UI is
derived from `status`. The logic is tested without the UI (34 `unittest` cases,
standard library only).

## Key decisions and tradeoffs

1. **Python + Streamlit, no backend.** Started as a zero-build vanilla-JS
   single-page app; the wizard state got verbose. Streamlit handles the
   multi-step state and reruns on its own. Cost: a `pip install` and working
   within Streamlit's rerun model. Rejected React + FastAPI as more setup than
   the prototype needs.
2. **Discounts are percentages, not absolute rates.** A percentage composes with
   an evolving catalog; an absolute rate attached to an attribute set breaks the
   moment a matching SKU has a different list price. Absolute overrides are a
   listed extension.
3. **Cross-service discount is a flat field, not a rule.** It applies to
   everything, so its `match` would be vacuously true — noise. Only targeted
   discounts carry expressions.
4. **Precedence by rule type, not a priority number.** Service-specific beats
   cross-service beats list. One less field to get wrong. Overlapping attribute
   targets would need an explicit priority; deferred.
5. **The rate table is derived, never persisted.** Keeps the stored config small
   and correct across catalog and price changes. The billing preview is likewise
   recomputed from stored usage plus current rules.
6. **Mock signature, hand-entered usage.** Real e-signature and a metering feed
   are integrations, not the idea. The metering dependency is stated explicitly
   in the requirements (assumptions, section 6).
7. **One "Sales" role.** In a real deployment the steps span Sales, billing
   operations, and the customer accounts team. The state machine already
   partitions the work by transition, so roles are a permissions layer, not a
   redesign.
8. **One JSON file for persistence.** A database adds setup for no demo value at
   this size. Writes are atomic (temp file, rename).

## What I would do with more time

1. Automated UI tests. The pure core has 34; the Streamlit UI is verified by hand.
2. Per-SKU override rules — same `match` grammar with `field: id` — for exhibit
   lines that target one SKU.
3. An explicit priority on rules, once overlapping attribute targets are allowed.
4. Volume and ramp tiers evaluated at rating time against real metered usage.
5. Commitment drawdown and true-up in the billing calculation.
6. Real e-signature and a metering feed replacing hand-entered usage.
7. Split the single role into Sales / billing operations / accounts with
   per-transition permissions.
8. A pre-seeded sample onboarding so a reviewer lands on a populated state.

## Time spent

Approximately 6 hours of active design and build on the Python version, plus
about 1.5 hours on the earlier JavaScript prototype that was replaced. Spread
across several sessions with iteration on the discount model and the
requirements doc.

## Status

Code and tests are green (34 `unittest` cases). Deployed at
https://app-pricing-customer-app.streamlit.app, and it also runs locally — setup
and a guided walkthrough are in the README. A **Load sample onboarding** button
puts a provisioned account with a billing preview one click away. Streamlit Cloud
serves one shared, ephemeral instance, so hosted state is not per-visitor; the
sample button covers that.
