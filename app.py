"""Private Pricing Customer Onboarding -- Streamlit portal for Sales.

Flow (this build):  author agreement  ->  generate agreement  ->  send for
signature  ->  (mock) customer signs.  Billing setup comes next.

State lives in store.py (one JSON file). st.session_state only remembers which
onboarding is open. Every button calls workflow.apply(), persists, and reruns --
so the screen is always derived from the record's status.
"""
from __future__ import annotations

from datetime import date

import streamlit as st

import store
import workflow as wf
from catalog import SERVICE_NAMES
from pdf import build_agreement_pdf

st.set_page_config(page_title="Private Pricing Onboarding", page_icon="🧾", layout="wide")

MAX_PER_SERVICE_ROWS = 4
PROGRESS = ["DRAFT", "AGREEMENT_READY", "PENDING_SIGNATURE", "SIGNED"]
PROGRESS_LABEL = ["Draft", "Agreement", "Signature", "Signed"]


def _parse_date(s: str) -> date:
    y, m, d = (int(x) for x in s.split("-"))
    return date(y, m, d)


def _money(x) -> str:
    return f"${float(x):,.0f}"


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
    idx = PROGRESS.index(status)
    cols = st.columns(len(PROGRESS))
    for i, (col, label) in enumerate(zip(cols, PROGRESS_LABEL)):
        if i < idx:
            col.markdown(f"✅ ~~{label}~~")
        elif i == idx:
            col.markdown(f"🟡 **{label}**")
        else:
            col.markdown(f"⚪ {label}")


def render_history(rec: dict) -> None:
    with st.expander("History"):
        for h in rec["history"]:
            frm = h["from"] or "—"
            st.text(f"{h['at']}   {h['action']:<20}  {frm} → {h['to']}")


# --------------------------------------------------------------- agreement preview
def render_agreement_preview(rec: dict) -> None:
    a = rec["agreement"]
    end = wf.compute_end_date(a["start_date"], a["term_months"])
    years = int(a["term_months"]) // 12
    lines = [
        f"**Private Pricing Agreement — {rec['id']}**",
        f"- **Customer:** {a['company_name'] or '—'}  (signer: {a['customer_name']})",
        f"- **Term:** {a['start_date']} → {end}  ({a['term_months']} months)",
        f"- **Committed spend:** {_money(a['annual_commitment_usd'])}/yr"
        f"  ·  total {_money(float(a['annual_commitment_usd']) * years)}",
        f"- **Currency / billing:** {wf.STAMPED['currency']} · {wf.STAMPED['billing']}",
    ]
    model = a["discount_model"]
    if model in ("cross_service", "both"):
        lines.append(f"- **Cross-service discount:** {float(a['cross_service_pct']):g}%")
    if model in ("per_service", "both"):
        rows = "  ·  ".join(
            f"{r['service']} {float(r['pct']):g}%" for r in a["per_service"] if r.get("service")
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

    cross_pct = float(a.get("cross_service_pct") or 0.0)
    if model in ("cross_service", "both"):
        cross_pct = st.number_input(
            "Cross-service discount %", min_value=0.0, max_value=100.0, step=1.0,
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
                f"pct {i}", min_value=0.0, max_value=100.0, step=1.0,
                value=float(row.get("pct", 0.0)),
                key=f"ps_pct_{rid}_{i}", label_visibility="collapsed",
            )
            if svc != "—":
                per_service.append({"service": svc, "pct": pct})

    edited = {
        "customer_name": customer_name,
        "company_name": company_name,
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


def screen_signed(rec: dict) -> None:
    sig = rec["signature"]
    st.subheader("4 · Signed")
    st.success(f"✅  Signed by **{sig['signer_name']}** on {sig['signed_at']} (UTC).")
    render_agreement_preview(rec)
    download_pdf_button(rec, "⬇  Download signed agreement PDF")
    st.divider()
    st.subheader("Next: billing setup")
    st.caption(
        "Capture the negotiated rates and provision the customer for billing — "
        "resolve the discount policy against the public catalog. Built in the next iteration."
    )
    st.button("⚙  Set up billing", disabled=True)


SCREENS = {
    "DRAFT": screen_draft,
    "AGREEMENT_READY": screen_agreement_ready,
    "PENDING_SIGNATURE": screen_pending_signature,
    "SIGNED": screen_signed,
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
