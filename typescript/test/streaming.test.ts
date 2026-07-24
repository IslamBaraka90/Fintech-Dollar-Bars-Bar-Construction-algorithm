import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { DollarBarsValidationError, constructBars, type DollarBarConfig, type Trade } from "../src/bars.ts";
import { StreamingDollarBarBuilder } from "../src/streaming.ts";
import { loadTrades } from "../src/tape.ts";

const FIXTURE = JSON.parse(
  readFileSync(fileURLToPath(new URL("./fixtures/worked_example.json", import.meta.url)), "utf8"),
);
const CONFIG: DollarBarConfig = FIXTURE.config;
const TRADES: Trade[] = FIXTURE.trades;
const TAPE = loadTrades(fileURLToPath(new URL("./fixtures/trade_tape.csv", import.meta.url)));

function stream(trades: Trade[], config: DollarBarConfig) {
  const builder = new StreamingDollarBarBuilder(config);
  const emitted = builder.pushMany(trades);
  emitted.push(...builder.flush());
  return emitted;
}

test("streaming matches batch (worked example)", () => {
  assert.deepEqual(stream(TRADES, CONFIG), constructBars(TRADES, CONFIG));
});

test("streaming matches batch (multi-bar tape)", () => {
  const config: DollarBarConfig = { targetDollar: 10000, currency: "USD", priceDecimals: 2, quantityDecimals: 0 };
  assert.deepEqual(stream(TAPE, config), constructBars(TAPE, config));
});

test("tape produces three bars", () => {
  const bars = constructBars(TAPE, { targetDollar: 10000, currency: "USD" });
  assert.deepEqual(
    bars.map((b) => b.dollarValue),
    [10300, 11050, 3000],
  );
  assert.deepEqual(
    bars.map((b) => b.closeReason),
    ["threshold", "threshold", "stream_end"],
  );
});

test("push emits when notional crosses the target", () => {
  const builder = new StreamingDollarBarBuilder(CONFIG);
  assert.deepEqual(builder.push(TRADES[0]), []); // 4000
  const closed = builder.push(TRADES[1]); // 10300 -> crosses
  assert.equal(closed.length, 1);
  assert.equal(closed[0].dollarValue, 10300);
});

test("cannot push after flush", () => {
  const builder = new StreamingDollarBarBuilder(CONFIG);
  builder.pushMany(TRADES);
  builder.flush();
  assert.throws(() => builder.push(TRADES[0]), DollarBarsValidationError);
});
