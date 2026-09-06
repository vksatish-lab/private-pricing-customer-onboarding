"""The onboarding workflow: a small, pure state machine.

An onboarding is a *record* that carries its state as it moves through the steps.
`apply(record, action, payload)` is the only way state changes -- it checks the
transition is legal, runs the guard, mutates a copy, appends to the history log,
and returns the new record. No I/O, no Streamlit. Persistence lives in store.py.

States (this build):  DRAFT -> AGREEMENT_READY -> PENDING_SIGNATURE -> SIGNED
Billing setup (-> ACTIVE) comes later.
"""
from __future__ import annotations

import json
import random
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from catalog import SERVICE_NAMES

STATUSES = ["DRAFT", "AGREEMENT_READY", "PENDING_SIGNATURE", "SIGNED"]

STATUS_LABEL = {
    "DRAFT": "Draft",
    "AGREEMENT_READY": "Agreement ready",
    "PENDING_SIGNATURE": "Pending signature",
    "SIGNED": "Signed",
}

# action -> (required_from_status, resulting_status)
TRANSITIONS = {
    "generate_agreement": ("DRAFT", "AGREEMENT_READY"),
    "send_for_signature": ("AGREEMENT_READY", "PENDING_SIGNATURE"),
    "mark_signed": ("PENDING_SIGNATURE", "SIGNED"),
}

DISCOUNT_MODELS = ["cross_service", "per_service", "both"]
DISCOUNT_MODEL_LABEL = {
    "cross_service": "Cross-service",
    "per_service": "Per-service",
    "both": "Both (baseline + per-service)",
}
TERM_MONTHS = [12, 24, 36]
RANDOM_NAMES = ["John Doe", "Jane Doe"]

# Agreement fields the system stamps rather than Sales entering them.
STAMPED = {"currency": "USD", "billing": "monthly in arrears"}


class WorkflowError(Exception):
    """Raised when a transition is illegal or its guard fails."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _deepcopy(record: dict) -> dict:
    return json.loads(json.dumps(record))


def new_record() -> dict:
    rid = "ONB-" + uuid.uuid4().hex[:8].upper()
    ts = _now()
    return {
        "id": rid,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "agreement": {
            "customer_name": random.choice(RANDOM_NAMES),
            "company_name": "",
            "account_number": "",  # billing account the discount applies to
            "start_date": date.today().isoformat(),
            "term_months": 12,
            "annual_commitment_usd": 0.0,
            "discount_model": "cross_service",
            "cross_service_pct": 10,
            "per_service": [],  # [{"service": str, "pct": float}]
        },
        "document": None,             # {"generated_at": iso}
        "sent_for_signature_at": None,
        "signature": None,            # {"signer_name": str, "signed_at": iso}
        "history": [{"at": ts, "action": "create", "from": None, "to": "DRAFT"}],
    }


def compute_end_date(start_iso: str, term_months: int) -> str:
    """start + term_months, minus one day. 2026-06-01 + 12mo -> 2027-05-31."""
    y, m, d = (int(x) for x in start_iso.split("-"))
    total = (y * 12 + (m - 1)) + int(term_months)
    ny, nm = divmod(total, 12)
    nm += 1
    d = min(d, monthrange(ny, nm)[1])
    return (date(ny, nm, d) - timedelta(days=1)).isoformat()


def validate_agreement(a: dict) -> list[str]:
    """Return a list of human-readable problems. Empty list == ready to generate."""
    errs: list[str] = []

    if not str(a.get("customer_name", "")).strip():
        errs.append("Customer name is required.")
    if not str(a.get("company_name", "")).strip():
        errs.append("Company name is required.")
    if not str(a.get("account_number", "")).strip():
        errs.append("Account number is required (the billing account the discount applies to).")

    try:
        commit = float(a.get("annual_commitment_usd") or 0)
    except (TypeError, ValueError):
        commit = 0.0
    if commit <= 0:
        errs.append("Annual committed spend must be greater than 0.")

    if a.get("term_months") not in TERM_MONTHS:
        errs.append("Term length must be 12, 24, or 36 months.")

    model = a.get("discount_model")
    if model not in DISCOUNT_MODELS:
        errs.append("Choose a discount model.")
        return errs

    wants_cross = model in ("cross_service", "both")
    wants_per = model in ("per_service", "both")

    if wants_cross:
        p = a.get("cross_service_pct")
        if p is None or not (0 <= float(p) <= 100):
            errs.append("Cross-service discount must be between 0 and 100%.")

    rows = [r for r in a.get("per_service", []) if r.get("service")]
    if wants_per:
        if not rows:
            errs.append("Add at least one per-service discount.")
        seen: set[str] = set()
        for r in rows:
            svc = r["service"]
            if svc not in SERVICE_NAMES:
                errs.append(f"Unknown service: {svc}.")
            if svc in seen:
                errs.append(f"{svc} is listed more than once.")
            seen.add(svc)
            p = r.get("pct")
            if p is None or not (0 <= float(p) <= 100):
                errs.append(f"{svc}: discount must be between 0 and 100%.")

    return errs


def apply(record: dict, action: str, payload: dict | None = None) -> dict:
    """The single mutation path. Returns a new record; never edits in place."""
    payload = payload or {}
    rec = _deepcopy(record)
    status = rec["status"]

    # --- editing the agreement (not a state transition, but guarded) -----------
    if action == "update_agreement":
        if status not in ("DRAFT", "AGREEMENT_READY"):
            raise WorkflowError("The agreement is locked once it has been sent for signature.")
        rec["agreement"].update(payload.get("agreement", {}))
        if status == "AGREEMENT_READY":
            # any edit invalidates the generated document -- back to Draft
            rec["status"] = "DRAFT"
            rec["document"] = None
            rec["history"].append(
                {"at": _now(), "action": "revise", "from": "AGREEMENT_READY", "to": "DRAFT"}
            )
        rec["updated_at"] = _now()
        return rec

    # --- state transitions ---------------------------------------------------
    if action not in TRANSITIONS:
        raise WorkflowError(f"Unknown action: {action!r}")

    src, dst = TRANSITIONS[action]
    if status != src:
        raise WorkflowError(
            f"Cannot '{action}' from '{STATUS_LABEL.get(status, status)}'."
        )

    if action == "generate_agreement":
        problems = validate_agreement(rec["agreement"])
        if problems:
            raise WorkflowError("Fix these before generating:\n- " + "\n- ".join(problems))
        rec["document"] = {"generated_at": _now()}

    elif action == "send_for_signature":
        if not rec.get("document"):
            raise WorkflowError("Generate the agreement before sending it for signature.")
        rec["sent_for_signature_at"] = _now()

    elif action == "mark_signed":
        rec["signature"] = {
            "signer_name": payload.get("signer_name") or rec["agreement"]["customer_name"],
            "signed_at": _now(),
        }

    rec["status"] = dst
    rec["updated_at"] = _now()
    rec["history"].append({"at": _now(), "action": action, "from": src, "to": dst})
    return rec
