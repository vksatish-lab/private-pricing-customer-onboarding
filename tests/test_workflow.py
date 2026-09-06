"""State-machine tests. Run from the repo root:  python -m unittest

No third-party test dependency -- stdlib unittest only.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from workflow import (  # noqa: E402
    WorkflowError,
    apply,
    compute_end_date,
    new_record,
    validate_agreement,
)


def _valid_agreement_record() -> dict:
    rec = new_record()
    rec["agreement"].update({
        "company_name": "Northwind Corp",
        "account_number": "ACME-100428",
        "annual_commitment_usd": 2_000_000,
        "term_months": 36,
        "discount_model": "cross_service",
        "cross_service_pct": 12.0,
    })
    return rec


class EndDate(unittest.TestCase):
    def test_derivation(self):
        self.assertEqual(compute_end_date("2026-06-01", 12), "2027-05-31")
        self.assertEqual(compute_end_date("2026-02-01", 36), "2029-01-31")
        self.assertEqual(compute_end_date("2026-03-31", 12), "2027-03-30")


class NewRecord(unittest.TestCase):
    def test_shape(self):
        r = new_record()
        self.assertEqual(r["status"], "DRAFT")
        self.assertIn(r["agreement"]["customer_name"], ("John Doe", "Jane Doe"))
        self.assertTrue(r["id"].startswith("ONB-"))
        self.assertEqual(len(r["history"]), 1)


class Validation(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(validate_agreement(_valid_agreement_record()["agreement"]), [])

    def test_missing_company(self):
        a = _valid_agreement_record()["agreement"]
        a["company_name"] = "   "
        self.assertIn("Company name is required.", validate_agreement(a))

    def test_missing_account_number(self):
        a = _valid_agreement_record()["agreement"]
        a["account_number"] = ""
        self.assertTrue(any("Account number is required" in e for e in validate_agreement(a)))

    def test_commitment_not_positive(self):
        a = _valid_agreement_record()["agreement"]
        a["annual_commitment_usd"] = 0
        self.assertTrue(any("greater than 0" in e for e in validate_agreement(a)))

    def test_cross_pct_range(self):
        a = _valid_agreement_record()["agreement"]
        a["cross_service_pct"] = 140
        self.assertTrue(any("between 0 and 100" in e for e in validate_agreement(a)))

    def test_per_service_requires_a_row(self):
        a = _valid_agreement_record()["agreement"]
        a["discount_model"] = "per_service"
        self.assertIn("Add at least one per-service discount.", validate_agreement(a))

    def test_per_service_unknown_and_duplicate(self):
        a = _valid_agreement_record()["agreement"]
        a["discount_model"] = "per_service"
        a["per_service"] = [
            {"service": "Claude API", "pct": 10},
            {"service": "Claude API", "pct": 15},
            {"service": "Nonexistent", "pct": 5},
        ]
        errs = validate_agreement(a)
        self.assertTrue(any("more than once" in e for e in errs))
        self.assertTrue(any("Unknown service" in e for e in errs))


class Transitions(unittest.TestCase):
    def test_happy_path(self):
        r = _valid_agreement_record()
        r = apply(r, "generate_agreement")
        self.assertEqual(r["status"], "AGREEMENT_READY")
        self.assertIsNotNone(r["document"])

        r = apply(r, "send_for_signature")
        self.assertEqual(r["status"], "PENDING_SIGNATURE")
        self.assertIsNotNone(r["sent_for_signature_at"])

        r = apply(r, "mark_signed")
        self.assertEqual(r["status"], "SIGNED")
        self.assertEqual(r["signature"]["signer_name"], r["agreement"]["customer_name"])

        actions = [h["action"] for h in r["history"]]
        self.assertEqual(
            actions, ["create", "generate_agreement", "send_for_signature", "mark_signed"]
        )

    def test_generate_blocked_by_validation(self):
        r = new_record()  # company_name empty, commitment 0
        with self.assertRaises(WorkflowError):
            apply(r, "generate_agreement")

    def test_illegal_transition(self):
        r = _valid_agreement_record()
        with self.assertRaises(WorkflowError):
            apply(r, "mark_signed")  # still DRAFT

    def test_edit_after_generate_reverts_to_draft(self):
        r = apply(_valid_agreement_record(), "generate_agreement")
        r = apply(r, "update_agreement", {"agreement": {"annual_commitment_usd": 3_000_000}})
        self.assertEqual(r["status"], "DRAFT")
        self.assertIsNone(r["document"])
        self.assertEqual(r["history"][-1]["action"], "revise")

    def test_locked_after_sent(self):
        r = apply(_valid_agreement_record(), "generate_agreement")
        r = apply(r, "send_for_signature")
        with self.assertRaises(WorkflowError):
            apply(r, "update_agreement", {"agreement": {"company_name": "New Name"}})

    def test_provision_billing(self):
        r = _valid_agreement_record()
        for act in ("generate_agreement", "send_for_signature", "mark_signed", "provision_billing"):
            r = apply(r, act)
        self.assertEqual(r["status"], "ACTIVE")
        cfg = r["billing_config"]
        self.assertEqual(cfg["kind"], "private-pricing-billing-config")
        self.assertEqual(cfg["account_number"], "ACME-100428")
        self.assertIsNotNone(cfg["provisioned_at"])
        self.assertEqual(r["history"][-1]["action"], "provision_billing")

    def test_provision_requires_signed(self):
        r = apply(_valid_agreement_record(), "generate_agreement")
        with self.assertRaises(WorkflowError):
            apply(r, "provision_billing")

    def test_apply_does_not_mutate_input(self):
        r = _valid_agreement_record()
        before = r["status"]
        apply(r, "generate_agreement")
        self.assertEqual(r["status"], before)


if __name__ == "__main__":
    unittest.main()
