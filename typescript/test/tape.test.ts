import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { constructBars, type DollarBarConfig } from "../src/bars.ts";
import { loadTrades } from "../src/tape.ts";

const TAPE = fileURLToPath(new URL("./fixtures/trade_tape.csv", import.meta.url));
const CONFIG: DollarBarConfig = { targetDollar: 10000, currency: "USD", priceDecimals: 2, quantityDecimals: 0 };

test("loadTrades parses the tape", () => {
  const trades = loadTrades(TAPE);
  assert.equal(trades.length, 5);
  assert.equal(trades[0].price, 100);
  assert.equal(trades[0].volume, 40);
});

test("constructBars over the loaded tape", () => {
  const bars = constructBars(loadTrades(TAPE), CONFIG);
  assert.deepEqual(
    bars.map((b) => b.dollarValue),
    [10300, 11050, 3000],
  );
  assert.deepEqual(
    bars.map((b) => b.excessDollar),
    [300, 1050, -7000],
  );
});
