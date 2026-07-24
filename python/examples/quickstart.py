"""Quickstart: build Dollar Bars from a trade tape, batch and streaming.

Run:  python examples/quickstart.py
"""

from fintech_dollar_bars import StreamingDollarBarBuilder, construct_bars

config = {"targetDollar": 10000, "currency": "USD", "priceDecimals": 2, "quantityDecimals": 0}
specs = [(100, 40), (90, 70), (95, 50), (105, 60), (100, 30)]
trades = [
    {"tradeId": f"W{i+1}", "timestamp": f"2026-01-05T14:30:0{i}.000Z", "session": "2026-01-05",
     "symbol": "SYNTH", "price": p, "volume": v, "currency": "USD"}
    for i, (p, v) in enumerate(specs)
]

# 1) Batch: a bar closes once cumulative notional (price*volume) >= $10,000.
for bar in construct_bars(trades, config):
    print(f"bar {bar['barIndex']}: ${bar['dollarValue']} (target ${bar['targetDollar']}, "
          f"excess ${bar['excessDollar']}) ticks={bar['tickCount']} ({bar['closeReason']})")

# 2) Streaming: emit each bar the moment notional crosses the target.
print("--- streaming ---")
builder = StreamingDollarBarBuilder(config)
for trade in trades:
    for bar in builder.push(trade):
        print(f"closed bar on {trade['tradeId']} at ${bar['dollarValue']} ({bar['closeReason']})")
for bar in builder.flush():
    print(f"flushed partial bar ${bar['dollarValue']} ({bar['closeReason']})")
