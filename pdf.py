"""Render an onboarding record into a one-page Private Pricing Agreement PDF.

Pure function of the record -- we never store the PDF, we regenerate it on demand
(so it always reflects the current agreement and signature state).
"""
from __future__ import annotations

from fpdf import FPDF

from workflow import STAMPED, compute_end_date


def _money(x) -> str:
    return f"US${float(x):,.0f}"


def build_agreement_pdf(record: dict) -> bytes:
    a = record["agreement"]
    end = compute_end_date(a["start_date"], a["term_months"])
    years = int(a["term_months"]) // 12
    signed = record.get("signature")

    pdf = FPDF(format="Letter", unit="pt")
    pdf.set_auto_page_break(auto=True, margin=54)
    pdf.set_margins(54, 54, 54)
    pdf.add_page()

    def heading(text: str, size: int = 13):
        pdf.ln(8)
        pdf.set_font("Helvetica", "B", size)
        pdf.set_text_color(20)
        pdf.multi_cell(0, size * 1.4, text)
        pdf.ln(2)

    def body(text: str, size: float = 10.5):
        pdf.set_font("Helvetica", "", size)
        pdf.set_text_color(40)
        pdf.multi_cell(0, size * 1.5, text)
        pdf.ln(3)

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(15)
    pdf.multi_cell(0, 24, "Private Pricing Agreement")
    pdf.ln(2)
    body(f"Onboarding reference: {record['id']}")
    body(
        f'This Private Pricing Agreement (the "Agreement") is entered into between '
        f'Anthropic, PBC ("Anthropic") and {a["company_name"] or "________________"} '
        f'("Customer").'
    )

    heading("1. Term")
    body(
        f"Start date: {a['start_date']}\n"
        f"Term: {a['term_months']} months\n"
        f"End date: {end}\n"
        f"Currency: {STAMPED['currency']}    Billing: {STAMPED['billing']}"
    )

    heading("2. Committed spend")
    body(
        f"Customer commits to an annual committed spend of "
        f"{_money(a['annual_commitment_usd'])} for each year of the Term "
        f"(total committed value {_money(float(a['annual_commitment_usd']) * years)})."
    )

    heading("3. Pricing")
    model = a["discount_model"]
    lines: list[str] = []
    if model in ("cross_service", "both"):
        lines.append(
            f"Cross-service discount: {float(a['cross_service_pct']):g}% off Anthropic's "
            f"list prices across all services."
        )
    if model in ("per_service", "both"):
        lines.append("Service-specific discounts off list price:")
        for row in a["per_service"]:
            if row.get("service"):
                lines.append(f"      -  {row['service']}: {float(row['pct']):g}%")
    body("\n".join(lines))
    body(
        "Discounts are applied by Anthropic's billing team at the SKU level against "
        "the then-current public price book. Any Anthropic service not listed above "
        "is billed at list price."
    )

    heading("4. Signatures")
    if signed:
        body(f"Customer:  {signed['signer_name']}        Signed (UTC): {signed['signed_at']}")
    else:
        body("Customer:  ______________________________        Date: ________________")
    body("Anthropic, PBC:  ______________________________        Date: ________________")

    footer = f"{record['id']} · {record['status']}"
    if record.get("document"):
        footer += f" · generated {record['document']['generated_at']}"
    if record["status"] == "DRAFT":
        footer += "  —  DRAFT, NOT FOR EXECUTION"
    pdf.set_y(-38)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(130)
    pdf.cell(0, 10, footer)

    out = pdf.output()
    return bytes(out)
