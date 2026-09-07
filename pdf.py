"""PDF renderers -- pure functions, nothing stored (regenerated on demand).

  build_agreement_pdf(record)      -- the Private Pricing Agreement:
      parties -> pricing schedule table -> boilerplate clauses -> signatures
  build_billing_preview_pdf(preview) -- a non-binding monthly billing preview:
      metadata -> line items (list / discount / net) -> list vs negotiated totals
"""
from __future__ import annotations

from fpdf import FPDF
from fpdf.fonts import FontFace

from workflow import DISCOUNT_MODEL_LABEL, STAMPED, compute_end_date

ANTHROPIC_REP = "Anthropic Authorized Signatory"


def _money(x) -> str:
    return f"US${float(x):,.0f}"


def _pct(x) -> str:
    return f"{int(round(float(x)))}%"


def _pricing_rows(record: dict) -> list[tuple[str, str]]:
    a = record["agreement"]
    end = compute_end_date(a["start_date"], a["term_months"])
    model = a["discount_model"]

    rows: list[tuple[str, str]] = [
        ("Account number", a.get("account_number") or "________________"),
        ("Effective date", a["start_date"]),
        ("Contract term", f"{a['term_months']} months"),
        ("End date", end),
        ("Currency", STAMPED["currency"]),
        ("Billing", STAMPED["billing"].capitalize()),
        ("Annual committed spend", _money(a["annual_commitment_usd"])),
        ("Discount model", DISCOUNT_MODEL_LABEL[model]),
    ]
    if model in ("cross_service", "both"):
        rows.append(("Cross-service discount", _pct(a["cross_service_pct"])))
    if model in ("per_service", "both"):
        for r in a["per_service"]:
            if r.get("service"):
                rows.append((f"{r['service']} discount", _pct(r["pct"])))
    return rows


CLAUSES = [
    (
        "Effective Date and Term",
        "This Private Pricing Agreement (the \"Agreement\") is effective as of the "
        "Effective Date set out in the Pricing Schedule and continues for the "
        "Contract Term stated therein, unless earlier terminated in accordance with "
        "the master agreement in effect between the parties (the \"Master Agreement\").",
    ),
    (
        "Committed Spend",
        "Customer commits to purchase Anthropic services with an aggregate net value "
        "not less than the Annual Committed Spend for each twelve (12) month period "
        "of the Contract Term. Usage in excess of the Annual Committed Spend in any "
        "period is billed at the applicable rates determined under this Agreement. "
        "Any shortfall against the Annual Committed Spend is due at the end of the "
        "applicable period.",
    ),
    (
        "Pricing and Discounts",
        "The discounts set out in the Pricing Schedule apply to Anthropic's "
        "then-current published list prices and are administered by Anthropic at the "
        "individual product (SKU) level. Any Anthropic service not expressly listed "
        "in the Pricing Schedule is billed at list price. List prices may change "
        "from time to time; the discount percentages in the Pricing Schedule remain "
        "fixed for the Contract Term.",
    ),
    (
        "Billing and Payment",
        "Anthropic invoices Customer in the Currency and on the billing cadence "
        "stated in the Pricing Schedule. Invoices are payable within thirty (30) "
        "days of the invoice date. Undisputed amounts not paid when due accrue "
        "interest at the lesser of 1.5% per month or the maximum rate permitted by "
        "applicable law.",
    ),
    (
        "Confidentiality",
        "The pricing, discounts and commercial terms in this Agreement are "
        "Confidential Information of both parties and may not be disclosed to any "
        "third party except as required by law or to a party's professional "
        "advisors who are bound by a duty of confidence.",
    ),
    (
        "Termination",
        "Either party may terminate this Agreement for the other party's material "
        "breach that remains uncured thirty (30) days after written notice. "
        "Termination does not relieve Customer of the obligation to pay for services "
        "rendered, or any accrued Committed Spend shortfall, through the effective "
        "date of termination.",
    ),
    (
        "Entire Agreement",
        "This Agreement, together with the Master Agreement, is the entire agreement "
        "of the parties as to its subject matter and supersedes all prior or "
        "contemporaneous proposals and communications. Any amendment must be in "
        "writing and signed by an authorized representative of each party.",
    ),
    (
        "Counterparts and Electronic Signature",
        "This Agreement may be executed in counterparts, each of which is an "
        "original and all of which together form one instrument. Signatures "
        "delivered electronically are deemed original signatures.",
    ),
]


def build_agreement_pdf(record: dict) -> bytes:
    a = record["agreement"]
    company = a["company_name"] or "________________"
    signer = a["customer_name"] or "________________"
    signature = record.get("signature")

    pdf = FPDF(format="Letter", unit="pt")
    pdf.set_auto_page_break(auto=True, margin=54)
    pdf.set_margins(54, 54, 54)
    pdf.add_page()

    def section(title: str):
        pdf.ln(7)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(20)
        pdf.cell(0, 15, title.upper(), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    def para(text: str, size: float = 9.5, gap: float = 4):
        pdf.set_font("Helvetica", "", size)
        pdf.set_text_color(35)
        pdf.multi_cell(0, size * 1.4, text, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(gap)

    # ---- title ---------------------------------------------------------------
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(15)
    pdf.cell(0, 22, "Private Pricing Agreement", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120)
    pdf.cell(0, 13, f"Agreement reference: {record['id']}", new_x="LMARGIN", new_y="NEXT")

    # ---- 1. parties -------------------------------------------------------
    section("Parties")
    para(
        "This Agreement is entered into as of the Effective Date by and between "
        "the following parties:",
        gap=8,
    )
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(20)
    pdf.cell(0, 15, "Anthropic, PBC  (\"Anthropic\")", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(35)
    pdf.cell(0, 14, f"Represented by:  ______________________________   ({ANTHROPIC_REP})",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(20)
    pdf.cell(0, 15, f"{company}  (\"Customer\")", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(35)
    pdf.cell(0, 14, f"Represented by:  {signer}   (Authorized Signatory)",
             new_x="LMARGIN", new_y="NEXT")

    # ---- 2. pricing schedule (table) -----------------------------------
    section("Pricing Schedule")
    headings = FontFace(emphasis="B", fill_color=(235, 235, 235), color=(20, 20, 20))
    with pdf.table(
        col_widths=(200, 304),
        text_align=("LEFT", "LEFT"),
        first_row_as_headings=True,
        headings_style=headings,
        line_height=16,
        width=504,
    ) as table:
        table.row(("Term", "Value"))
        for key, value in _pricing_rows(record):
            table.row((key, value))
    pdf.ln(4)
    para(
        "Discounts in the Pricing Schedule are applied against Anthropic's "
        "then-current public price book. Services not listed are billed at list price.",
        size=9,
    )

    # ---- 3. terms and conditions -------------------------------------
    section("Terms and Conditions")
    for i, (title, body) in enumerate(CLAUSES, start=1):
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(20)
        pdf.multi_cell(0, 13, f"{i}.  {title}", new_x="LMARGIN", new_y="NEXT")
        para(body, size=9, gap=5)

    # ---- 4. signatures ---------------------------------------------------
    section("Signatures")
    sig_date = signature["signed_at"][:10] if signature else "________________"
    sig_name = signature["signer_name"] if signature else signer

    pdf.set_font("Helvetica", "B", 9.5)
    pdf.set_text_color(20)
    pdf.cell(0, 13, "For Anthropic, PBC", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(35)
    for line in ("By:     ______________________________",
                 "Name:  ______________________________",
                 "Title:   ______________________________",
                 "Date:  ______________________________"):
        pdf.cell(0, 13, line, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 9.5)
    pdf.set_text_color(20)
    pdf.cell(0, 13, f"For {company}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(35)
    by_val = sig_name if signature else "______________________________"
    for line in (f"By:     {by_val}",
                 f"Name:  {sig_name}",
                 "Title:   ______________________________",
                 f"Date:  {sig_date}"):
        pdf.cell(0, 13, line, new_x="LMARGIN", new_y="NEXT")

    # ---- footer -------------------------------------------------------
    footer = f"{record['id']} - {record['status']}"
    if record.get("document"):
        footer += f" - generated {record['document']['generated_at']}"
    if record["status"] == "DRAFT":
        footer += "   DRAFT - NOT FOR EXECUTION"
    pdf.set_auto_page_break(False)  # keep the footer on the last content page
    pdf.set_y(-34)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(140)
    pdf.cell(0, 10, footer)

    return bytes(pdf.output())


# ---------------------------------------------------------------- billing-preview PDF
def _amt(x) -> str:
    return f"{float(x):,.2f}"


_LATIN1 = str.maketrans({"—": "-", "–": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "·": "-"})


def _safe(s: str) -> str:
    """Core PDF fonts are latin-1 only; fold the few unicode chars the catalog uses."""
    return str(s).translate(_LATIN1).encode("latin-1", "replace").decode("latin-1")


def build_billing_preview_pdf(preview: dict) -> bytes:
    inv = preview
    pdf = FPDF(format="Letter", unit="pt")
    pdf.set_auto_page_break(auto=True, margin=48)
    pdf.set_margins(48, 48, 48)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(15)
    pdf.cell(0, 24, "Billing Preview", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(120)
    pdf.cell(0, 12, "Non-binding estimate from entered usage. Not an invoice.",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(40)
    meta = [
        f"Reference:  {inv['preview_number']}",
        f"Account:  {inv['account_number']}    Customer:  {_safe(inv['customer'].get('company_name', ''))}",
        f"Billing period:  {inv['billing_period']}    Generated (UTC):  {inv.get('generated_at') or '-'}",
        f"Currency:  {inv['currency']}    Price book:  {inv['price_book_date']}",
    ]
    for line in meta:
        pdf.cell(0, 14, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    headings = FontFace(emphasis="B", fill_color=(235, 235, 235), color=(20, 20, 20))
    with pdf.table(
        col_widths=(168, 52, 62, 40, 62, 74),
        text_align=("LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"),
        first_row_as_headings=True,
        headings_style=headings,
        line_height=13,
        width=458,
        padding=(2, 4, 2, 4),
    ) as table:
        table.row(("Item", "Qty", "List $/u", "Disc", "Net $/u", "Amount $"))
        for ln in inv["lines"]:
            table.row((
                _safe(ln["description"]),
                f"{ln['quantity']:,g}",
                _amt(ln["list_price"]),
                f"{ln['discount_pct']}%",
                _amt(ln["unit_price"]),
                _amt(ln["amount"]),
            ))

    pdf.ln(10)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(35)

    def total_row(label: str, value: str, bold: bool = False):
        pdf.set_font("Helvetica", "B" if bold else "", 10.5 if bold else 10)
        pdf.cell(330, 16, "", new_x="RIGHT", new_y="LAST")
        pdf.cell(120, 16, label + "   ", align="R")
        pdf.cell(0, 16, f"{inv['currency']} {value}", align="R", new_x="LMARGIN", new_y="NEXT")

    total_row("At list price", _amt(inv["gross_subtotal"]))
    total_row(f"Agreement saving ({inv.get('savings_pct', 0):g}%)", f"-{_amt(inv['discount_total'])}")
    total_row("At your negotiated rates", _amt(inv["total"]), bold=True)

    pdf.set_auto_page_break(False)
    pdf.set_y(-30)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(140)
    pdf.cell(0, 10, f"{inv['preview_number']} - billing preview, non-binding")

    return bytes(pdf.output())
