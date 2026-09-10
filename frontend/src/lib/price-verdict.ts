/**
 * What a price history has to say about the last price paid.
 *
 * The product page used to answer with two numbers — "last paid" and
 * "best in 30 days" — which on a short history are usually the same
 * number twice. The question a person actually arrives with is *was that
 * a good price*, and that is a comparison, not a value.
 *
 * Pure, so the judgement can be tested without a screen.
 */
import type { PricePoint } from '@/types'

/** Prices are compared per base unit when they can be — R$/l survives a
 *  500 ml against a 1,5 L, and R$ 1,79 against R$ 3,29 does not. Falls
 *  back to the paid price when the line could not be normalised. */
export function comparable(point: PricePoint): number {
  const normalized = point.normalized_price === null ? null : Number(point.normalized_price)
  return normalized === null || Number.isNaN(normalized) ? Number(point.unit_price) : normalized
}

export type Verdict =
  | { kind: 'only' }
  | { kind: 'cheapest' }
  | { kind: 'above'; percent: number; best: PricePoint }

/**
 * Outliers are excluded from the comparison but not from the page: a
 * price ten times the usual one is almost always a parsing accident, and
 * calling the real price "83% above your best" because of it would be
 * worse than saying nothing.
 */
export function verdict(last: PricePoint | null, history: PricePoint[]): Verdict | null {
  if (!last) return null
  const sound = history.filter((point) => !point.is_outlier)
  if (sound.length < 2) return { kind: 'only' }

  const best = sound.reduce((a, b) => (comparable(b) < comparable(a) ? b : a))
  const paid = comparable(last)
  const floor = comparable(best)
  if (floor <= 0 || paid <= floor) return { kind: 'cheapest' }

  // Under 1% is rounding, not a saving worth a sentence — measured before
  // the rounding, or half a percent would come back as "1% above".
  const percent = ((paid - floor) / floor) * 100
  return percent < 1 ? { kind: 'cheapest' } : { kind: 'above', percent: Math.round(percent), best }
}

/** The store with the lowest sound price, when more than one was seen. */
export function cheapestStore(history: PricePoint[]): PricePoint | null {
  const sound = history.filter((point) => !point.is_outlier)
  const stores = new Set(sound.map((point) => point.store_id))
  if (stores.size < 2) return null
  return sound.reduce((a, b) => (comparable(b) < comparable(a) ? b : a))
}

/**
 * The points a chart may be drawn from, oldest first — or null when a chart
 * would say more than the data does.
 *
 * Three refusals. Fewer than five sound observations: with two points a line
 * between them insinuates a trend that was never measured. A mixed base unit:
 * `comparable()` falls back to the paid price when a line could not be
 * normalised, so a history that is half R$/l and half R$ each would be drawn
 * on one axis as if the numbers meant the same thing. And outliers, which the
 * backend only flags at ten times the median or a tenth of it — inside the
 * chart they would flatten every real movement into a straight line at the
 * bottom of the axis. They stay in the history list below, struck through,
 * where a reader can see them without an axis being bent around them.
 */
export function chartable(history: PricePoint[]): PricePoint[] | null {
  const sound = history.filter((point) => !point.is_outlier)
  if (sound.length < 5) return null
  const units = new Set(sound.map((point) => (point.normalized_price === null ? null : point.base_unit)))
  if (units.size > 1) return null
  return [...sound].sort((a, b) => a.observed_on.localeCompare(b.observed_on))
}

/** How many observations a point of the average speaks for. */
export const AVERAGE_WINDOW = 3

/**
 * A trailing average over the last `AVERAGE_WINDOW` purchases, aligned with
 * the points it was computed from and null until there are enough of them.
 *
 * Trailing rather than centred, because a centred average would put the
 * price of a purchase that has not happened yet into the reading for one
 * that has. It smooths the store-to-store swing — the same tin is a real
 * fifty centavos apart across the street — so what is left is the drift.
 */
export function movingAverage(points: PricePoint[], window = AVERAGE_WINDOW): (number | null)[] {
  return points.map((_, index) => {
    if (index + 1 < window) return null
    const slice = points.slice(index + 1 - window, index + 1)
    return slice.reduce((sum, point) => sum + comparable(point), 0) / window
  })
}
