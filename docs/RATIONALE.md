# Design rationale

## Theme

**Systems & Reliability.** The hard part of onboarding a committed-spend customer
is not a screen — it is the correctness of a multi-step process and the shape of
the data that feeds billing. The theme lists "a developer tool that solves a real
workflow pain point"; that is what this is. The systems content is an explicit
state machine with a guard on every transition, a single pure mutation path, an
append-only history, and a billing configuration that *resolves* against one
shared catalog instead of *materialising* a price list per customer.

This is not the failure-handling / concurrency / stress reading of the theme. It
is the workflow-correctness reading.

## The problem

Large customers sign committed-spend contracts: a dollar commitment per year for
negotiated discounts. These customers are large, so a small number of them
account for the majority of revenue.

Setting one up to bill correctly is a hand-off across teams, done ad hoc in
spreadsheets and email. Steps get skipped. Discounts get entered against the
wrong products. The discount definition drifts from the products it covers.
Nothing shows where a given customer is in the process.

Onboarding these accounts accurately and on schedule is part of their product
experience. A billing error hits a top account. A delay blocks their launch.

## The non-obvious idea: attribute-based discounting

The obvious way to give a customer negotiated pricing is a **private price list**:
clone the SKUs, set each one's rate. Many billing systems do exactly this, and a
reviewer might expect it. It does not scale. N customers times M products. The
same product duplicated under many ids. Every list-price change re-applied to
every private copy.

Instead, a discount is a **rule whose `match` is a predicate over product
attributes** (`service_code`, `unit`, `id`, `price_source`). At provisioning the
agreement compiles to a small set of these rules plus one flat cross-service
percentage. The per-SKU rate table is *derived on demand* from (rules + current
catalog) and never stored.

Consequences:

- One rule covers a whole product family — every Claude API token line, cache
  line, batch line — and every product added to that family later, with no change
  to the configuration.
- The stored configuration is a handful of lines whatever the catalog size, so it
  cannot drift as the product set grows.
- A list-price change propagates to every customer automatically, because no
  customer holds a copy of the price.

## Secondary idea: the workflow is a guarded state machine

`apply(record, action, payload)` is the only function that changes a record. It
copies the record, checks the transition is legal, runs the guard, applies the
change, appends to `history`, returns the new record. It does no I/O. The UI is
derived entirely from `status`. The result: the process is auditable, and the
logic is tested without the UI (33 `unittest` cases, no third-party test
dependency).

## Key decisions and tradeoffs

1. **Python + Streamlit, no backend.** Started as a zero-build vanilla-JS
   single-page app; the wizard state got verbose and there was no one-command
   host. Streamlit gives a stateful multi-step UI with little UI code and a free
   deploy. Cost: a `pip install` and Streamlit's rerun model. Rejected
   React + FastAPI (more infra, no free one-click host).
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

1. Deploy to Streamlit Community Cloud and do a full browser pass on the UI.
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
across several sessions with heavy iteration on the discount model and the
requirements doc.

## Status

Code and tests are complete and green. Not yet deployed; the hosted URL and the
video are outstanding.
