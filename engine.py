"""Billing configuration engine -- pure, no Streamlit, no I/O.

Turns a signed agreement into a `private-pricing-billing-config` JSON, and
resolves that config against the public catalog into a rate table.

The billing config stores:
  - a flat `cross_service_discount_pct` (the baseline; null if none)
  - `discount_rules`: service-specific discounts, each a `discount_pct` plus a
    `match` expression evaluated against catalog SKUs

The rate table (per-SKU discount + effective price) is DERIVED on demand from the
config + the current catalog. It is never stored -- list prices can change and
the config still resolves correctly.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from catalog import CATALOG, PRICE_BOOK_DATE, SERVICE_CODES
from workflow import STAMPED, compute_end_date

CONFIG_VERSION = "1.0"
CONFIG_KIND = "private-pricing-billing-config"

# Catalog SKU fields a `match` expression may reference.
MATCH_FIELDS = {"service_code", "id", "unit", "price_source"}


# --------------------------------------------------------------- match evaluator
def match_sku(expr: dict, sku: dict) -> bool:
    """Evaluate a match expression against one catalog SKU.

    Leaf:  {"field": <MATCH_FIELDS>, "op": "eq" | "in", "value": ...}
    Combinators:  {"all": [expr, ...]}  |  {"any": [expr, ...]}
    """
    if not isinstance(expr, dict) or not expr:
        raise ValueError(f"Invalid match expression: {expr!r}")

    if "all" in expr:
        return all(match_sku(e, sku) for e in expr["all"])
    if "any" in expr:
        return any(match_sku(e, sku) for e in expr["any"])

    field = expr.get("field")
    if field not in MATCH_FIELDS:
        raise ValueError(f"Unknown match field: {field!r}")
    op = expr.get("op", "eq")
    value = expr.get("value")
    actual = sku.get(field)

    if op == "eq":
        return actual == value
    if op == "in":
        return actual in (value or [])
    raise ValueError(f"Unknown match op: {op!r}")


# --------------------------------------------------------------- build config
def _pct_int(x) -> int:
    return int(round(float(x or 0)))


def _rule_slug(service_code: str) -> str:
    return "ssd-" + service_code.lower().replace("_", "-")


def build_billing_config(record: dict) -> dict:
    """Signed agreement record -> billing config JSON (provisioned_at left null)."""
    a = record["agreement"]
    model = a["discount_model"]
    sig = record.get("signature") or {}

    cross_pct = None
    if model in ("cross_service", "both"):
        cross_pct = _pct_int(a.get("cross_service_pct"))

    rules: list[dict] = []
    if model in ("per_service", "both"):
        for row in a.get("per_service", []):
            service = row.get("service")
            if not service:
                continue
            code = SERVICE_CODES[service]
            rules.append({
                "id": _rule_slug(code),
                "type": "service_specific_discount",
                "description": f"{service} service discount",
                "discount_pct": _pct_int(row.get("pct")),
                "match": {"all": [{"field": "service_code", "op": "eq", "value": code}]},
            })

    return {
        "kind": CONFIG_KIND,
        "version": CONFIG_VERSION,
        "onboarding_ref": record["id"],
        "account_number": a["account_number"],
        "customer": {
            "company_name": a["company_name"],
            "signer_name": sig.get("signer_name") or a["customer_name"],
        },
        "currency": STAMPED["currency"],
        "billing": STAMPED["billing"],
        "effective_from": a["start_date"],
        "effective_to": compute_end_date(a["start_date"], a["term_months"]),
        "annual_committed_spend_usd": float(a["annual_commitment_usd"]),
        "price_book_date": PRICE_BOOK_DATE,
        "provisioned_at": None,
        "cross_service_discount_pct": cross_pct,
        "discount_rules": rules,
    }


# --------------------------------------------------------------- resolve
def _round_price(x: float, unit: str) -> float:
    return round(x, 4 if unit == "per_mtok" else 2)


def resolve_rate_table(config: dict, catalog: dict | None = None) -> dict:
    """Config + catalog -> per-SKU discount and effective price.

    Per SKU: the first matching service-specific rule wins; else the flat
    cross-service discount if set; else list price.
    """
    catalog = catalog or CATALOG
    cross_pct = config.get("cross_service_discount_pct")
    rules = config.get("discount_rules", [])

    lines: list[dict] = []
    discounted = 0
    at_list_ids: list[str] = []

    for sku in catalog["skus"]:
        applied_rule = None
        pct = 0
        for rule in rules:
            if match_sku(rule["match"], sku):
                applied_rule = rule["id"]
                pct = rule["discount_pct"]
                break
        if applied_rule is None and cross_pct is not None:
            applied_rule = "cross_service"
            pct = cross_pct

        if pct > 0:
            discounted += 1
        else:
            at_list_ids.append(sku["id"])

        lines.append({
            "sku_id": sku["id"],
            "service": sku["service"],
            "service_code": sku["service_code"],
            "unit": sku["unit"],
            "list_price": sku["list_price"],
            "applied_rule": applied_rule,
            "discount_pct": pct,
            "effective_price": _round_price(sku["list_price"] * (1 - pct / 100), sku["unit"]),
        })

    return {
        "lines": lines,
        "summary": {
            "skus_total": len(lines),
            "skus_discounted": discounted,
            "skus_at_list": len(at_list_ids),
            "skus_at_list_ids": at_list_ids,
        },
    }


def rate_table_to_csv(table: dict, config: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "sku_id", "service", "service_code", "unit", "list_price", "discount_pct",
        "effective_price", "applied_rule", "account_number", "effective_from", "effective_to",
    ])
    for ln in table["lines"]:
        w.writerow([
            ln["sku_id"], ln["service"], ln["service_code"], ln["unit"], ln["list_price"],
            ln["discount_pct"], ln["effective_price"], ln["applied_rule"] or "list",
            config["account_number"], config["effective_from"], config["effective_to"],
        ])
    return buf.getvalue()


def stamp_provisioned(config: dict) -> dict:
    config = dict(config)
    config["provisioned_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return config
