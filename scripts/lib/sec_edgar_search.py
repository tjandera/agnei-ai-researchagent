"""
SEC EDGAR connector - official company filings, no auth required, free.

The highest-signal source in the set: 8-K material events, 10-Q/10-K reports,
and Form 4 insider trades straight from the SEC. Resolves a ticker to its CIK
via the public company map (cached for the process), then reads the company's
recent submissions. The SEC requires a descriptive User-Agent on every request.
Symbols with no CIK (e.g. crypto) return [].
"""

import requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}"

# SEC asks for a UA identifying the requester with contact info.
HEADERS = {"User-Agent": "Agnes Finance Research admin@agnesfinance.app"}

# High-signal forms only, with reader-friendly labels.
FORM_LABELS = {
    "8-K": "Material event",
    "10-Q": "Quarterly report",
    "10-K": "Annual report",
    "4": "Insider trade",
    "SC 13D": "Activist stake",
    "SC 13G": "Passive stake",
    "DEF 14A": "Proxy statement",
}

_TICKER_CACHE: Optional[Dict[str, int]] = None


def search_sec_filings(symbol: str, limit: int = 8, days: int = 90) -> List[Dict]:
    """Fetch recent high-signal SEC filings for a ticker.

    Returns a list of dicts: {source, title, url, form, filed, age, age_days}.
    Returns [] when the symbol has no CIK (e.g. crypto) or on any error.
    """
    cik = _cik_for(symbol)
    if cik is None:
        return []

    try:
        resp = requests.get(SUBMISSIONS_URL.format(cik=cik), headers=HEADERS, timeout=12)
        resp.raise_for_status()
        recent = (resp.json().get("filings") or {}).get("recent") or {}
    except Exception as e:
        return [{"error": str(e), "source": "sec"}]

    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []
    now = datetime.now(timezone.utc)

    out: List[Dict[str, Any]] = []
    insider_seen = 0  # Form 4s are filed in volume; cap them so 8-K/10-Q surface.
    for i, form in enumerate(forms):
        if form not in FORM_LABELS:
            continue
        if form == "4":
            if insider_seen >= 2:
                continue
            insider_seen += 1
        filed = dates[i] if i < len(dates) else ""
        age_days = _age_days(filed, now)
        if age_days is not None and age_days > days:
            continue

        accession = (accessions[i] if i < len(accessions) else "").replace("-", "")
        doc = docs[i] if i < len(docs) else ""
        url = (
            ARCHIVE_URL.format(cik=cik, accession=accession, doc=doc)
            if accession and doc
            else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}"
        )

        out.append({
            "source": "sec",
            "title": f"{form} — {FORM_LABELS[form]}",
            "url": url,
            "form": form,
            "filed": filed,
            "age": _relative_age(age_days),
            "age_days": round(age_days, 2) if age_days is not None else None,
        })
        if len(out) >= limit:
            break

    return out


def _cik_for(symbol: str) -> Optional[int]:
    """Resolve a ticker to its CIK using the cached SEC company map."""
    global _TICKER_CACHE
    sym = (symbol or "").upper().strip()
    if not sym or "-" in sym:  # crypto / FX style symbols have no CIK
        return None

    if _TICKER_CACHE is None:
        try:
            resp = requests.get(TICKERS_URL, headers=HEADERS, timeout=12)
            resp.raise_for_status()
            rows = resp.json().values()
            _TICKER_CACHE = {
                str(r.get("ticker", "")).upper(): int(r.get("cik_str"))
                for r in rows if r.get("ticker")
            }
        except Exception:
            _TICKER_CACHE = {}

    return _TICKER_CACHE.get(sym)


def _age_days(filed: Optional[str], now: datetime) -> Optional[float]:
    if not filed:
        return None
    try:
        dt = datetime.fromisoformat(filed).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (now - dt).total_seconds() / 86400


def _relative_age(days: Optional[float]) -> str:
    if days is None:
        return ""
    if days < 1:
        return "today"
    if days < 2:
        return "1d ago"
    return f"{int(days)}d ago"
