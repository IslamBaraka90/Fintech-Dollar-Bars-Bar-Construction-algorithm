"""Stateful, streaming Dollar-Bar builder.

:func:`~fintech_dollar_bars.core.construct_bars` aggregates a whole tape at once.
A live tape needs a builder that accepts one trade at a time and emits a bar the
instant cumulative notional reaches the target. ``StreamingDollarBarBuilder`` does
that using the same exact fixed-point arithmetic, validating each trade
incrementally, and produces byte-identical bars to the batch kernel.

Feed trades with :meth:`push` (it returns any bars closed by that trade — usually
zero or one); call :meth:`flush` at end of stream.
"""

from __future__ import annotations

import re
from typing import Any

from .core import (
    MAX_SAFE_INTEGER,
    REQUIRED_TRADE_FIELDS,
    DollarBarsValidationError,
    _decimal_places,
    _number,
    _scaled_int,
    _timestamp,
)

__all__ = ["StreamingDollarBarBuilder"]


class StreamingDollarBarBuilder:
    """Incremental whole-trade dollar-bar builder with fixed-point math.

    Examples
    --------
    >>> builder = StreamingDollarBarBuilder({"targetDollar": 10000, "currency": "USD"})
    >>> closed = builder.push_many(tape) + builder.flush()   # doctest: +SKIP
    """

    def __init__(self, config: dict[str, Any]) -> None:
        if not isinstance(config, dict):
            raise DollarBarsValidationError("config must be an object")
        if not isinstance(config.get("closePartial", True), bool):
            raise DollarBarsValidationError("closePartial must be boolean")
        self._price_places = _decimal_places(config, "priceDecimals", 2)
        self._quantity_places = _decimal_places(config, "quantityDecimals", 0)
        self._notional_places = self._price_places + self._quantity_places
        currency = config.get("currency")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise DollarBarsValidationError("config.currency must be one three-letter uppercase currency code")
        self._currency = currency
        self._target = _scaled_int(config.get("targetDollar"), self._notional_places, "targetDollar")
        self._close_partial = bool(config.get("closePartial", True))

        # validation state
        self._seen_ids: set[str] = set()
        self._closed_sessions: set[str] = set()
        self._validation_session: str | None = None
        self._symbol: str | None = None
        self._previous_time = None
        self._previous_sequence: int | None = None

        # aggregation state
        self._current: list[tuple[dict[str, Any], int, int]] = []
        self._active_session: str | None = None
        self._cumulative = 0
        self._bar_count = 0
        self._flushed = False

    def _validate_and_scale(self, trade: object) -> tuple[int, int]:
        if not isinstance(trade, dict) or any(field not in trade for field in REQUIRED_TRADE_FIELDS):
            raise DollarBarsValidationError("trade is missing a required field")
        for field in ("tradeId", "session", "symbol", "currency"):
            if not isinstance(trade[field], str) or not trade[field]:
                raise DollarBarsValidationError(f"{field} must be a non-empty string")
        if trade["tradeId"] in self._seen_ids:
            raise DollarBarsValidationError("tradeId must be unique after corrections are resolved")
        self._seen_ids.add(trade["tradeId"])
        if trade["currency"] != self._currency:
            raise DollarBarsValidationError("mixed or unexpected currency is not allowed; normalize upstream")
        if self._symbol is None:
            self._symbol = trade["symbol"]
        elif trade["symbol"] != self._symbol:
            raise DollarBarsValidationError("one builder may contain only one symbol")

        current_time = _timestamp(trade["timestamp"])
        sequence = trade.get("sequence")
        if sequence is not None and (isinstance(sequence, bool) or not isinstance(sequence, int)):
            raise DollarBarsValidationError("sequence must be an integer when supplied")
        if self._previous_time is not None:
            if current_time < self._previous_time:
                raise DollarBarsValidationError("trades must be chronological")
            if current_time == self._previous_time:
                if self._previous_sequence is None or sequence is None or sequence <= self._previous_sequence:
                    raise DollarBarsValidationError("equal timestamps require strictly increasing integer sequence values")
        self._previous_time, self._previous_sequence = current_time, sequence

        if self._validation_session is None:
            self._validation_session = trade["session"]
        elif trade["session"] != self._validation_session:
            self._closed_sessions.add(self._validation_session)
            if trade["session"] in self._closed_sessions:
                raise DollarBarsValidationError("a session may not reappear after its state has closed")
            self._validation_session = trade["session"]

        return (
            _scaled_int(trade["price"], self._price_places, "price"),
            _scaled_int(trade["volume"], self._quantity_places, "volume"),
        )

    def _emit(self, reason: str) -> dict[str, Any] | None:
        if not self._current:
            return None
        prices = [item[1] for item in self._current]
        quantities = [item[2] for item in self._current]
        first, last = self._current[0][0], self._current[-1][0]
        bar = {
            "barIndex": self._bar_count,
            "session": first["session"],
            "symbol": first["symbol"],
            "currency": self._currency,
            "startTime": first["timestamp"],
            "endTime": last["timestamp"],
            "lastTradeTime": last["timestamp"],
            "open": _number(prices[0], self._price_places),
            "high": _number(max(prices), self._price_places),
            "low": _number(min(prices), self._price_places),
            "close": _number(prices[-1], self._price_places),
            "volume": _number(sum(quantities), self._quantity_places),
            "dollarValue": _number(self._cumulative, self._notional_places),
            "targetDollar": _number(self._target, self._notional_places),
            "excessDollar": _number(self._cumulative - self._target, self._notional_places),
            "tickCount": len(self._current),
            "firstTradeId": first["tradeId"],
            "lastTradeId": last["tradeId"],
            "closeReason": reason,
        }
        self._bar_count += 1
        self._current, self._cumulative = [], 0
        return bar

    def push(self, trade: dict[str, Any]) -> list[dict[str, Any]]:
        """Accept one trade and return any bars it closes (usually 0 or 1)."""
        if self._flushed:
            raise DollarBarsValidationError("cannot push after flush()")
        price, quantity = self._validate_and_scale(trade)
        emitted: list[dict[str, Any]] = []

        if self._active_session is not None and trade["session"] != self._active_session:
            if self._current and self._close_partial:
                bar = self._emit("session_end")
                if bar is not None:
                    emitted.append(bar)
            else:
                self._current, self._cumulative = [], 0
        self._active_session = trade["session"]

        contribution = price * quantity
        if self._cumulative + contribution > MAX_SAFE_INTEGER:
            raise DollarBarsValidationError("bar notional exceeds the cross-language safe-integer range")
        self._current.append((trade, price, quantity))
        self._cumulative += contribution
        if self._cumulative >= self._target:
            bar = self._emit("threshold")
            if bar is not None:
                emitted.append(bar)
        return emitted

    def push_many(self, trades: object) -> list[dict[str, Any]]:
        """Feed an iterable of trades, returning every bar closed along the way."""
        try:
            iterator = iter(trades)  # type: ignore[arg-type]
        except TypeError as error:
            raise DollarBarsValidationError("trades must be an iterable.") from error
        emitted: list[dict[str, Any]] = []
        for trade in iterator:
            emitted.extend(self.push(trade))
        return emitted

    def flush(self) -> list[dict[str, Any]]:
        """Close the final partial bar (if ``closePartial``) and end the stream."""
        self._flushed = True
        if self._current and self._close_partial:
            bar = self._emit("stream_end")
            return [bar] if bar is not None else []
        return []
