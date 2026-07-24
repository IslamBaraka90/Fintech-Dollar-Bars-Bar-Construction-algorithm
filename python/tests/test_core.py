"""Exactness and contract tests for Dollar Bars.

The worked-example fixture pins one exact bar ($10300, excess $300); the tape
adds a multi-bar case. Both language suites assert the same values.
"""

import json
from pathlib import Path

import pytest

from fintech_dollar_bars import DollarBarsValidationError, construct_bars

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "worked_example.json").read_text())
CONFIG = FIXTURE["config"]
TRADES = FIXTURE["trades"]


def test_worked_example_single_bar():
    bars = construct_bars(TRADES, CONFIG)
    assert len(bars) == 1
    bar = bars[0]
    assert bar["dollarValue"] == 10300.0  # 100*40 + 90*70
    assert bar["excessDollar"] == 300.0
    assert bar["targetDollar"] == 10000.0
    assert bar["closeReason"] == "threshold"
    assert bar["volume"] == 110 and bar["tickCount"] == 2
    assert bar["currency"] == "USD" and bar["symbol"] == "SYNTH"


def test_whole_trade_overshoot():
    # The crossing trade stays whole, so the bar overshoots and reports the excess.
    bar = construct_bars(TRADES, CONFIG)[0]
    assert bar["dollarValue"] > bar["targetDollar"]
    assert bar["excessDollar"] == bar["dollarValue"] - bar["targetDollar"]


def test_fixed_point_exactness_with_cents():
    # 33.33 * 3 = 99.99 (< 100) then 0.02*1 pushes to 100.01 -> one bar, exact.
    trades = [
        {"tradeId": "A", "timestamp": "2026-01-05T00:00:00.000Z", "session": "S", "symbol": "X", "price": 33.33, "volume": 3, "currency": "USD"},
        {"tradeId": "B", "timestamp": "2026-01-05T00:00:01.000Z", "session": "S", "symbol": "X", "price": 0.02, "volume": 1, "currency": "USD"},
    ]
    bar = construct_bars(trades, {"targetDollar": 100, "currency": "USD"})[0]
    assert bar["dollarValue"] == 100.01
    assert bar["excessDollar"] == pytest.approx(0.01)


def test_empty_trades_returns_empty():
    assert construct_bars([], CONFIG) == []


def test_rejects_bad_currency():
    with pytest.raises(DollarBarsValidationError):
        construct_bars(TRADES, {**CONFIG, "currency": "usd"})


def test_rejects_target_below_scale():
    with pytest.raises(DollarBarsValidationError):
        construct_bars(TRADES, {**CONFIG, "targetDollar": 0})


def test_rejects_price_exceeding_scale():
    bad = [{**TRADES[0], "price": 100.123}]  # 3 decimals > priceDecimals=2
    with pytest.raises(DollarBarsValidationError):
        construct_bars(bad, CONFIG)


def test_rejects_duplicate_trade_id():
    with pytest.raises(DollarBarsValidationError):
        construct_bars([TRADES[0], {**TRADES[1], "tradeId": "W1"}], CONFIG)


def test_rejects_mixed_currency_trade():
    with pytest.raises(DollarBarsValidationError):
        construct_bars([TRADES[0], {**TRADES[1], "currency": "EUR"}], CONFIG)


def test_rejects_unordered_trades():
    with pytest.raises(DollarBarsValidationError):
        construct_bars(list(reversed(TRADES)), CONFIG)
