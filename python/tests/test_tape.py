"""Trade-tape loader tests (Dollar Bars need a tape; Yahoo has no tick data)."""

from pathlib import Path

from fintech_dollar_bars import construct_bars, load_trades

TAPE = Path(__file__).parent / "fixtures" / "trade_tape.csv"
CONFIG = {"targetDollar": 10000, "currency": "USD", "priceDecimals": 2, "quantityDecimals": 0}


def test_load_trades_parses_integers_as_int():
    trades = load_trades(TAPE)
    assert len(trades) == 5
    # integer volumes must stay int (a trailing .0 breaks fixed-point scaling).
    assert trades[0]["volume"] == 40 and isinstance(trades[0]["volume"], int)
    assert trades[0]["price"] == 100 and isinstance(trades[0]["price"], int)


def test_construct_bars_over_loaded_tape():
    bars = construct_bars(load_trades(TAPE), CONFIG)
    assert [b["dollarValue"] for b in bars] == [10300.0, 11050.0, 3000.0]
    assert [b["excessDollar"] for b in bars] == [300.0, 1050.0, -7000.0]
