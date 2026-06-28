"""
Tiny JSON persistence for the personal dashboard - holdings and notes.

Single-user, local-first: data lives in web/data/*.json. Writes are atomic
(write-temp-then-rename) and guarded by a process lock, which is enough for this
single-user app. No database, no dependencies.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "web" / "data"
_LOCK = threading.Lock()


# ------------------------------------------------------------------ #
# Low-level JSON read/write
# ------------------------------------------------------------------ #

def _load(name: str, default):
    path = _DATA_DIR / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save(name: str, data) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _DATA_DIR / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, path)  # atomic on POSIX


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ #
# Portfolio (holdings)
# ------------------------------------------------------------------ #

def get_holdings() -> List[Dict]:
    return _load("portfolio.json", {"holdings": []}).get("holdings", [])


def get_holding(ticker: str) -> Optional[Dict]:
    t = (ticker or "").upper().strip()
    if not t:
        return None
    for h in get_holdings():
        if str(h.get("ticker", "")).upper() == t:
            return h
    return None


def upsert_holding(ticker: str, shares, cost_basis) -> Dict:
    """Add a holding, or update shares/cost if the ticker already exists."""
    t = (ticker or "").upper().strip()
    if not t:
        raise ValueError("ticker is required")
    shares = _num(shares) or 0
    cost_basis = _num(cost_basis)
    with _LOCK:
        data = _load("portfolio.json", {"holdings": []})
        holds = data.setdefault("holdings", [])
        for h in holds:
            if str(h.get("ticker", "")).upper() == t:
                h["shares"] = shares
                h["cost_basis"] = cost_basis
                _save("portfolio.json", data)
                return h
        new = {"ticker": t, "shares": shares, "cost_basis": cost_basis, "added_at": _now()}
        holds.append(new)
        _save("portfolio.json", data)
        return new


def remove_holding(ticker: str) -> bool:
    t = (ticker or "").upper().strip()
    with _LOCK:
        data = _load("portfolio.json", {"holdings": []})
        holds = data.setdefault("holdings", [])
        before = len(holds)
        data["holdings"] = [h for h in holds if str(h.get("ticker", "")).upper() != t]
        _save("portfolio.json", data)
        return len(data["holdings"]) < before


# ------------------------------------------------------------------ #
# Notes (calendar journal)
# ------------------------------------------------------------------ #

def get_notes(date: Optional[str] = None, ticker: Optional[str] = None) -> List[Dict]:
    notes = _load("notes.json", {"notes": []}).get("notes", [])
    if date:
        notes = [n for n in notes if n.get("date") == date]
    if ticker:
        t = ticker.upper()
        notes = [n for n in notes if str(n.get("ticker") or "").upper() == t]
    return sorted(notes, key=lambda n: n.get("created_at", ""), reverse=True)


def add_note(text: str, date: Optional[str] = None, ticker: Optional[str] = None,
             headline: Optional[str] = None, url: Optional[str] = None) -> Dict:
    if not (text or "").strip():
        raise ValueError("note text is required")
    with _LOCK:
        data = _load("notes.json", {"notes": []})
        notes = data.setdefault("notes", [])
        note = {
            "id": uuid.uuid4().hex[:12],
            "date": date or _today(),
            "ticker": ((ticker or "").upper() or None),
            "headline": headline or None,
            "url": url or None,
            "text": text.strip(),
            "created_at": _now(),
        }
        notes.append(note)
        _save("notes.json", data)
        return note


def delete_note(note_id: str) -> bool:
    with _LOCK:
        data = _load("notes.json", {"notes": []})
        notes = data.setdefault("notes", [])
        before = len(notes)
        data["notes"] = [n for n in notes if n.get("id") != note_id]
        _save("notes.json", data)
        return len(data["notes"]) < before
