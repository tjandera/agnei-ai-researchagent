"""
PDF report generator for Agnes Finance Research.
Produces a clean, professional one-page report using fpdf2.
"""

import io
import os
from datetime import datetime
from typing import Dict, Any, Optional

try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True
except ImportError:
    FPDF_AVAILABLE = False


def generate_pdf(
    symbol: str,
    ticker_data: Dict[str, Any],
    report_text: str,
    chart_png: Optional[bytes] = None,
) -> bytes:
    """
    Generate a PDF finance report.

    Args:
        symbol:      Ticker symbol
        ticker_data: Data from yahoo_finance.get_ticker_data()
        report_text: Agnes research synthesis text
        chart_png:   Optional PNG bytes of price chart

    Returns:
        PDF as bytes
    """
    if not FPDF_AVAILABLE:
        raise ImportError("fpdf2 not installed - run: pip install fpdf2")

    from lib.yahoo_finance import fmt_large

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── Header ──────────────────────────────────────────────────────────
    pdf.set_fill_color(12, 12, 12)
    pdf.rect(0, 0, 210, 32, "F")

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(0, 232, 122)
    pdf.set_xy(10, 8)
    pdf.cell(0, 8, "AGNES FINANCE RESEARCH", ln=False)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(136, 136, 136)
    pdf.set_xy(10, 18)
    pdf.cell(0, 6, f"Generated {datetime.now().strftime('%B %d, %Y  %H:%M')}  ·  Powered by Agnes 2.0 Flash")

    pdf.set_text_color(0, 0, 0)
    pdf.ln(22)

    # ── Ticker banner ────────────────────────────────────────────────────
    name      = ticker_data.get("name", symbol)
    price     = ticker_data.get("price")
    change    = ticker_data.get("change")
    change_pct= ticker_data.get("change_pct")

    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(40, 12, symbol.upper(), ln=False)

    if price:
        price_str = f"${price:,.2f}"
        pdf.set_font("Helvetica", "B", 20)
        pdf.cell(50, 12, price_str, ln=False)

    if change is not None and change_pct is not None:
        is_up = change >= 0
        r, g, b = (0, 160, 80) if is_up else (200, 40, 40)
        pdf.set_text_color(r, g, b)
        pdf.set_font("Helvetica", "", 13)
        sign = "+" if is_up else "-"
        pdf.cell(0, 12, f"  {sign} {abs(change):.2f}  ({abs(change_pct):.2f}%)", ln=True)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 6, name, ln=True)
    pdf.ln(4)

    # ── Key metrics grid ─────────────────────────────────────────────────
    def metric_row(label, value, label2="", value2=""):
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(30, 6, label.upper(), ln=False)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(20, 20, 20)
        pdf.cell(35, 6, str(value), ln=False)
        if label2:
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(120, 120, 120)
            pdf.cell(30, 6, label2.upper(), ln=False)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(20, 20, 20)
            pdf.cell(35, 6, str(value2), ln=True)
        else:
            pdf.ln()

    pdf.set_draw_color(220, 220, 220)
    pdf.set_line_width(0.3)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)

    def _v(key, fmt=None, fallback="N/A"):
        v = ticker_data.get(key)
        if v is None:
            return fallback
        if fmt == "money":
            return f"${v:,.2f}"
        if fmt == "large":
            return fmt_large(v)
        if fmt == "pct":
            return f"{v*100:.2f}%"
        if fmt == "ratio":
            return f"{v:.2f}x"
        return str(v)

    metric_row("Market Cap", _v("market_cap", "large"), "Volume",    _v("volume", "large"))
    metric_row("P/E Ratio",  _v("pe_ratio", "ratio"),   "Fwd P/E",   _v("forward_pe", "ratio"))
    metric_row("52W High",   _v("52w_high", "money"),   "52W Low",   _v("52w_low", "money"))
    metric_row("EPS",        _v("eps", "money"),         "Div Yield", _v("dividend_yield", "pct"))
    metric_row("Beta",       _v("beta"),                 "Avg Vol",   _v("avg_volume", "large"))
    metric_row("Sector",     _v("sector"),               "Industry",  _v("industry"))

    pdf.ln(3)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)

    # ── Chart (if provided) ──────────────────────────────────────────────
    if chart_png:
        tmp_path = "/tmp/agnes_chart.png"
        with open(tmp_path, "wb") as f:
            f.write(chart_png)
        try:
            pdf.image(tmp_path, x=10, w=190, h=60)
            pdf.ln(4)
        except Exception:
            pass

    # ── Research synthesis ───────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(0, 100, 60)
    pdf.cell(0, 7, "RESEARCH SYNTHESIS", ln=True)
    pdf.set_draw_color(0, 200, 100)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(30, 30, 30)

    # Strip markdown and sanitize to latin-1 for fpdf2 built-in fonts
    import re
    clean = re.sub(r"\*\*(.*?)\*\*", r"\1", report_text)
    clean = re.sub(r"\*(.*?)\*",     r"\1", clean)
    clean = re.sub(r"#{1,3}\s*",     "",    clean)
    clean = re.sub(r"─+",            "",    clean)
    clean = clean.replace("-", "-").replace("-", "-").replace("’", "'").replace("“", '"').replace("”", '"')
    clean = clean.encode("latin-1", errors="replace").decode("latin-1")
    clean = clean.strip()

    pdf.multi_cell(0, 4.5, clean[:3000])

    # ── Footer ───────────────────────────────────────────────────────────
    pdf.set_y(-15)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(0, 5, "Agnes Finance Research · For informational purposes only · Not financial advice", align="C")

    return pdf.output()
