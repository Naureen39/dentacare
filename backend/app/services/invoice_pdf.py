"""PDF rendering of an invoice with ReportLab (BSD licensed, pure Python)."""

from datetime import datetime
from decimal import Decimal
from html import escape
from io import BytesIO
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import Settings
from app.db.enums import InvoiceStatus
from app.schemas.billing import InvoiceOut

NAVY = colors.HexColor("#0B2545")
TEAL = colors.HexColor("#13A3A1")
MINT = colors.HexColor("#E8F6F5")
SLATE = colors.HexColor("#475569")

METHOD_LABELS = {
    "card": "Card (sandbox)",
    "cash": "Cash",
    "bank_transfer": "Bank transfer",
    "insurance": "Insurance",
}
STATUS_LABELS = {
    InvoiceStatus.DRAFT: "DRAFT",
    InvoiceStatus.ISSUED: "ISSUED",
    InvoiceStatus.PARTIALLY_PAID: "PARTIALLY PAID",
    InvoiceStatus.PAID: "PAID",
    InvoiceStatus.VOID: "VOID",
}


def format_money(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _text(value: str) -> str:
    return escape(value, quote=False)


def render_invoice_pdf(
    invoice: InvoiceOut,
    settings: Settings,
    *,
    service_date: datetime | None = None,
    dentist_name: str | None = None,
    bill_to_email: str | None = None,
) -> bytes:
    tz = ZoneInfo(settings.clinic_tz)
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "body", parent=styles["BodyText"], fontSize=9.5, leading=13, textColor=colors.black
    )
    muted = ParagraphStyle("muted", parent=body, textColor=SLATE, fontSize=8.5)
    title = ParagraphStyle(
        "title", parent=styles["Title"], textColor=NAVY, alignment=0, fontSize=22
    )
    heading = ParagraphStyle(
        "heading", parent=body, textColor=NAVY, fontName="Helvetica-Bold", fontSize=10
    )
    right = ParagraphStyle("right", parent=body, alignment=2)

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"Invoice {invoice.display_number}",
        author=settings.clinic_name,
    )
    story: list[object] = []

    header = Table(
        [
            [
                [
                    Paragraph(_text(settings.clinic_name), title),
                    Paragraph(_text(settings.clinic_address), muted),
                    Paragraph(_text(f"{settings.clinic_phone}  |  {settings.clinic_email}"), muted),
                ],
                [
                    Paragraph(
                        "<b>INVOICE</b>",
                        ParagraphStyle("t", parent=right, fontSize=14, textColor=TEAL),
                    ),
                    Paragraph(
                        _text(invoice.display_number),
                        ParagraphStyle("n", parent=right, fontSize=12, fontName="Helvetica-Bold"),
                    ),
                    Paragraph(
                        _text(STATUS_LABELS[invoice.status]),
                        ParagraphStyle(
                            "s", parent=right, textColor=NAVY, fontName="Helvetica-Bold"
                        ),
                    ),
                ],
            ]
        ],
        colWidths=[110 * mm, 64 * mm],
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 1, TEAL),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story += [header, Spacer(1, 6 * mm)]

    issued = invoice.issued_at.astimezone(tz).strftime("%B %d, %Y")
    details = [
        [Paragraph("Billed to", heading), Paragraph("Invoice details", heading)],
        [
            [Paragraph(_text(invoice.patient_name), body)]
            + ([Paragraph(_text(bill_to_email), muted)] if bill_to_email else []),
            [
                Paragraph(f"Issue date: {issued}", body),
                *(
                    [
                        Paragraph(
                            f"Date of service: {service_date.astimezone(tz).strftime('%B %d, %Y')}",
                            body,
                        )
                    ]
                    if service_date
                    else []
                ),
                *([Paragraph(_text(f"Provider: {dentist_name}"), body)] if dentist_name else []),
            ],
        ],
    ]
    story += [Table(details, colWidths=[87 * mm, 87 * mm]), Spacer(1, 6 * mm)]

    rows: list[list[object]] = [["Description", "Qty", "Unit price", "Amount"]]
    for item in invoice.items:
        rows.append(
            [
                Paragraph(_text(item.description), body),
                str(item.qty),
                format_money(item.unit_price),
                format_money(item.amount),
            ]
        )
    items_table = Table(rows, colWidths=[96 * mm, 16 * mm, 30 * mm, 32 * mm], repeatRows=1)
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, MINT]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story += [items_table, Spacer(1, 4 * mm)]

    summary: list[list[str]] = [["Subtotal", format_money(invoice.subtotal)]]
    if invoice.discount > 0:
        label = "Discount" + (f" ({invoice.discount_reason})" if invoice.discount_reason else "")
        summary.append([label, format_money(-invoice.discount)])
    if invoice.tax > 0:
        summary.append(["Tax", format_money(invoice.tax)])
    summary.append(["Total", format_money(invoice.total)])
    if invoice.insurance_expected > 0:
        summary.append(["Expected from insurance", format_money(invoice.insurance_expected)])
        summary.append(["Patient responsibility", format_money(invoice.patient_responsibility)])
    if invoice.paid > 0:
        summary.append(["Payments received", format_money(-invoice.paid)])
    summary.append(["Balance due", format_money(invoice.balance)])
    summary_table = Table(summary, colWidths=[124 * mm, 50 * mm])
    summary_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 1, NAVY),
                ("TEXTCOLOR", (0, -1), (-1, -1), NAVY),
            ]
        )
    )
    story.append(summary_table)

    if invoice.payments:
        story += [Spacer(1, 7 * mm), Paragraph("Payments", heading), Spacer(1, 2 * mm)]
        pay_rows: list[list[str]] = [["Date", "Method", "Reference", "Amount"]]
        for payment in invoice.payments:
            method = METHOD_LABELS.get(payment.method.value, payment.method.value)
            if payment.card_last4:
                method += f" ending {payment.card_last4}"
            pay_rows.append(
                [
                    payment.paid_at.astimezone(tz).strftime("%b %d, %Y"),
                    method,
                    payment.reference or "",
                    format_money(payment.amount),
                ]
            )
        pay_table = Table(pay_rows, colWidths=[34 * mm, 60 * mm, 48 * mm, 32 * mm])
        pay_table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (3, 0), (3, -1), "RIGHT"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, SLATE),
                ]
            )
        )
        story.append(pay_table)

    if invoice.status is InvoiceStatus.VOID and invoice.void_reason:
        story += [
            Spacer(1, 6 * mm),
            Paragraph(_text(f"This invoice was voided: {invoice.void_reason}"), body),
        ]

    story += [
        Spacer(1, 12 * mm),
        Paragraph(
            "Thank you for choosing "
            + _text(settings.clinic_name)
            + ". Questions about this invoice? "
            + _text(f"Call {settings.clinic_phone} or write to {settings.clinic_email}."),
            muted,
        ),
        Spacer(1, 2 * mm),
        Paragraph(
            "Demo environment, fictional clinic. Card payments shown here are sandbox simulations.",
            muted,
        ),
    ]
    document.build(story)
    return buffer.getvalue()
