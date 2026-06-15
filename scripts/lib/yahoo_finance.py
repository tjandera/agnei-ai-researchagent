"""
Yahoo Finance connector — free, no API key required.
Provides live prices, fundamentals, and historical OHLCV data.
"""

import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional


def get_ticker_data(symbol: str, days: int = 90) -> Dict[str, Any]:
    """
    Fetch comprehensive data for a stock, ETF, or crypto ticker.

    Returns price, fundamentals, historical data, and analyst info.
    """
    t = yf.Ticker(symbol.upper())

    try:
        info = t.info
    except Exception:
        info = {}

    period = f"{min(days, 365)}d"
    try:
        hist = t.history(period=period)
    except Exception:
        hist = None

    history = []
    if hist is not None and not hist.empty:
        for date, row in hist.iterrows():
            history.append({
                "date":   date.strftime("%Y-%m-%d"),
                "open":   round(float(row.get("Open", 0)),  2),
                "high":   round(float(row.get("High", 0)),  2),
                "low":    round(float(row.get("Low", 0)),   2),
                "close":  round(float(row.get("Close", 0)), 2),
                "volume": int(row.get("Volume", 0)),
            })

    def _safe(key, default=None):
        v = info.get(key, default)
        if v is None or v != v:  # catches NaN
            return default
        return v

    price     = _safe("currentPrice") or _safe("regularMarketPrice") or _safe("navPrice")
    prev_close= _safe("regularMarketPreviousClose") or _safe("previousClose")
    change    = round(price - prev_close, 2) if price and prev_close else None
    change_pct= round((change / prev_close) * 100, 2) if change and prev_close else None

    return {
        "source":         "yahoo_finance",
        "symbol":         symbol.upper(),
        "name":           _safe("longName") or _safe("shortName", symbol.upper()),
        "price":          price,
        "change":         change,
        "change_pct":     change_pct,
        "prev_close":     prev_close,
        "open":           _safe("regularMarketOpen"),
        "day_high":       _safe("dayHigh") or _safe("regularMarketDayHigh"),
        "day_low":        _safe("dayLow")  or _safe("regularMarketDayLow"),
        "volume":         _safe("volume")  or _safe("regularMarketVolume"),
        "avg_volume":     _safe("averageVolume"),
        "market_cap":     _safe("marketCap"),
        "pe_ratio":       _safe("trailingPE"),
        "forward_pe":     _safe("forwardPE"),
        "eps":            _safe("trailingEps"),
        "dividend_yield": _safe("dividendYield"),
        "52w_high":       _safe("fiftyTwoWeekHigh"),
        "52w_low":        _safe("fiftyTwoWeekLow"),
        "beta":           _safe("beta"),
        "sector":         _safe("sector"),
        "industry":       _safe("industry"),
        "currency":       _safe("currency", "USD"),
        "exchange":       _safe("exchange"),
        "asset_type":     _safe("quoteType", "EQUITY"),
        "summary":        (_safe("longBusinessSummary") or "")[:600],
        "history":        history,
        "analyst_rating": _safe("recommendationKey"),
        "target_price":   _safe("targetMeanPrice"),
    }


def search_tickers(query: str, limit: int = 6) -> List[Dict[str, Any]]:
    """Search for ticker symbols matching a company name or keyword."""
    try:
        import requests
        resp = requests.get(
            "https://query2.finance.yahoo.com/v1/finance/search",
            params={"q": query, "quotesCount": limit, "newsCount": 0},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        resp.raise_for_status()
        quotes = resp.json().get("quotes", [])
        return [
            {
                "symbol":   q.get("symbol", ""),
                "name":     q.get("longname") or q.get("shortname", ""),
                "exchange": q.get("exchange", ""),
                "type":     q.get("quoteType", ""),
            }
            for q in quotes
            if q.get("symbol")
        ]
    except Exception as e:
        return [{"error": str(e)}]


def fmt_large(n: Optional[float]) -> str:
    """Format large numbers: 2800000000 → $2.80B"""
    if n is None:
        return "N/A"
    if abs(n) >= 1e12:
        return f"${n/1e12:.2f}T"
    if abs(n) >= 1e9:
        return f"${n/1e9:.2f}B"
    if abs(n) >= 1e6:
        return f"${n/1e6:.2f}M"
    return f"${n:,.0f}"
