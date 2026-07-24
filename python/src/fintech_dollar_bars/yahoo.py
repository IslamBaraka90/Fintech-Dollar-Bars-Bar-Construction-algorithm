"""Market-data helpers for Dollar Bars.

Dollar bars are built from a **trade tape** (individual executions). Yahoo Finance
does not expose tick data — only pre-aggregated **time** bars — so there is no
live Yahoo tick source. :func:`load_trades` reads a trade tape from CSV for the
construction path (the offline tests use a committed synthetic tape).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

__all__ = ["load_trades"]

_TRADE_FIELDS = ("tradeId", "timestamp", "session", "symbol", "currency")


def _number(text: str) -> int | float:
    """Parse a numeric CSV cell to int when integer-valued, else float.

    Dollar Bars' fixed-point scaling rejects an integer written with a trailing
    ``.0`` (it counts as a decimal digit), so integer quantities must stay ``int``.
    """
    stripped = text.strip()
    if stripped.lstrip("-").isdigit():
        return int(stripped)
    return float(stripped)


def load_trades(csv_path: str | Path) -> list[dict[str, Any]]:
    """Read a trade tape from CSV into trade dicts for :func:`construct_bars`.

    Expected columns: ``tradeId,timestamp,session,symbol,price,volume,currency``.
    ``price`` / ``volume`` are parsed as ``int`` when integer-valued, else ``float``.
    """
    with open(csv_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    trades: list[dict[str, Any]] = []
    for row in rows:
        trade: dict[str, Any] = {field: row[field] for field in _TRADE_FIELDS if field in row}
        trade["price"] = _number(row["price"])
        trade["volume"] = _number(row["volume"])
        trades.append(trade)
    return trades
