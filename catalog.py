"""The public product catalog + list-price book.

One shared catalog for everyone. Private-pricing customers get a discount *policy*
applied against this catalog at billing time -- we never fork it per customer.

Step 1 (authoring) only needs SERVICE_NAMES for the per-service discount dropdown.
The SKU-level detail is here for the billing-setup step (not built yet).
"""
from __future__ import annotations

PRICE_BOOK_DATE = "2026-08-01"
CURRENCY = "USD"

# Stable machine code for each service. `match` expressions in a billing config
# target `service_code`, not the display name.
SERVICE_CODES = {
    "Claude API": "CLAUDE_API",
    "Claude Code": "CLAUDE_CODE",
    "Claude for Work": "CLAUDE_FOR_WORK",
    "Server Tools": "SERVER_TOOLS",
}

# A deliberately small catalog for the prototype -- 5 SKUs spread across the
# 4 services, enough to show per-service vs cross-service resolution and
# "uncovered -> list price".
# price_source: "public" -> Anthropic published list price ; "illustrative" -> placeholder
_SKUS = [
    ("API-OPUS-5-INPUT",       "Claude API",      "Claude Opus 5 - input tokens",   "per_mtok",        5.0,  "public"),
    ("API-OPUS-5-OUTPUT",      "Claude API",      "Claude Opus 5 - output tokens",  "per_mtok",       25.0,  "public"),
    ("CLAUDE-CODE-USAGE",      "Claude Code",     "Claude Code - blended usage",    "per_mtok",        6.0,  "illustrative"),
    ("CLAUDE-ENTERPRISE-SEAT", "Claude for Work", "Claude for Work - Enterprise seat", "per_seat_month", 60.0, "illustrative"),
    ("TOOL-WEB-SEARCH",        "Server Tools",    "Web search tool",               "per_1k_calls",   10.0,  "illustrative"),
]


def _build_skus() -> list[dict]:
    return [
        {
            "id": sku_id,
            "service": service,
            "service_code": SERVICE_CODES[service],
            "display_name": display_name,
            "unit": unit,
            "list_price": list_price,
            "price_source": price_source,
        }
        for sku_id, service, display_name, unit, list_price, price_source in _SKUS
    ]


SKUS: list[dict] = _build_skus()

SERVICE_NAMES: list[str] = ["Claude API", "Claude Code", "Claude for Work", "Server Tools"]

SERVICE_DESCRIPTIONS = {
    "Claude API": "Pay-as-you-go model inference, priced per million tokens.",
    "Claude Code": "Agentic coding tool — usage-metered and/or per seat.",
    "Claude for Work": "claude.ai Team and Enterprise seats.",
    "Server Tools": "Anthropic-hosted tools invoked from the API.",
}


def skus_for_service(service: str) -> list[dict]:
    return [s for s in SKUS if s["service"] == service]


# Bundled form the engine consumes (and tests can pass a stand-in).
CATALOG: dict = {
    "price_book_date": PRICE_BOOK_DATE,
    "currency": CURRENCY,
    "service_names": SERVICE_NAMES,
    "service_codes": SERVICE_CODES,
    "skus": SKUS,
}
