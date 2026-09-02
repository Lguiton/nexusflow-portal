"""
REP-01: real CSV/PDF export of the stakeholder report.

Before this, /api/v1/reports/stakeholder always returned a JSON payload
only -- nothing a stakeholder could download and hand to someone, print,
or attach to an email. Both renderers below take the exact same dict
generate_stakeholder_report() already returns (see
backend/agents/report_generator.py's docstrings for its shape:
{"agent", "status", "summary_metrics", "executive_sections"}) -- there is
no separate code path that could drift from what the JSON endpoint shows,
and both renderers handle every real status that function can return
(GENERATED, FALLBACK, NO_DATA, ERROR) without special-casing, including
the ERROR state's None-valued summary_metrics.

Scope, stated plainly, same as everywhere else in this audit: this is the
export half of REP-01 only. "Secure sharing and expiration" (the other
half of REP-01's own title -- a shareable, time-limited external link)
is NOT built here -- it needs a real policy decision (how long does a
link live, can it be revoked, is it authenticated or anonymous) that
belongs to the founder, not picked unilaterally. What ships here is a
tenant downloading their own report through their own authenticated
session, nothing more.
"""
import csv
import io
from datetime import datetime, timezone
from typing import Any, Dict

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

REPORT_TITLE = "Eivanta Stakeholder Report"


def _fmt_money(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_int(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "N/A"


def _metric_rows(report: Dict[str, Any]) -> list:
    """Flattens summary_metrics into (label, value) pairs shared by both
    renderers -- the one place that knows how to read this dict's shape,
    so CSV and PDF can never disagree with each other about it."""
    m = report.get("summary_metrics") or {}
    top_category = m.get("top_category")
    rows = [
        ("Total Revenue", _fmt_money(m.get("total_revenue"))),
        ("Total Expenses", _fmt_money(m.get("total_expenses"))),
        ("Net Income", _fmt_money(m.get("net_income"))),
        ("Records Audited", _fmt_int(m.get("records_audited"))),
    ]
    if top_category:
        rows.append(("Top Category", str(top_category.get("category", "N/A"))))
        rows.append(("Top Category Revenue", _fmt_money(top_category.get("revenue"))))
        rows.append(("Top Category % of Total Revenue", _fmt_pct(top_category.get("pct_of_total_revenue"))))
    else:
        rows.append(("Top Category", "N/A"))
    rows.append(("Revenue Trend", _fmt_pct(m.get("revenue_trend_pct"))))
    return rows


def render_report_csv(report: Dict[str, Any]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([REPORT_TITLE])
    writer.writerow(["Status", report.get("status", "UNKNOWN")])
    writer.writerow(["Generated", datetime.now(timezone.utc).isoformat()])
    writer.writerow([])

    writer.writerow(["Metric", "Value"])
    for label, value in _metric_rows(report):
        writer.writerow([label, value])
    writer.writerow([])

    writer.writerow(["Section", "Summary"])
    for section in report.get("executive_sections") or []:
        writer.writerow([section.get("title", ""), section.get("summary", "")])

    return buf.getvalue().encode("utf-8")


def render_report_pdf(report: Dict[str, Any], client_id: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    meta_style = ParagraphStyle("Meta", parent=styles["Normal"], textColor=colors.grey, spaceAfter=12)
    heading_style = ParagraphStyle("SectionHeading", parent=styles["Heading2"], spaceBefore=14, spaceAfter=4)
    body_style = ParagraphStyle("SectionBody", parent=styles["Normal"], spaceAfter=8, leading=14)

    story = [
        Paragraph(REPORT_TITLE, title_style),
        Paragraph(
            f"Tenant: {client_id} &nbsp;|&nbsp; Status: {report.get('status', 'UNKNOWN')} &nbsp;|&nbsp; "
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            meta_style,
        ),
        Spacer(1, 8),
    ]

    table_data = [["Metric", "Value"]] + [[label, value] for label, value in _metric_rows(report)]
    table = Table(table_data, colWidths=[2.8 * inch, 2.8 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    story.append(Spacer(1, 16))

    for section in report.get("executive_sections") or []:
        story.append(Paragraph(str(section.get("title", "")), heading_style))
        story.append(Paragraph(str(section.get("summary", "")), body_style))

    doc.build(story)
    return buf.getvalue()
