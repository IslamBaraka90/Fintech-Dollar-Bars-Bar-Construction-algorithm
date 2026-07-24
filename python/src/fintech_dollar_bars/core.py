"""Whole-trade, single-currency Dollar Bars with fixed-point membership math.

Faithful to the reference algorithm published at The Fintech Builder (topic
``D01-F01-A04``). A **dollar bar** closes once the trades inside it have traded at
least ``targetDollar`` of notional value (price x volume) — sampling the market by
*money exchanged* rather than by clock time, tick count, or share volume.

    D_j = sum over trades in bar B_j of price_i * volume_i
    close B_j at the first trade for which D_j >= targetDollar

To make the threshold comparison **exact and identical across languages**, prices
and volumes are converted to fixed-point integers using ``priceDecimals`` and
``quantityDecimals`` before any arithmetic — no floating-point drift decides bar
membership. The whole-trade convention keeps the crossing trade intact (bars may
overshoot). Each bar reports ``dollarValue`` and its ``excessDollar`` over target.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

__all__ = ["DollarBarsValidationError", "MAX_SAFE_INTEGER", "construct_bars"]

MAX_SAFE_INTEGER = 9_007_199_254_740_991
_DECIMAL_TEXT = re.compile(r"^(?:0|[1-9]\d*)(?:\.(\d+))?$")
REQUIRED_TRADE_FIELDS = ("tradeId", "timestamp", "session", "symbol", "price", "volume", "currency")


class DollarBarsValidationError(ValueError):
    """Raised when trades or config violate the Dollar Bars contract."""


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DollarBarsValidationError("timestamp must be an ISO-8601 UTC string ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise DollarBarsValidationError("timestamp must be valid ISO-8601 UTC") from exc


def _decimal_places(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 8:
        raise DollarBarsValidationError(f"{key} must be an integer from 0 through 8")
    return value


def _scaled_int(value: Any, places: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DollarBarsValidationError(f"{label} must be a number")
    text = str(value)
    match = _DECIMAL_TEXT.fullmatch(text)
    if not match:
        raise DollarBarsValidationError(f"{label} must be finite, positive, and without exponent notation")
    fraction = match.group(1) or ""
    if len(fraction) > places:
        raise DollarBarsValidationError(f"{label} exceeds the configured {places}-decimal scale")
    scaled = int(Decimal(text) * (10**places))
    if scaled <= 0 or scaled > MAX_SAFE_INTEGER:
        raise DollarBarsValidationError(f"{label} is outside the supported positive fixed-point range")
    return scaled


def _number(value: int, places: int) -> int | float:
    if places == 0:
        return value
    sign = "-" if value < 0 else ""
    digits = str(abs(value)).zfill(places + 1)
    return float(f"{sign}{digits[:-places]}.{digits[-places:]}")


def _validate_and_scale(
    trades: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[int, int, int, str, list[tuple[int, int]]]:
    if not isinstance(trades, list):
        raise DollarBarsValidationError("trades must be a list")
    if not isinstance(config, dict):
        raise DollarBarsValidationError("config must be an object")
    if not isinstance(config.get("closePartial", True), bool):
        raise DollarBarsValidationError("closePartial must be boolean")

    price_places = _decimal_places(config, "priceDecimals", 2)
    quantity_places = _decimal_places(config, "quantityDecimals", 0)
    notional_places = price_places + quantity_places
    currency = config.get("currency")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise DollarBarsValidationError("config.currency must be one three-letter uppercase currency code")
    target = _scaled_int(config.get("targetDollar"), notional_places, "targetDollar")

    seen_ids: set[str] = set()
    closed_sessions: set[str] = set()
    active_session: str | None = None
    symbol: str | None = None
    previous_time: datetime | None = None
    previous_sequence: int | None = None
    scaled: list[tuple[int, int]] = []

    for trade in trades:
        if not isinstance(trade, dict) or any(field not in trade for field in REQUIRED_TRADE_FIELDS):
            raise DollarBarsValidationError("trade is missing a required field")
        for field in ("tradeId", "session", "symbol", "currency"):
            if not isinstance(trade[field], str) or not trade[field]:
                raise DollarBarsValidationError(f"{field} must be a non-empty string")
        if trade["tradeId"] in seen_ids:
            raise DollarBarsValidationError("tradeId must be unique after corrections are resolved")
        seen_ids.add(trade["tradeId"])
        if trade["currency"] != currency:
            raise DollarBarsValidationError("mixed or unexpected currency is not allowed; normalize upstream")
        if symbol is None:
            symbol = trade["symbol"]
        elif trade["symbol"] != symbol:
            raise DollarBarsValidationError("one construct_bars call may contain only one symbol")

        current_time = _timestamp(trade["timestamp"])
        sequence = trade.get("sequence")
        if sequence is not None and (isinstance(sequence, bool) or not isinstance(sequence, int)):
            raise DollarBarsValidationError("sequence must be an integer when supplied")
        if previous_time is not None:
            if current_time < previous_time:
                raise DollarBarsValidationError("trades must be chronological")
            if current_time == previous_time:
                if previous_sequence is None or sequence is None or sequence <= previous_sequence:
                    raise DollarBarsValidationError("equal timestamps require strictly increasing integer sequence values")
        previous_time, previous_sequence = current_time, sequence

        if active_session is None:
            active_session = trade["session"]
        elif trade["session"] != active_session:
            closed_sessions.add(active_session)
            if trade["session"] in closed_sessions:
                raise DollarBarsValidationError("a session may not reappear after its state has closed")
            active_session = trade["session"]

        scaled.append(
            (
                _scaled_int(trade["price"], price_places, "price"),
                _scaled_int(trade["volume"], quantity_places, "volume"),
            )
        )
    return price_places, quantity_places, target, currency, scaled


def construct_bars(trades: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Build dollar bars using an inclusive threshold and whole-trade overshoot."""
    price_places, quantity_places, target, currency, scaled = _validate_and_scale(trades, config)
    if not trades:
        return []
    notional_places = price_places + quantity_places
    close_partial = config.get("closePartial", True)
    result: list[dict[str, Any]] = []
    current: list[tuple[dict[str, Any], int, int]] = []
    active_session: str | None = None
    cumulative = 0

    def emit(reason: str) -> None:
        nonlocal current, cumulative
        if not current:
            return
        prices = [item[1] for item in current]
        quantities = [item[2] for item in current]
        first, last = current[0][0], current[-1][0]
        result.append(
            {
                "barIndex": len(result),
                "session": first["session"],
                "symbol": first["symbol"],
                "currency": currency,
                "startTime": first["timestamp"],
                "endTime": last["timestamp"],
                "lastTradeTime": last["timestamp"],
                "open": _number(prices[0], price_places),
                "high": _number(max(prices), price_places),
                "low": _number(min(prices), price_places),
                "close": _number(prices[-1], price_places),
                "volume": _number(sum(quantities), quantity_places),
                "dollarValue": _number(cumulative, notional_places),
                "targetDollar": _number(target, notional_places),
                "excessDollar": _number(cumulative - target, notional_places),
                "tickCount": len(current),
                "firstTradeId": first["tradeId"],
                "lastTradeId": last["tradeId"],
                "closeReason": reason,
            }
        )
        current, cumulative = [], 0

    for trade, (price, quantity) in zip(trades, scaled):
        if active_session is not None and trade["session"] != active_session:
            if current and close_partial:
                emit("session_end")
            else:
                current, cumulative = [], 0
        active_session = trade["session"]
        contribution = price * quantity
        if cumulative + contribution > MAX_SAFE_INTEGER:
            raise DollarBarsValidationError("bar notional exceeds the cross-language safe-integer range")
        current.append((trade, price, quantity))
        cumulative += contribution
        if cumulative >= target:
            emit("threshold")

    if current and close_partial:
        emit("stream_end")
    return result
