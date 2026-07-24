/**
 * Stateful, streaming Dollar-Bar builder.
 *
 * `./bars`'s `constructBars` aggregates a whole tape at once. A live tape needs a
 * builder that accepts one trade at a time and emits a bar the instant cumulative
 * notional reaches the target. `StreamingDollarBarBuilder` uses the same exact
 * fixed-point BigInt arithmetic, validates each trade incrementally, and produces
 * byte-identical bars to the batch kernel.
 */

import {
  DollarBarsValidationError,
  _internals,
  type DollarBar,
  type DollarBarConfig,
  type Trade,
  type CloseReason,
} from "./bars.ts";

const { MAX_SAFE, timestamp, decimalPlaces, scaledInt, numberFromScaled } = _internals;

interface Prepared {
  trade: Trade;
  price: bigint;
  quantity: bigint;
}

export class StreamingDollarBarBuilder {
  private readonly currency: string;
  private readonly pricePlaces: number;
  private readonly quantityPlaces: number;
  private readonly notionalPlaces: number;
  private readonly target: bigint;
  private readonly closePartial: boolean;

  // validation state
  private ids = new Set<string>();
  private closedSessions = new Set<string>();
  private validationSession: string | null = null;
  private symbol: string | null = null;
  private priorTime: number | null = null;
  private priorSequence: number | undefined;

  // aggregation state
  private current: Prepared[] = [];
  private activeSession: string | null = null;
  private cumulative = 0n;
  private barCount = 0;
  private flushed = false;

  constructor(config: DollarBarConfig) {
    if (!config || typeof config !== "object") throw new DollarBarsValidationError("config must be an object");
    if (config.closePartial !== undefined && typeof config.closePartial !== "boolean") throw new DollarBarsValidationError("closePartial must be boolean");
    if (typeof config.currency !== "string" || !/^[A-Z]{3}$/.test(config.currency)) {
      throw new DollarBarsValidationError("config.currency must be one three-letter uppercase currency code");
    }
    this.currency = config.currency;
    this.pricePlaces = decimalPlaces(config.priceDecimals, "priceDecimals", 2);
    this.quantityPlaces = decimalPlaces(config.quantityDecimals, "quantityDecimals", 0);
    this.notionalPlaces = this.pricePlaces + this.quantityPlaces;
    this.target = scaledInt(config.targetDollar, this.notionalPlaces, "targetDollar");
    this.closePartial = config.closePartial !== false;
  }

  private validateAndScale(trade: Trade): Prepared {
    for (const field of ["tradeId", "timestamp", "session", "symbol", "currency"] as const) {
      if (typeof trade?.[field] !== "string" || !trade[field]) throw new DollarBarsValidationError(`${field} must be a non-empty string`);
    }
    if (this.ids.has(trade.tradeId)) throw new DollarBarsValidationError("tradeId must be unique after corrections are resolved");
    this.ids.add(trade.tradeId);
    if (trade.currency !== this.currency) throw new DollarBarsValidationError("mixed or unexpected currency is not allowed; normalize upstream");
    if (this.symbol === null) this.symbol = trade.symbol;
    else if (trade.symbol !== this.symbol) throw new DollarBarsValidationError("one builder may contain only one symbol");

    const time = timestamp(trade.timestamp);
    if (trade.sequence !== undefined && !Number.isInteger(trade.sequence)) throw new DollarBarsValidationError("sequence must be an integer when supplied");
    if (this.priorTime !== null) {
      if (time < this.priorTime) throw new DollarBarsValidationError("trades must be chronological");
      if (time === this.priorTime && (this.priorSequence === undefined || trade.sequence === undefined || trade.sequence <= this.priorSequence)) {
        throw new DollarBarsValidationError("equal timestamps require strictly increasing integer sequence values");
      }
    }
    this.priorTime = time;
    this.priorSequence = trade.sequence;

    if (this.validationSession === null) this.validationSession = trade.session;
    else if (trade.session !== this.validationSession) {
      this.closedSessions.add(this.validationSession);
      if (this.closedSessions.has(trade.session)) throw new DollarBarsValidationError("a session may not reappear after its state has closed");
      this.validationSession = trade.session;
    }
    return {
      trade,
      price: scaledInt(trade.price, this.pricePlaces, "price"),
      quantity: scaledInt(trade.volume, this.quantityPlaces, "volume"),
    };
  }

  private emit(reason: CloseReason): DollarBar | null {
    if (!this.current.length) return null;
    const prices = this.current.map((item) => item.price);
    const quantities = this.current.map((item) => item.quantity);
    const first = this.current[0].trade;
    const last = this.current[this.current.length - 1].trade;
    const bar: DollarBar = {
      barIndex: this.barCount,
      session: first.session,
      symbol: first.symbol,
      currency: this.currency,
      startTime: first.timestamp,
      endTime: last.timestamp,
      lastTradeTime: last.timestamp,
      open: numberFromScaled(prices[0], this.pricePlaces),
      high: numberFromScaled(prices.reduce((a, b) => (a > b ? a : b)), this.pricePlaces),
      low: numberFromScaled(prices.reduce((a, b) => (a < b ? a : b)), this.pricePlaces),
      close: numberFromScaled(prices[prices.length - 1], this.pricePlaces),
      volume: numberFromScaled(quantities.reduce((a, b) => a + b, 0n), this.quantityPlaces),
      dollarValue: numberFromScaled(this.cumulative, this.notionalPlaces),
      targetDollar: numberFromScaled(this.target, this.notionalPlaces),
      excessDollar: numberFromScaled(this.cumulative - this.target, this.notionalPlaces),
      tickCount: this.current.length,
      firstTradeId: first.tradeId,
      lastTradeId: last.tradeId,
      closeReason: reason,
    };
    this.barCount += 1;
    this.current = [];
    this.cumulative = 0n;
    return bar;
  }

  /** Accept one trade and return any bars it closes (usually 0 or 1). */
  push(trade: Trade): DollarBar[] {
    if (this.flushed) throw new DollarBarsValidationError("cannot push after flush()");
    const item = this.validateAndScale(trade);
    const emitted: DollarBar[] = [];

    if (this.activeSession !== null && item.trade.session !== this.activeSession) {
      if (this.current.length && this.closePartial) {
        const bar = this.emit("session_end");
        if (bar) emitted.push(bar);
      } else {
        this.current = [];
        this.cumulative = 0n;
      }
    }
    this.activeSession = item.trade.session;

    const contribution = item.price * item.quantity;
    if (this.cumulative + contribution > MAX_SAFE) throw new DollarBarsValidationError("bar notional exceeds the cross-language safe-integer range");
    this.current.push(item);
    this.cumulative += contribution;
    if (this.cumulative >= this.target) {
      const bar = this.emit("threshold");
      if (bar) emitted.push(bar);
    }
    return emitted;
  }

  /** Feed an array of trades, returning every bar closed along the way. */
  pushMany(trades: readonly Trade[]): DollarBar[] {
    const emitted: DollarBar[] = [];
    for (const trade of trades) emitted.push(...this.push(trade));
    return emitted;
  }

  /** Close the final partial bar (if `closePartial`) and end the stream. */
  flush(): DollarBar[] {
    this.flushed = true;
    if (this.current.length && this.closePartial) {
      const bar = this.emit("stream_end");
      return bar ? [bar] : [];
    }
    return [];
  }
}
