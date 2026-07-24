/**
 * Whole-trade, single-currency Dollar Bars with fixed-point membership math.
 *
 * A faithful, cross-language twin of the Python `fintech_dollar_bars.core` module
 * and of the reference algorithm published at The Fintech Builder (topic
 * `D01-F01-A04`). A dollar bar closes once its trades have traded at least
 * `targetDollar` of notional (price x volume):
 *
 *     close bar B at the first trade for which (sum of price*volume in B) >= targetDollar
 *
 * Prices and volumes are converted to fixed-point BigInt integers (using
 * `priceDecimals` / `quantityDecimals`) before any arithmetic, so membership
 * decisions are exact and identical across languages. The crossing trade stays
 * whole (bars may overshoot); each bar reports `dollarValue` and `excessDollar`.
 */

export class DollarBarsValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DollarBarsValidationError";
  }
}

export interface Trade {
  tradeId: string;
  timestamp: string;
  session: string;
  symbol: string;
  price: number;
  volume: number;
  currency: string;
  sequence?: number;
}

export interface DollarBarConfig {
  targetDollar: number;
  currency: string;
  priceDecimals?: number;
  quantityDecimals?: number;
  closePartial?: boolean;
}

export type CloseReason = "threshold" | "session_end" | "stream_end";

export interface DollarBar {
  barIndex: number;
  session: string;
  symbol: string;
  currency: string;
  startTime: string;
  endTime: string;
  lastTradeTime: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  dollarValue: number;
  targetDollar: number;
  excessDollar: number;
  tickCount: number;
  firstTradeId: string;
  lastTradeId: string;
  closeReason: CloseReason;
}

const MAX_SAFE = BigInt(Number.MAX_SAFE_INTEGER);
const DECIMAL_TEXT = /^(?:0|[1-9]\d*)(?:\.(\d+))?$/;

function timestamp(value: unknown): number {
  if (typeof value !== "string" || !value.endsWith("Z")) throw new DollarBarsValidationError("timestamp must be ISO-8601 UTC ending in Z");
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) throw new DollarBarsValidationError("timestamp must be valid ISO-8601 UTC");
  return parsed;
}

function decimalPlaces(value: unknown, label: string, fallback: number): number {
  const resolved = value ?? fallback;
  if (!Number.isInteger(resolved) || Number(resolved) < 0 || Number(resolved) > 8) {
    throw new DollarBarsValidationError(`${label} must be an integer from 0 through 8`);
  }
  return Number(resolved);
}

function scaledInt(value: unknown, places: number, label: string): bigint {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new DollarBarsValidationError(`${label} must be a finite number`);
  const text = String(value);
  const match = DECIMAL_TEXT.exec(text);
  if (!match) throw new DollarBarsValidationError(`${label} must be positive and written without exponent notation`);
  const fraction = match[1] ?? "";
  if (fraction.length > places) throw new DollarBarsValidationError(`${label} exceeds the configured ${places}-decimal scale`);
  const [whole] = text.split(".");
  const scaled = BigInt(whole) * 10n ** BigInt(places) + BigInt(fraction.padEnd(places, "0") || "0");
  if (scaled <= 0n || scaled > MAX_SAFE) throw new DollarBarsValidationError(`${label} is outside the supported positive fixed-point range`);
  return scaled;
}

function numberFromScaled(value: bigint, places: number): number {
  if (places === 0) return Number(value);
  const sign = value < 0n ? "-" : "";
  const digits = (value < 0n ? -value : value).toString().padStart(places + 1, "0");
  return Number(`${sign}${digits.slice(0, -places)}.${digits.slice(-places)}`);
}

interface Prepared {
  trade: Trade;
  price: bigint;
  quantity: bigint;
}

// Exported for the streaming builder to reuse the exact same fixed-point rules.
export const _internals = { MAX_SAFE, timestamp, decimalPlaces, scaledInt, numberFromScaled };

export function constructBars(trades: Trade[], config: DollarBarConfig): DollarBar[] {
  if (!Array.isArray(trades)) throw new DollarBarsValidationError("trades must be an array");
  if (!config || typeof config !== "object") throw new DollarBarsValidationError("config must be an object");
  if (config.closePartial !== undefined && typeof config.closePartial !== "boolean") throw new DollarBarsValidationError("closePartial must be boolean");
  if (typeof config.currency !== "string" || !/^[A-Z]{3}$/.test(config.currency)) {
    throw new DollarBarsValidationError("config.currency must be one three-letter uppercase currency code");
  }
  const pricePlaces = decimalPlaces(config.priceDecimals, "priceDecimals", 2);
  const quantityPlaces = decimalPlaces(config.quantityDecimals, "quantityDecimals", 0);
  const notionalPlaces = pricePlaces + quantityPlaces;
  const target = scaledInt(config.targetDollar, notionalPlaces, "targetDollar");
  const closePartial = config.closePartial !== false;

  const ids = new Set<string>();
  const closedSessions = new Set<string>();
  const prepared: Prepared[] = [];
  let priorTime: number | null = null;
  let priorSequence: number | undefined;
  let validationSession: string | null = null;
  let symbol: string | null = null;

  for (const trade of trades) {
    for (const field of ["tradeId", "timestamp", "session", "symbol", "currency"] as const) {
      if (typeof trade?.[field] !== "string" || !trade[field]) throw new DollarBarsValidationError(`${field} must be a non-empty string`);
    }
    if (ids.has(trade.tradeId)) throw new DollarBarsValidationError("tradeId must be unique after corrections are resolved");
    ids.add(trade.tradeId);
    if (trade.currency !== config.currency) throw new DollarBarsValidationError("mixed or unexpected currency is not allowed; normalize upstream");
    if (symbol === null) symbol = trade.symbol;
    else if (trade.symbol !== symbol) throw new DollarBarsValidationError("one constructBars call may contain only one symbol");

    const time = timestamp(trade.timestamp);
    if (trade.sequence !== undefined && !Number.isInteger(trade.sequence)) throw new DollarBarsValidationError("sequence must be an integer when supplied");
    if (priorTime !== null) {
      if (time < priorTime) throw new DollarBarsValidationError("trades must be chronological");
      if (time === priorTime && (priorSequence === undefined || trade.sequence === undefined || trade.sequence <= priorSequence)) {
        throw new DollarBarsValidationError("equal timestamps require strictly increasing integer sequence values");
      }
    }
    priorTime = time;
    priorSequence = trade.sequence;

    if (validationSession === null) validationSession = trade.session;
    else if (trade.session !== validationSession) {
      closedSessions.add(validationSession);
      if (closedSessions.has(trade.session)) throw new DollarBarsValidationError("a session may not reappear after its state has closed");
      validationSession = trade.session;
    }
    prepared.push({
      trade,
      price: scaledInt(trade.price, pricePlaces, "price"),
      quantity: scaledInt(trade.volume, quantityPlaces, "volume"),
    });
  }

  const result: DollarBar[] = [];
  let current: Prepared[] = [];
  let activeSession: string | null = null;
  let cumulative = 0n;

  const emit = (reason: CloseReason): void => {
    if (!current.length) return;
    const prices = current.map((item) => item.price);
    const quantities = current.map((item) => item.quantity);
    const first = current[0].trade;
    const last = current[current.length - 1].trade;
    result.push({
      barIndex: result.length,
      session: first.session,
      symbol: first.symbol,
      currency: config.currency,
      startTime: first.timestamp,
      endTime: last.timestamp,
      lastTradeTime: last.timestamp,
      open: numberFromScaled(prices[0], pricePlaces),
      high: numberFromScaled(prices.reduce((a, b) => (a > b ? a : b)), pricePlaces),
      low: numberFromScaled(prices.reduce((a, b) => (a < b ? a : b)), pricePlaces),
      close: numberFromScaled(prices[prices.length - 1], pricePlaces),
      volume: numberFromScaled(quantities.reduce((a, b) => a + b, 0n), quantityPlaces),
      dollarValue: numberFromScaled(cumulative, notionalPlaces),
      targetDollar: numberFromScaled(target, notionalPlaces),
      excessDollar: numberFromScaled(cumulative - target, notionalPlaces),
      tickCount: current.length,
      firstTradeId: first.tradeId,
      lastTradeId: last.tradeId,
      closeReason: reason,
    });
    current = [];
    cumulative = 0n;
  };

  for (const item of prepared) {
    if (activeSession !== null && item.trade.session !== activeSession) {
      if (current.length && closePartial) emit("session_end");
      else {
        current = [];
        cumulative = 0n;
      }
    }
    activeSession = item.trade.session;
    const contribution = item.price * item.quantity;
    if (cumulative + contribution > MAX_SAFE) throw new DollarBarsValidationError("bar notional exceeds the cross-language safe-integer range");
    current.push(item);
    cumulative += contribution;
    if (cumulative >= target) emit("threshold");
  }
  if (current.length && closePartial) emit("stream_end");
  return result;
}
