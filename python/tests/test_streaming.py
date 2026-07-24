"""StreamingDollarBarBuilder must produce byte-identical bars to the batch kernel."""

import json
from pathlib import Path

import pytest

from fintech_dollar_bars import DollarBarsValidationError, StreamingDollarBarBuilder, construct_bars, load_trades

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "worked_example.json").read_text())
CONFIG = FIXTURE["config"]
TRADES = FIXTURE["trades"]
TAPE = load_trades(Path(__file__).parent / "fixtures" / "trade_tape.csv")


def _stream(trades, config):
    builder = StreamingDollarBarBuilder(config)
    emitted = builder.push_many(trades)
    emitted.extend(builder.flush())
    return emitted


def test_streaming_matches_batch_worked_example():
    assert _stream(TRADES, CONFIG) == construct_bars(TRADES, CONFIG)


def test_streaming_matches_batch_multi_bar_tape():
    config = {"targetDollar": 10000, "currency": "USD", "priceDecimals": 2, "quantityDecimals": 0}
    assert _stream(TAPE, config) == construct_bars(TAPE, config)


def test_tape_produces_three_bars():
    config = {"targetDollar": 10000, "currency": "USD"}
    bars = construct_bars(TAPE, config)
    assert [b["dollarValue"] for b in bars] == [10300.0, 11050.0, 3000.0]
    assert [b["closeReason"] for b in bars] == ["threshold", "threshold", "stream_end"]


def test_push_emits_when_notional_crosses_target():
    builder = StreamingDollarBarBuilder(CONFIG)
    assert builder.push(TRADES[0]) == []          # 4000 < 10000
    closed = builder.push(TRADES[1])              # 10300 -> crosses
    assert len(closed) == 1 and closed[0]["dollarValue"] == 10300.0


def test_cannot_push_after_flush():
    builder = StreamingDollarBarBuilder(CONFIG)
    builder.push_many(TRADES)
    builder.flush()
    with pytest.raises(DollarBarsValidationError):
        builder.push(TRADES[0])
