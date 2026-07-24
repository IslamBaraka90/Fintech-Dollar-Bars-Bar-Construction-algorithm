# Fintech Dollar Bars — Bar Construction Algorithm

> A canonical, well-specified, **cross-language (Python + TypeScript)** reference
> implementation of **Dollar Bars** — aggregating a trade tape into bars that each
> trade at least `targetDollar` of notional (price × volume) — using **exact
> fixed-point arithmetic** so bar membership is identical across languages. Ships
> a **streaming (incremental) builder** and strict validation.

<p>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="TypeScript" src="https://img.shields.io/badge/typescript-5.7%2B-3178c6">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Tests" src="https://img.shields.io/badge/tests-17%20py%20%2F%2017%20ts-brightgreen">
</p>

**📖 Full article (canonical):** **[Dollar Bars — The Fintech Builder](https://thefintechbuilder.com/market-data-engineering/bar-construction/dollar-bars/)**

This repository is the runnable, production-oriented companion to that article.
The article teaches the concept; this repo is the code you install and build on.

🧭 **Browse all algorithms:** [Awesome FinTech Algorithms](https://github.com/IslamBaraka90/Fintech-Algorithms-Awesome) — the full index of the library.
🗂️ **This algorithm's domain:** [Market Data Engineering](https://thefintechbuilder.com/domains/market-data-engineering/) › **Bar Construction**
↔️ **Sibling bar types:** [Time](https://github.com/IslamBaraka90/Fintech-Time-Bars-Bar-Construction-algorithm) · [Tick](https://github.com/IslamBaraka90/Fintech-Tick-Bars-Bar-Construction-algorithm) · [Volume](https://github.com/IslamBaraka90/Fintech-Volume-Bars-Bar-Construction-algorithm).

| | |
|---|---|
| **Catalog topic** | `D01-F01-A04` |
| **Domain** | D01 — Market Data Engineering |
| **Family** | D01-F01 — Bar Construction |
| **Difficulty** | 2 / 5 |
| **Languages** | Python, TypeScript |

---

## Table of contents

- [What are Dollar Bars?](#what-are-dollar-bars)
- [Why fixed-point arithmetic](#why-fixed-point-arithmetic)
- [Why this implementation](#why-this-implementation)
- [Install](#install)
- [Quickstart](#quickstart)
- [Streaming (live tapes)](#streaming-live-tapes)
- [Loading a trade tape](#loading-a-trade-tape)
- [Bar & config shapes](#bar--config-shapes)
- [Worked example (exact)](#worked-example-exact)
- [API reference](#api-reference)
- [Edge cases & limitations](#edge-cases--limitations)
- [Testing](#testing)
- [Related algorithms](#related-algorithms)
- [License](#license)

---

## What are Dollar Bars?

A **dollar bar** closes once the trades inside it have exchanged at least
`targetDollar` of value — sampling by **money traded** rather than by clock time,
tick count, or share volume.

```
D_j = sum over trades in bar B_j of price_i * volume_i
close B_j at the first trade for which D_j >= targetDollar
```

Dollar bars are the most economically meaningful of the information clocks: a bar
represents a fixed amount of capital changing hands. They're also more robust to
price level and splits than volume bars (López de Prado, *Advances in Financial
Machine Learning*).

## Why fixed-point arithmetic

Deciding bar membership on `price × volume` in floating point is a trap — `0.1 +
0.2 != 0.3`, and two languages can disagree on the exact crossing trade. This
package converts every price and volume to an **integer** using `priceDecimals`
and `quantityDecimals`, then does all threshold math in integers (Python `int`,
TypeScript `bigint`). The result: **byte-identical bars in both languages**, and
no floating-point drift ever decides where a bar closes. Values are converted
back to numbers only for display.

## Why this implementation

- **Exact integer thresholds** — no float decides membership; the same crossing
  trade is chosen everywhere.
- **Whole-trade overshoot** — the crossing trade stays whole; each bar reports its
  `dollarValue`, the `targetDollar`, and the `excessDollar` above target.
- **Strict validation** — one `DollarBarsValidationError` for chronology, unique
  ids, single symbol/currency (a 3-letter code), decimal-scale limits, and a
  safe-integer notional ceiling.
- **A streaming builder** (`StreamingDollarBarBuilder`) using the same fixed-point
  math — byte-identical to the batch kernel, validated incrementally.
- **Cross-language parity** — the worked example and the multi-bar tape produce
  the same bars in both languages.

## Install

**Python**

```bash
pip install fintech-dollar-bars
```

**TypeScript / JavaScript (Node ≥ 20)**

```bash
npm install fintech-dollar-bars
```

## Quickstart

**Python**

```python
from fintech_dollar_bars import construct_bars

bars = construct_bars(trades, {"targetDollar": 1_000_000, "currency": "USD"})
```

**TypeScript**

```ts
import { constructBars } from "fintech-dollar-bars";

const bars = constructBars(trades, { targetDollar: 1_000_000, currency: "USD" });
```

## Streaming (live tapes)

`StreamingDollarBarBuilder` emits a bar the moment cumulative notional crosses the
target. `push` returns the bars closed by that trade (usually 0 or 1); `flush`
closes the final partial bar.

```python
from fintech_dollar_bars import StreamingDollarBarBuilder

builder = StreamingDollarBarBuilder({"targetDollar": 1_000_000, "currency": "USD"})
for trade in tape:                    # your live source
    for bar in builder.push(trade):
        publish(bar)
for bar in builder.flush():
    publish(bar)
```

```ts
const builder = new StreamingDollarBarBuilder({ targetDollar: 1_000_000, currency: "USD" });
for (const trade of tape) for (const bar of builder.push(trade)) publish(bar);
for (const bar of builder.flush()) publish(bar);
```

## Loading a trade tape

Dollar bars are built from **individual trades**, and Yahoo Finance does **not**
expose tick data (it serves pre-aggregated bars only). So the real-data path is
a trade tape:

```python
from fintech_dollar_bars import construct_bars, load_trades

trades = load_trades("tape.csv")   # tradeId,timestamp,session,symbol,price,volume,currency
bars = construct_bars(trades, {"targetDollar": 1_000_000, "currency": "USD"})
```

> **Data note:** the committed fixtures are synthetic and exist only to exercise
> the load → construct path. They are not real market observations.

## Bar & config shapes

**Config:** `targetDollar` (positive) · `currency` (3-letter uppercase, e.g.
`"USD"`) · `priceDecimals` (0–8, default 2) · `quantityDecimals` (0–8, default 0)
· `closePartial` (default `true`).

**Bar** (per emitted bar): `barIndex, session, symbol, currency, startTime,
endTime, lastTradeTime, open, high, low, close, volume, dollarValue,
targetDollar, excessDollar, tickCount, firstTradeId, lastTradeId, closeReason`.

## Worked example (exact)

`targetDollar = 1000` (config in the fixture uses `10000`). Two trades:

| trade | price | volume | notional | cumulative |
|---|--:|--:|--:|--:|
| W1 | 100 | 40 | 4000 | 4000 |
| W2 | 90 | 70 | 6300 | **10300** ≥ 10000 → close |

The bar closes on W2 with `dollarValue = 10300`, `excessDollar = 300` (the
crossing trade stayed whole). A five-trade tape extends this to three bars
(`$10300 / $11050 / $3000`). These exact values are asserted by **both** language
test suites.

## API reference

| Purpose | Python | TypeScript |
|---|---|---|
| Batch construction | `construct_bars(trades, config)` | `constructBars(trades, config)` |
| Streaming builder | `StreamingDollarBarBuilder(config)` | `new StreamingDollarBarBuilder(config)` |
| Load a trade tape | `load_trades(csv)` | `loadTrades(path)` |
| Errors | `DollarBarsValidationError` | `DollarBarsValidationError` |

## Edge cases & limitations

- **Overshoot by design:** the crossing trade is not split, so `dollarValue` can
  exceed `targetDollar` (reported as `excessDollar`).
- **Decimal scale is enforced:** a price/volume with more decimals than configured
  is rejected — set `priceDecimals` / `quantityDecimals` to match your venue.
- **Safe-integer ceiling:** scaled notional must fit `2^53 − 1`; very large targets
  or tiny decimal scales can hit it.
- **Single symbol & currency per call;** contiguous sessions only.

## Testing

**Python** (17 tests)

```bash
cd python && pip install -e ".[dev]" && pytest
```

**TypeScript** (17 tests, zero runtime dependencies)

```bash
cd typescript && npm install && npm test && npm run build
```

## Related algorithms

- `D01-F01-A01` — [Time Bars](https://github.com/IslamBaraka90/Fintech-Time-Bars-Bar-Construction-algorithm) · `A02` — [Tick Bars](https://github.com/IslamBaraka90/Fintech-Tick-Bars-Bar-Construction-algorithm) · `A03` — [Volume Bars](https://github.com/IslamBaraka90/Fintech-Volume-Bars-Bar-Construction-algorithm)
- `D01-F01-A05…A07` — Imbalance / Run bars

Full index: **[Awesome FinTech Algorithms](https://github.com/IslamBaraka90/Fintech-Algorithms-Awesome)**.

## License

[MIT](./LICENSE) © The Fintech Builder. Part of the
[100 FinTech Algorithms](https://thefintechbuilder.com) library.
