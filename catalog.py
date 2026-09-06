"""The public product catalog + list-price book.

One shared catalog for everyone. Private-pricing customers get a discount *policy*
applied against this catalog at billing time -- we never fork it per customer.

Step 1 (authoring) only needs SERVICE_NAMES for the per-service discount dropdown.
The SKU-level detail is here for the billing-setup step (not built yet).
"""
from __future__ import annotations

PRICE_BOOK_DATE = "2026-08-01"
CURRENCY = "USD"

# priceSource: "public"      -> Anthropic published list price (per 1M tokens)
#              "illustrative" -> plausible placeholder so the catalog is complete
_MODELS = [
    # (code, display, input $/MTok, output $/MTok)
    ("OPUS-5", "Claude Opus 5", 5.0, 25.0),
    ("SONNET-5", "Claude Sonnet 5", 3.0, 15.0),
    ("HAIKU-4-5", "Claude Haiku 4.5", 1.0, 5.0),
]
_LINES = [
    ("INPUT", "input tokens", 1.0),
    ("OUTPUT", "output tokens", None),  # uses the model's output price
    ("CACHE-WRITE-5M", "cache write (5-min)", 1.25),
    ("CACHE-WRITE-1H", "cache write (1-hour)", 2.0),
    ("CACHE-READ", "cache read", 0.1),
]


def _round4(x: float) -> float:
    return round(x, 4)


def _build_skus() -> list[dict]:
    skus: list[dict] = []
    for code, name, in_price, out_price in _MODELS:
        for line_code, line_name, mult in _LINES:
            price = out_price if line_code == "OUTPUT" else _round4(in_price * mult)
            skus.append({
                "id": f"API-{code}-{line_code}",
                "service": "Claude API",
                "display_name": f"{name} — {line_name}",
                "unit": "per_mtok",
                "list_price": price,
                "price_source": "public",
            })
    # Batch (50% of standard, input/output only)
    for code, name, in_price, out_price in _MODELS[:2]:
        skus.append({"id": f"API-{code}-INPUT-BATCH", "service": "Claude API",
                     "display_name": f"{name} — input (Batch)", "unit": "per_mtok",
                     "list_price": _round4(in_price * 0.5), "price_source": "public"})
        skus.append({"id": f"API-{code}-OUTPUT-BATCH", "service": "Claude API",
                     "display_name": f"{name} — output (Batch)", "unit": "per_mtok",
                     "list_price": _round4(out_price * 0.5), "price_source": "public"})

    skus += [
        {"id": "CLAUDE-CODE-USAGE", "service": "Claude Code", "display_name": "Claude Code — blended usage",
         "unit": "per_mtok", "list_price": 6.0, "price_source": "illustrative"},
        {"id": "CLAUDE-CODE-SEAT", "service": "Claude Code", "display_name": "Claude Code — seat",
         "unit": "per_seat_month", "list_price": 30.0, "price_source": "illustrative"},
        {"id": "CLAUDE-TEAM-SEAT", "service": "Claude for Work", "display_name": "Claude for Work — Team seat",
         "unit": "per_seat_month", "list_price": 30.0, "price_source": "illustrative"},
        {"id": "CLAUDE-ENTERPRISE-SEAT", "service": "Claude for Work", "display_name": "Claude for Work — Enterprise seat",
         "unit": "per_seat_month", "list_price": 60.0, "price_source": "illustrative"},
        {"id": "TOOL-WEB-SEARCH", "service": "Server Tools", "display_name": "Web search tool",
         "unit": "per_1k_calls", "list_price": 10.0, "price_source": "illustrative"},
        {"id": "TOOL-CODE-EXEC", "service": "Server Tools", "display_name": "Code execution tool",
         "unit": "per_1k_calls", "list_price": 5.0, "price_source": "illustrative"},
    ]
    return skus


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
