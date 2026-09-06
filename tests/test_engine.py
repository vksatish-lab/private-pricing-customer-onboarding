"""Billing engine tests.  python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from catalog import CATALOG  # noqa: E402
from engine import (  # noqa: E402
    build_billing_config,
    build_invoice,
    match_sku,
    rate_table_to_csv,
    resolve_rate_table,
    sample_usage,
)
from workflow import apply, new_record  # noqa: E402


def _signed_record(**agreement) -> dict:
    rec = new_record()
    rec["agreement"].update({
        "company_name": "Globex Corporation",
        "account_number": "GLBX-004417",
        "annual_commitment_usd": 5_000_000,
        "term_months": 24,
        "discount_model": "cross_service",
        "cross_service_pct": 12,
        "per_service": [],
    })
    rec["agreement"].update(agreement)
    rec = apply(rec, "generate_agreement")
    rec = apply(rec, "send_for_signature")
    return apply(rec, "mark_signed")


def _sku(**kw) -> dict:
    base = {"id": "X", "service_code": "CLAUDE_API", "unit": "per_mtok", "price_source": "public"}
    base.update(kw)
    return base


class MatchExpr(unittest.TestCase):
    def test_leaf_eq(self):
        self.assertTrue(match_sku({"field": "service_code", "op": "eq", "value": "CLAUDE_CODE"},
                                  _sku(service_code="CLAUDE_CODE")))
        self.assertFalse(match_sku({"field": "service_code", "op": "eq", "value": "CLAUDE_CODE"},
                                   _sku(service_code="CLAUDE_API")))

    def test_leaf_in(self):
        expr = {"field": "unit", "op": "in", "value": ["per_seat_month", "per_1k_calls"]}
        self.assertTrue(match_sku(expr, _sku(unit="per_1k_calls")))
        self.assertFalse(match_sku(expr, _sku(unit="per_mtok")))

    def test_all_any(self):
        s = _sku(service_code="CLAUDE_API", unit="per_mtok")
        self.assertTrue(match_sku({"all": [
            {"field": "service_code", "op": "eq", "value": "CLAUDE_API"},
            {"field": "unit", "op": "eq", "value": "per_mtok"},
        ]}, s))
        self.assertFalse(match_sku({"all": [
            {"field": "service_code", "op": "eq", "value": "CLAUDE_API"},
            {"field": "unit", "op": "eq", "value": "per_seat_month"},
        ]}, s))
        self.assertTrue(match_sku({"any": [
            {"field": "service_code", "op": "eq", "value": "NOPE"},
            {"field": "unit", "op": "eq", "value": "per_mtok"},
        ]}, s))

    def test_bad_field_and_op(self):
        with self.assertRaises(ValueError):
            match_sku({"field": "list_price", "op": "eq", "value": 5}, _sku())
        with self.assertRaises(ValueError):
            match_sku({"field": "unit", "op": "gt", "value": "x"}, _sku())


class BuildConfig(unittest.TestCase):
    def test_cross_service_only(self):
        cfg = build_billing_config(_signed_record(discount_model="cross_service", cross_service_pct=12))
        self.assertEqual(cfg["kind"], "private-pricing-billing-config")
        self.assertEqual(cfg["cross_service_discount_pct"], 12)
        self.assertEqual(cfg["discount_rules"], [])
        self.assertEqual(cfg["account_number"], "GLBX-004417")
        self.assertIsNone(cfg["provisioned_at"])

    def test_per_service_only(self):
        cfg = build_billing_config(_signed_record(
            discount_model="per_service", cross_service_pct=0,
            per_service=[{"service": "Claude Code", "pct": 20},
                         {"service": "Claude for Work", "pct": 15}],
        ))
        self.assertIsNone(cfg["cross_service_discount_pct"])
        ids = [r["id"] for r in cfg["discount_rules"]]
        self.assertEqual(ids, ["ssd-claude-code", "ssd-claude-for-work"])
        rule = cfg["discount_rules"][0]
        self.assertEqual(rule["discount_pct"], 20)
        self.assertEqual(
            rule["match"],
            {"all": [{"field": "service_code", "op": "eq", "value": "CLAUDE_CODE"}]},
        )

    def test_both(self):
        cfg = build_billing_config(_signed_record(
            discount_model="both", cross_service_pct=12,
            per_service=[{"service": "Claude Code", "pct": 20}],
        ))
        self.assertEqual(cfg["cross_service_discount_pct"], 12)
        self.assertEqual(len(cfg["discount_rules"]), 1)


class Resolve(unittest.TestCase):
    def test_precedence_ssd_beats_csd(self):
        cfg = build_billing_config(_signed_record(
            discount_model="both", cross_service_pct=12,
            per_service=[{"service": "Claude Code", "pct": 20}],
        ))
        table = resolve_rate_table(cfg, CATALOG)
        by_id = {ln["sku_id"]: ln for ln in table["lines"]}

        cc = by_id["CLAUDE-CODE-USAGE"]
        self.assertEqual(cc["applied_rule"], "ssd-claude-code")
        self.assertEqual(cc["discount_pct"], 20)
        self.assertEqual(cc["effective_price"], round(6.0 * 0.8, 4))

        api = by_id["API-OPUS-5-INPUT"]
        self.assertEqual(api["applied_rule"], "cross_service")
        self.assertEqual(api["discount_pct"], 12)
        self.assertEqual(api["effective_price"], round(5.0 * 0.88, 4))

    def test_uncovered_skus_at_list(self):
        cfg = build_billing_config(_signed_record(
            discount_model="per_service", cross_service_pct=0,
            per_service=[{"service": "Claude API", "pct": 10}],
        ))
        table = resolve_rate_table(cfg, CATALOG)
        by_id = {ln["sku_id"]: ln for ln in table["lines"]}
        tool = by_id["TOOL-WEB-SEARCH"]
        self.assertIsNone(tool["applied_rule"])
        self.assertEqual(tool["discount_pct"], 0)
        self.assertEqual(tool["effective_price"], tool["list_price"])
        self.assertIn("TOOL-WEB-SEARCH", table["summary"]["skus_at_list_ids"])

    def test_summary_counts(self):
        cfg = build_billing_config(_signed_record(discount_model="cross_service", cross_service_pct=15))
        table = resolve_rate_table(cfg, CATALOG)
        self.assertEqual(table["summary"]["skus_total"], len(CATALOG["skus"]))
        self.assertEqual(table["summary"]["skus_discounted"], len(CATALOG["skus"]))
        self.assertEqual(table["summary"]["skus_at_list"], 0)

    def test_csv_shape(self):
        cfg = build_billing_config(_signed_record(discount_model="cross_service", cross_service_pct=15))
        table = resolve_rate_table(cfg, CATALOG)
        csv_text = rate_table_to_csv(table, cfg)
        lines = csv_text.strip().splitlines()
        self.assertEqual(len(lines), len(CATALOG["skus"]) + 1)
        self.assertTrue(lines[0].startswith("sku_id,service,service_code,unit,list_price"))


class Invoice(unittest.TestCase):
    def _cfg(self):
        return build_billing_config(_signed_record(
            discount_model="both", cross_service_pct=10,
            per_service=[{"service": "Claude Code", "pct": 25}],
        ))

    def test_line_math_gross_and_net(self):
        cfg = self._cfg()
        inv = build_invoice(cfg, "2026-09", {
            "API-OPUS-5-INPUT": 100,      # list 5.00, cross 10% -> net 4.50
            "CLAUDE-CODE-USAGE": 50,      # list 6.00, ssd 25%  -> net 4.50
        })
        self.assertEqual(inv["kind"], "private-pricing-invoice")
        self.assertEqual(inv["invoice_number"], f"INV-{cfg['account_number']}-2026-09")
        self.assertIsNone(inv["issued_at"])
        by_id = {ln["sku_id"]: ln for ln in inv["lines"]}
        self.assertEqual(by_id["API-OPUS-5-INPUT"]["gross_amount"], 500.0)
        self.assertEqual(by_id["API-OPUS-5-INPUT"]["amount"], 450.0)
        self.assertEqual(by_id["CLAUDE-CODE-USAGE"]["amount"], 225.0)
        self.assertEqual(inv["gross_subtotal"], 800.0)
        self.assertEqual(inv["subtotal"], 675.0)
        self.assertEqual(inv["discount_total"], 125.0)
        self.assertEqual(inv["total"], inv["subtotal"])

    def test_zero_and_unknown_usage_ignored(self):
        inv = build_invoice(self._cfg(), "2026-09", {
            "API-OPUS-5-INPUT": 0, "NOT-A-SKU": 999, "API-SONNET-5-INPUT": 10,
        })
        self.assertEqual([ln["sku_id"] for ln in inv["lines"]], ["API-SONNET-5-INPUT"])

    def test_sample_usage_produces_a_nonempty_invoice(self):
        inv = build_invoice(self._cfg(), "2026-10", sample_usage())
        self.assertGreater(len(inv["lines"]), 5)
        self.assertGreater(inv["total"], 0)
        self.assertLess(inv["total"], inv["gross_subtotal"])


if __name__ == "__main__":
    unittest.main()
