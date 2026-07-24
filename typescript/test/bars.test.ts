import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { DollarBarsValidationError, constructBars, type DollarBarConfig, type Trade } from "../src/bars.ts";

const FIXTURE = JSON.parse(
  readFileSync(fileURLToPath(new URL("./fixtures/worked_example.json", import.meta.url)), "utf8"),
);
const CONFIG: DollarBarConfig = FIXTURE.config;
const TRADES: Trade[] = FIXTURE.trades;

test("worked example single bar", () => {
  const bars = constructBars(TRADES, CONFIG);
  assert.equal(bars.length, 1);
  const bar = bars[0];
  assert.equal(bar.dollarValue, 10300);
  assert.equal(bar.excessDollar, 300);
  assert.equal(bar.targetDollar, 10000);
  assert.equal(bar.closeReason, "threshold");
  assert.equal(bar.volume, 110);
  assert.equal(bar.tickCount, 2);
  assert.equal(bar.currency, "USD");
  assert.equal(bar.symbol, "SYNTH");
});

test("whole-trade overshoot reports excess", () => {
  const bar = constructBars(TRADES, CONFIG)[0];
  assert.ok(bar.dollarValue > bar.targetDollar);
  assert.equal(bar.excessDollar, bar.dollarValue - bar.targetDollar);
});

test("fixed-point exactness with cents", () => {
  const trades: Trade[] = [
    { tradeId: "A", timestamp: "2026-01-05T00:00:00.000Z", session: "S", symbol: "X", price: 33.33, volume: 3, currency: "USD" },
    { tradeId: "B", timestamp: "2026-01-05T00:00:01.000Z", session: "S", symbol: "X", price: 0.02, volume: 1, currency: "USD" },
  ];
  const bar = constructBars(trades, { targetDollar: 100, currency: "USD" })[0];
  assert.equal(bar.dollarValue, 100.01);
  assert.ok(Math.abs(bar.excessDollar - 0.01) < 1e-9);
});

test("empty trades returns empty", () => {
  assert.deepEqual(constructBars([], CONFIG), []);
});

test("rejects bad currency", () => {
  assert.throws(() => constructBars(TRADES, { ...CONFIG, currency: "usd" }), DollarBarsValidationError);
});

test("rejects target below scale", () => {
  assert.throws(() => constructBars(TRADES, { ...CONFIG, targetDollar: 0 }), DollarBarsValidationError);
});

test("rejects price exceeding scale", () => {
  assert.throws(() => constructBars([{ ...TRADES[0], price: 100.123 }], CONFIG), DollarBarsValidationError);
});

test("rejects duplicate trade id", () => {
  assert.throws(
    () => constructBars([TRADES[0], { ...TRADES[1], tradeId: "W1" }], CONFIG),
    DollarBarsValidationError,
  );
});

test("rejects mixed currency trade", () => {
  assert.throws(
    () => constructBars([TRADES[0], { ...TRADES[1], currency: "EUR" }], CONFIG),
    DollarBarsValidationError,
  );
});

test("rejects unordered trades", () => {
  assert.throws(() => constructBars([...TRADES].reverse(), CONFIG), DollarBarsValidationError);
});
