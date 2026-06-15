"""
Verifies scripts/lib/yahoo_finance.py stays silent during requests.

Project rule: nothing may be written to stdout/stderr while a request is in
flight. yfinance logs delisted/404 warnings internally; get_ticker_data must
swallow that noise without swallowing real exceptions or changing its output.

Runnable two ways:
    .venv/bin/python tests/test_yahoo_finance_quiet.py
    .venv/bin/pytest tests/test_yahoo_finance_quiet.py

Note: the silence tests make a live network call to a junk symbol.
"""

import os
import sys
import tempfile
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from lib.yahoo_finance import get_ticker_data  # noqa: E402

JUNK = "ZZZZ_NOT_A_TICKER_XYZ"


@contextmanager
def capture_fd_output():
    """Capture everything written to fd 1 and fd 2, from any layer.

    Redirects the real stdout/stderr file descriptors at the OS level, so it
    catches Python print(), the logging module, and C-library writes alike.
    After the block, holder["text"] holds the captured bytes as text.
    """
    holder = {"text": ""}
    sys.stdout.flush()
    sys.stderr.flush()
    saved_out, saved_err = os.dup(1), os.dup(2)
    tmp = tempfile.TemporaryFile(mode="w+b")
    try:
        os.dup2(tmp.fileno(), 1)
        os.dup2(tmp.fileno(), 2)
        yield holder
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(saved_out)
        os.close(saved_err)
        tmp.seek(0)
        holder["text"] = tmp.read().decode("utf-8", "replace")
        tmp.close()


def test_junk_symbol_emits_nothing():
    """A missing/delisted ticker must not print a single byte."""
    with capture_fd_output() as out:
        get_ticker_data(JUNK, days=5)
    assert out["text"] == "", (
        "expected no stdout/stderr, got:\n" + out["text"]
    )


def test_junk_symbol_returns_degenerate_dict():
    """Output shape is preserved for an unknown symbol (no exception)."""
    data = get_ticker_data(JUNK, days=5)
    assert isinstance(data, dict)
    assert data["source"] == "yahoo_finance"
    assert data["symbol"] == JUNK
    assert data["price"] is None
    assert data["history"] == []


def test_empty_ticker_raises_value_error():
    """A truly empty ticker is a caller error, not a degenerate fetch."""
    for bad in ("", "   "):
        try:
            get_ticker_data(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


if __name__ == "__main__":
    tests = [
        test_junk_symbol_emits_nothing,
        test_junk_symbol_returns_degenerate_dict,
        test_empty_ticker_raises_value_error,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
