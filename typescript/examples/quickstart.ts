/**
 * Quickstart: build Dollar Bars from a trade tape, batch and streaming.
 *
 * Run:  node --experimental-strip-types examples/quickstart.ts
 */

import { constructBars, type DollarBarConfig, type Trade } from "../src/bars.ts";
import { StreamingDollarBarBuilder } from "../src/streaming.ts";

const config: DollarBarConfig = { targetDollar: 10000, currency: "USD", priceDecimals: 2, quantityDecimals: 0 };
const specs: Array<[number, number]> = [[100, 40], [90, 70], [95, 50], [105, 60], [100, 30]];
const trades: Trade[] = specs.map(([price, volume], i) => ({
  tradeId: `W${i + 1}`,
  timestamp: `2026-01-05T14:30:0${i}.000Z`,
  session: "2026-01-05",
  symbol: "SYNTH",
  price,
  volume,
  currency: "USD",
}));

// 1) Batch: a bar closes once cumulative notional (price*volume) >= $10,000.
for (const bar of constructBars(trades, config)) {
  console.log(`bar ${bar.barIndex}: $${bar.dollarValue} (target $${bar.targetDollar}, excess $${bar.excessDollar}) ticks=${bar.tickCount} (${bar.closeReason})`);
}

// 2) Streaming: emit each bar the moment notional crosses the target.
console.log("--- streaming ---");
const builder = new StreamingDollarBarBuilder(config);
for (const trade of trades) {
  for (const bar of builder.push(trade)) console.log(`closed bar on ${trade.tradeId} at $${bar.dollarValue} (${bar.closeReason})`);
}
for (const bar of builder.flush()) console.log(`flushed partial bar $${bar.dollarValue} (${bar.closeReason})`);
