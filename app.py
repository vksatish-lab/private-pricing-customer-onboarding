"""Private Pricing Customer Onboarding -- Streamlit portal for Sales.

Flow:  author agreement -> generate -> send for signature -> (mock) customer
signs -> provision billing (resolve discounts to a per-SKU rate table).

State lives in store.py (one JSON file). st.session_state only remembers which
onboarding is open. Every button calls workflow.apply(), persists, and reruns --
so the screen is always derived from the record's status.
"""
from __future__ import annotations

import json
import re
from datetime import date

import streamlit as st

import engine
import store
import workflow as wf
from catalog import SERVICE_NAMES
from pdf import build_agreement_pdf

st.set_page_config(page_title="Private Pricing Onboarding", page_icon="🧾", layout="wide")

MAX_PER_SERVICE_ROWS = 4

# (status, tracker label, icon) in order
STEPS = [
    ("DRAFT", "Draft", "📝"),
    ("AGREEMENT_READY", "Agreement", "📄"),
    ("PENDING_SIGNATURE", "Signature", "🖊️"),
    ("SIGNED", "Signed", "🎉"),
    ("ACTIVE", "Billing", "💳"),
]

_TRACKER_CSS = """
<style>
.ppco-track{display:flex;align-items:flex-start;margin:2px 0 10px;}
.ppco-step{display:flex;flex-direction:column;align-items:center;flex:0 0 auto;width:104px;}
.ppco-dot{width:46px;height:46px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-size:20px;border:2px solid #3a3f4b;background:#20242e;color:#9aa3b2;}
.ppco-step.done .ppco-dot{background:#16a34a;border-color:#16a34a;color:#fff;}
.ppco-step.current .ppco-dot{border-color:#f2a900;color:#f2a900;box-shadow:0 0 0 4px rgba(242,169,0,.18);}
.ppco-lbl{margin-top:7px;font-size:12px;color:#9aa3b2;text-align:center;}
.ppco-step.done .ppco-lbl,.ppco-step.current .ppco-lbl{color:#e7e9ee;font-weight:600;}
.ppco-bar{flex:1 1 auto;height:3px;background:#3a3f4b;margin:22px -8px 0;border-radius:2px;}
.ppco-bar.done{background:#16a34a;}
</style>
"""


def _parse_date(s: str) -> date:
    y, m, d = (int(x) for x in s.split("-"))
    return date(y, m, d)


def _money(x) -> str:
    return f"${float(x):,.0f}"


def _pct(x) -> str:
    return f"{int(round(float(x)))}%"


# --------------------------------------------------------------- sidebar / tracker
def render_sidebar() -> None:
    st.sidebar.title("Onboarding tracker")
    if st.sidebar.button("➕  New onboarding", use_container_width=True, type="primary"):
        rec = wf.new_record()
        store.upsert(rec)
        st.session_state.active_id = rec["id"]
        st.rerun()

    records = store.list_records()
    st.sidebar.caption(f"{len(records)} in flight" if records else "Nothing in flight yet")

    active = st.session_state.get("active_id")
    for r in records:
        a = r["agreement"]
        name = a["company_name"] or "(unnamed)"
        marker = "▸ " if r["id"] == active else ""
        label = f"{marker}{name}\n{wf.STATUS_LABEL[r['status']]}  ·  {_money(a['annual_commitment_usd'])}/yr"
        if st.sidebar.button(label, key=f"pick_{r['id']}", use_container_width=True):
            st.session_state.active_id = r["id"]
            st.rerun()


# --------------------------------------------------------------- progress + history
def render_progress(status: str) -> None:
    idx = [s[0] for s in STEPS].index(status)
    html = ['<div class="ppco-track">']
    for i, (_key, label, icon) in enumerate(STEPS):
        cls = "done" if i < idx else ("current" if i == idx else "")
        dot = "✓" if i < idx else icon
        html.append(
            f'<div class="ppco-step {cls}"><div class="ppco-dot">{dot}</div>'
            f'<div class="ppco-lbl">{label}</div></div>'
        )
        if i < len(STEPS) - 1:
            html.append(f'<div class="ppco-bar {"done" if i < idx else ""}"></div>')
    html.append("</div>")
    st.markdown(_TRACKER_CSS + "".join(html), unsafe_allow_html=True)


def render_history(rec: dict) -> None:
    with st.expander("History"):
        for h in rec["history"]:
            frm = h["from"] or "—"
            st.text(f"{h['at']}   {h['action']:<20}  {frm} → {h['to']}")


# --------------------------------------------------------------- agreement preview
def render_agreement_preview(rec: dict) -> None:
    a = rec["agreement"]
    end = wf.compute_end_date(a["start_date"], a["term_months"])
    lines = [
        f"**Private Pricing Agreement — {rec['id']}**",
        f"- **Customer:** {a['company_name'] or '—'}  (signer: {a['customer_name']})",
        f"- **Account number:** {a.get('account_number') or '—'}",
        f"- **Term:** {a['start_date']} → {end}  ({a['term_months']} months)",
        f"- **Committed spend:** {_money(a['annual_commitment_usd'])}/yr",
        f"- **Currency / billing:** {wf.STAMPED['currency']} · {wf.STAMPED['billing']}",
    ]
    model = a["discount_model"]
    if model in ("cross_service", "both"):
        lines.append(f"- **Cross-service discount:** {_pct(a['cross_service_pct'])}")
    if model in ("per_service", "both"):
        rows = "  ·  ".join(
            f"{r['service']} {_pct(r['pct'])}" for r in a["per_service"] if r.get("service")
        )
        lines.append(f"- **Per-service discounts:** {rows or '—'}")
    # escape $ so Streamlit doesn't treat "$...$" as LaTeX
    st.markdown("\n".join(lines).replace("$", "\\$"))


def download_pdf_button(rec: dict, label: str) -> None:
    st.download_button(
        label,
        data=build_agreement_pdf(rec),
        file_name=f"{rec['id']}-private-pricing-agreement.pdf",
        mime="application/pdf",
        key=f"dl_{rec['id']}_{rec['status']}",
    )


# --------------------------------------------------------------- step 1: the form
def render_agreement_form(rec: dict) -> None:
    a = rec["agreement"]
    rid = rec["id"]

    c1, c2 = st.columns(2)
    customer_name = c1.text_input("Customer name (signer)", value=a["customer_name"], key=f"cn_{rid}")
    company_name = c2.text_input("Company name", value=a["company_name"], key=f"co_{rid}")

    account_number = st.text_input(
        "Account number",
        value=a.get("account_number", ""),
        key=f"an_{rid}",
        help="The billing account this discount will be applied to.",
    )

    c1, c2, c3 = st.columns(3)
    start_date = c1.date_input("Start date", value=_parse_date(a["start_date"]), key=f"sd_{rid}")
    term_months = c2.selectbox(
        "Term length", wf.TERM_MONTHS,
        index=wf.TERM_MONTHS.index(a["term_months"]),
        format_func=lambda m: f"{m} months", key=f"tm_{rid}",
    )
    c3.text_input(
        "End date (derived)",
        value=wf.compute_end_date(start_date.isoformat(), term_months),
        disabled=True, key=f"ed_{rid}",
    )

    commitment = st.number_input(
        "Annual committed spend (USD)", min_value=0.0, step=100_000.0,
        value=float(a["annual_commitment_usd"]), format="%.0f", key=f"ac_{rid}",
    )

    st.markdown("**Pricing**")
    model = st.radio(
        "Discount model", wf.DISCOUNT_MODELS,
        index=wf.DISCOUNT_MODELS.index(a["discount_model"]),
        format_func=lambda m: wf.DISCOUNT_MODEL_LABEL[m],
        horizontal=True, key=f"dm_{rid}",
    )

    cross_pct = int(round(float(a.get("cross_service_pct") or 0)))
    if model in ("cross_service", "both"):
        cross_pct = st.number_input(
            "Cross-service discount %", min_value=0, max_value=100, step=1,
            value=cross_pct, key=f"cx_{rid}",
        )

    per_service: list[dict] = []
    if model in ("per_service", "both"):
        st.caption("Per-service discounts — service · discount %")
        existing = a.get("per_service", [])
        for i in range(MAX_PER_SERVICE_ROWS):
            row = existing[i] if i < len(existing) else {}
            cc1, cc2 = st.columns([3, 1])
            svc = cc1.selectbox(
                f"service {i}", ["—"] + SERVICE_NAMES,
                index=(SERVICE_NAMES.index(row["service"]) + 1)
                if row.get("service") in SERVICE_NAMES else 0,
                key=f"ps_svc_{rid}_{i}", label_visibility="collapsed",
            )
            pct = cc2.number_input(
                f"pct {i}", min_value=0, max_value=100, step=1,
                value=int(round(float(row.get("pct", 0)))),
                key=f"ps_pct_{rid}_{i}", label_visibility="collapsed",
            )
            if svc != "—":
                per_service.append({"service": svc, "pct": pct})

    edited = {
        "customer_name": customer_name,
        "company_name": company_name,
        "account_number": account_number,
        "start_date": start_date.isoformat(),
        "term_months": term_months,
        "annual_commitment_usd": commitment,
        "discount_model": model,
        "cross_service_pct": cross_pct,
        "per_service": per_service,
    }

    problems = wf.validate_agreement(edited)

    b1, b2, _ = st.columns([1, 1, 2])
    if b1.button("💾  Save draft", key=f"save_{rid}", use_container_width=True):
        store.upsert(wf.apply(rec, "update_agreement", {"agreement": edited}))
        st.toast("Draft saved")
        st.rerun()
    if b2.button(
        "📄  Generate agreement →", key=f"gen_{rid}", type="primary",
        use_container_width=True, disabled=bool(problems),
    ):
        rec2 = wf.apply(rec, "update_agreement", {"agreement": edited})
        rec2 = wf.apply(rec2, "generate_agreement")
        store.upsert(rec2)
        st.rerun()

    if problems:
        st.info("Not ready to generate:\n\n- " + "\n- ".join(problems))


# --------------------------------------------------------------- per-status screens
def screen_draft(rec: dict) -> None:
    st.subheader("1 · Author agreement")
    render_agreement_form(rec)


def screen_agreement_ready(rec: dict) -> None:
    st.subheader("2 · Agreement ready")
    st.success(f"Agreement generated {rec['document']['generated_at']} (UTC).")
    render_agreement_preview(rec)
    download_pdf_button(rec, "⬇  Download agreement PDF")
    if st.button("📧  Send for signature", type="primary", key=f"send_{rec['id']}"):
        store.upsert(wf.apply(rec, "send_for_signature"))
        st.rerun()
    with st.expander("Edit agreement (reverts to Draft, clears the generated PDF)"):
        render_agreement_form(rec)


def screen_pending_signature(rec: dict) -> None:
    a = rec["agreement"]
    st.subheader("3 · Pending signature")
    st.info(
        f"📨  Sent to **{a['customer_name']}** at **{a['company_name']}** "
        f"on {rec['sent_for_signature_at']} (UTC). Awaiting signature."
    )
    render_agreement_preview(rec)
    download_pdf_button(rec, "⬇  Download agreement PDF")
    st.divider()
    st.caption("Mock — stand in for the customer signing in DocuSign")
    if st.button(f"🖊  Mark as signed by {a['customer_name']}", type="primary", key=f"sign_{rec['id']}"):
        store.upsert(wf.apply(rec, "mark_signed"))
        st.balloons()
        st.rerun()


def _render_billing_review(config: dict, table: dict) -> None:
    """The private pricing table + a summary. Used on both SIGNED and ACTIVE."""
    cross = config.get("cross_service_discount_pct")
    bits: list[str] = []
    if cross is not None:
        bits.append(f"Cross-service **{cross}%**")
    for rule in config["discount_rules"]:
        codes = ", ".join(
            leaf.get("value", "") for leaf in rule["match"].get("all", []) if leaf.get("field") == "service_code"
        )
        bits.append(f"{rule['description']} → `{codes}` **{rule['discount_pct']}%**")
    st.markdown(("  ·  ".join(bits) or "No discounts.").replace("$", "\\$"))

    s = table["summary"]
    note = f"{s['skus_discounted']} of {s['skus_total']} SKUs discounted · {s['skus_at_list']} at list price"
    if s["skus_at_list_ids"]:
        note += "  (" + ", ".join(s["skus_at_list_ids"]) + ")"
    st.caption(note)

    rows = [
        {
            "SKU": ln["sku_id"],
            "Service": ln["service"],
            "Service code": ln["service_code"],
            "Unit": ln["unit"],
            "List $": ln["list_price"],
            "Disc %": ln["discount_pct"],
            "Effective $": ln["effective_price"],
            "Applied rule": ln["applied_rule"] or "list price",
        }
        for ln in table["lines"]
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def screen_signed(rec: dict) -> None:
    sig = rec["signature"]
    st.subheader("4 · Signed")
    st.success(f"✅  Signed by **{sig['signer_name']}** on {sig['signed_at']} (UTC).")
    render_agreement_preview(rec)
    download_pdf_button(rec, "⬇  Download signed agreement PDF")

    st.divider()
    st.subheader("5 · Billing configuration")
    st.caption(
        "Resolve the agreement's discounts against the public catalog. Review, then provision."
    )
    config = engine.build_billing_config(rec)
    table = engine.resolve_rate_table(config)
    _render_billing_review(config, table)

    if st.button("💳  Provision billing account", type="primary", key=f"prov_{rec['id']}"):
        store.upsert(wf.apply(rec, "provision_billing"))
        st.balloons()
        st.rerun()


_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _tab_rate_table(rec: dict) -> None:
    cfg = rec["billing_config"]
    table = engine.resolve_rate_table(cfg)
    _render_billing_review(cfg, table)

    c1, c2 = st.columns(2)
    c1.download_button(
        "⬇  Billing config (JSON)",
        data=json.dumps(cfg, indent=2),
        file_name=f"{cfg['account_number']}-billing-config.json",
        mime="application/json",
        key=f"cfg_json_{rec['id']}",
    )
    c2.download_button(
        "⬇  Rate table (CSV)",
        data=engine.rate_table_to_csv(table, cfg),
        file_name=f"{cfg['account_number']}-rate-table.csv",
        mime="text/csv",
        key=f"rt_csv_{rec['id']}",
    )
    with st.expander("Billing config JSON"):
        st.json(cfg)


def _savings_line(p: dict, prefix: str = "") -> str:
    cur = p["currency"]
    return (
        f"{prefix}list price **{cur} {p['gross_subtotal']:,.2f}**  ·  "
        f"your rate **{cur} {p['subtotal']:,.2f}**  ·  "
        f"saves **{cur} {p['discount_total']:,.2f} ({p.get('savings_pct', 0):g}%)**"
    ).replace("$", "\\$")


def _tab_billing_preview(rec: dict) -> None:
    from pdf import build_billing_preview_pdf

    rid = rec["id"]
    cfg = rec["billing_config"]
    rate_by_id = {ln["sku_id"]: ln for ln in engine.resolve_rate_table(cfg)["lines"]}
    previews_by_month = {p["billing_period"]: p for p in rec.get("billing_previews", [])}

    st.caption(
        "A non-binding estimate: enter a month's usage and see what it costs at this "
        "account's negotiated rates vs. list price."
    )

    month = st.text_input(
        "Billing month", value=date.today().strftime("%Y-%m"), key=f"month_{rid}", help="YYYY-MM",
    )
    valid_month = bool(_MONTH_RE.match(month))
    if not valid_month:
        st.warning("Enter the month as YYYY-MM.")

    # `nonce` forces a fresh data_editor (re-seeded from `rows`) after Load-sample / generate.
    nonce_key = f"usage_nonce_{rid}"
    seed_key = f"usage_seed_{rid}"
    st.session_state.setdefault(nonce_key, 0)

    if st.button("Load sample usage", key=f"sample_{rid}"):
        st.session_state[seed_key] = engine.sample_usage()
        st.session_state[nonce_key] += 1
        st.rerun()

    seed = st.session_state.get(seed_key)
    if seed is None and month in previews_by_month:
        seed = {ln["sku_id"]: ln["quantity"] for ln in previews_by_month[month]["lines"]}
    seed = seed or {}

    rows = [
        {
            "SKU": s["id"],
            "Service code": s["service_code"],
            "Unit": s["unit"],
            "Net $/unit": rate_by_id[s["id"]]["effective_price"],
            "Quantity": float(seed.get(s["id"], 0.0)),
        }
        for s in engine.CATALOG["skus"]
    ]
    edited = st.data_editor(
        rows,
        key=f"usage_editor_{rid}_{month}_{st.session_state[nonce_key]}",
        hide_index=True,
        use_container_width=True,
        disabled=["SKU", "Service code", "Unit", "Net $/unit"],
        column_config={"Quantity": st.column_config.NumberColumn(min_value=0.0, step=1.0)},
    )
    usage = {r["SKU"]: float(r["Quantity"] or 0) for r in edited if float(r["Quantity"] or 0) > 0}

    # live running total as quantities change
    if usage:
        running = engine.build_billing_preview(cfg, month, usage)
        st.markdown(f"**{month}** — " + _savings_line(running))

    exists = month in previews_by_month
    label = f"{'Regenerate' if exists else 'Generate'} billing preview for {month}"
    if st.button(label, type="primary", disabled=not (valid_month and usage), key=f"gen_bp_{rid}"):
        store.upsert(wf.apply(rec, "record_billing_preview", {"month": month, "usage": usage}))
        st.session_state.pop(seed_key, None)
        st.session_state[nonce_key] += 1
        st.toast(f"Billing preview generated for {month}")
        st.rerun()

    st.divider()
    previews = rec.get("billing_previews", [])
    if not previews:
        st.caption("No billing previews yet — enter usage above and generate one.")
        return

    def _preview_block(p: dict) -> None:
        st.markdown("#### " + _savings_line(p))
        st.caption(f"Generated {p.get('generated_at') or '-'} (UTC) · {len(p['lines'])} line(s)")
        st.dataframe(
            [
                {
                    "SKU": ln["sku_id"], "Service code": ln.get("service_code", ""),
                    "Qty": ln["quantity"], "List $/u": ln["list_price"], "Disc %": ln["discount_pct"],
                    "Net $/u": ln["unit_price"], "List $": ln["gross_amount"], "Net $": ln["amount"],
                }
                for ln in p["lines"]
            ],
            hide_index=True, use_container_width=True,
        )
        try:
            pdf_bytes = build_billing_preview_pdf(p)
            st.download_button(
                "⬇  Download billing preview (PDF)",
                data=pdf_bytes,
                file_name=f"{p['preview_number']}.pdf",
                mime="application/pdf",
                type="primary",
                key=f"bp_pdf_{rid}_{p['billing_period']}",
            )
        except Exception as exc:  # noqa: BLE001 -- surface the reason instead of a blank
            st.error(f"Could not build the billing preview PDF: {exc}")

    newest = previews[-1]
    st.markdown(f"### Latest billing preview — {newest['billing_period']}  ·  {newest['preview_number']}")
    _preview_block(newest)

    earlier = list(reversed(previews[:-1]))
    if earlier:
        st.markdown("**Earlier previews**")
        for p in earlier:
            with st.expander(
                f"{p['billing_period']}  ·  {p['preview_number']}  ·  "
                f"{p['currency']} {p['total']:,.2f} at your rates"
            ):
                _preview_block(p)


def screen_active(rec: dict) -> None:
    cfg = rec["billing_config"]
    st.subheader("5 · Billing — active")
    st.success(
        f"✅  Provisioned {cfg['provisioned_at']} (UTC) to account **{cfg['account_number']}**."
    )
    st.caption(
        f"Effective {cfg['effective_from']} → {cfg['effective_to']} · "
        f"{cfg['currency']} · price book {cfg['price_book_date']}"
    )

    tab_rates, tab_preview = st.tabs(["Rate table", "Billing preview"])
    with tab_rates:
        _tab_rate_table(rec)
    with tab_preview:
        _tab_billing_preview(rec)


SCREENS = {
    "DRAFT": screen_draft,
    "AGREEMENT_READY": screen_agreement_ready,
    "PENDING_SIGNATURE": screen_pending_signature,
    "SIGNED": screen_signed,
    "ACTIVE": screen_active,
}


# --------------------------------------------------------------- entrypoint
def main() -> None:
    render_sidebar()

    active_id = st.session_state.get("active_id")
    rec = store.get(active_id) if active_id else None

    if rec is None:
        st.title("Private Pricing Customer Onboarding")
        st.write(
            "Sales portal for onboarding a customer onto a private (committed-spend) "
            "pricing agreement."
        )
        st.info("Create a new onboarding from the sidebar, or open one from the tracker.")
        return

    a = rec["agreement"]
    st.title(f"{a['company_name'] or 'New onboarding'} · {rec['id']}")
    render_progress(rec["status"])
    st.divider()
    SCREENS[rec["status"]](rec)
    render_history(rec)


main()
