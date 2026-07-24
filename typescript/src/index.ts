/**
 * Fintech Dollar Bars — notional-clock bar construction.
 *
 * Companion article (canonical): https://thefintechbuilder.com/market-data-engineering/bar-construction/dollar-bars/
 * Catalog topic id: D01-F01-A04 (Domain D01 — Market Data Engineering / Family D01-F01 — Bar Construction)
 */

export {
  DollarBarsValidationError,
  constructBars,
  type Trade,
  type DollarBarConfig,
  type DollarBar,
  type CloseReason,
} from "./bars.ts";
export { StreamingDollarBarBuilder } from "./streaming.ts";
export { loadTrades } from "./tape.ts";
