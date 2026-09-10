import { describe, expect, it } from 'vitest'
import { chartable, cheapestStore, comparable, verdict } from './price-verdict'
import type { PricePoint } from '@/types'

function point(overrides: Partial<PricePoint> = {}): PricePoint {
  return {
    observed_on: '2026-01-10',
    store_id: 'store-a',
    store_name: 'Store A',
    unit: 'un',
    quantity: '1.0000',
    unit_price: '10.0000',
    normalized_price: null,
    base_unit: null,
    is_outlier: false,
    source: 'receipt',
    mine: true,
    ...overrides,
  }
}

describe('comparable', () => {
  it('prefers the normalised price, which survives a change of size', () => {
    expect(comparable(point({ unit_price: '1.7900', normalized_price: '3.5800', base_unit: 'l' }))).toBe(3.58)
  })

  it('falls back to what was paid when the line was never normalised', () => {
    expect(comparable(point({ unit_price: '1.7900' }))).toBe(1.79)
  })
})

describe('verdict', () => {
  it('says nothing without a last price', () => {
    expect(verdict(null, [point()])).toBeNull()
  })

  it('calls a single observation what it is', () => {
    const only = point()
    expect(verdict(only, [only])).toEqual({ kind: 'only' })
  })

  it('recognises the cheapest price paid', () => {
    const last = point({ unit_price: '8.0000', observed_on: '2026-02-01' })
    expect(verdict(last, [point({ unit_price: '10.0000' }), last])).toEqual({ kind: 'cheapest' })
  })

  it('measures how far above the best a price is', () => {
    const best = point({ unit_price: '8.0000', store_id: 'store-b' })
    const last = point({ unit_price: '10.0000', observed_on: '2026-02-01' })
    expect(verdict(last, [best, last])).toEqual({ kind: 'above', percent: 25, best })
  })

  it('treats a rounding difference as no difference', () => {
    const best = point({ unit_price: '10.0000' })
    const last = point({ unit_price: '10.0500', observed_on: '2026-02-01' })
    expect(verdict(last, [best, last])).toEqual({ kind: 'cheapest' })
  })

  it('does not let a parsing accident decide the verdict', () => {
    // A price a tenth of the real one, flagged as an outlier: taking it as
    // the floor would call every honest price 900% above the best.
    const junk = point({ unit_price: '1.0000', is_outlier: true })
    const best = point({ unit_price: '10.0000' })
    const last = point({ unit_price: '10.0000', observed_on: '2026-02-01' })
    expect(verdict(last, [junk, best, last])).toEqual({ kind: 'cheapest' })
  })
})

describe('cheapestStore', () => {
  it('stays quiet while only one store has been seen', () => {
    expect(cheapestStore([point(), point({ unit_price: '9.0000' })])).toBeNull()
  })

  it('names the store with the lowest comparable price', () => {
    const cheap = point({ store_id: 'store-b', store_name: 'Store B', unit_price: '7.0000' })
    expect(cheapestStore([point(), cheap])?.store_name).toBe('Store B')
  })
})

describe('chartable', () => {
  const five = (index: number) =>
    point({ observed_on: `2026-01-0${index + 1}`, unit_price: `${10 + index}.0000` })

  it('refuses a chart the history cannot support', () => {
    expect(chartable([0, 1, 2, 3].map(five))).toBeNull()
  })

  it('draws from five sound observations, oldest first', () => {
    const series = chartable([4, 0, 3, 1, 2].map(five))
    expect(series?.map((p) => p.observed_on)).toEqual([
      '2026-01-01',
      '2026-01-02',
      '2026-01-03',
      '2026-01-04',
      '2026-01-05',
    ])
  })

  it('leaves outliers off the chart and out of the count', () => {
    const sound = [0, 1, 2, 3].map(five)
    const junk = point({ observed_on: '2026-01-09', unit_price: '99.0000', is_outlier: true })
    expect(chartable([...sound, junk])).toBeNull()
    expect(chartable([...sound, five(4), junk])).toHaveLength(5)
  })

  it('refuses to put two different base units on one axis', () => {
    const litres = [0, 1, 2, 3].map((i) =>
      point({ observed_on: `2026-01-0${i + 1}`, normalized_price: '3.0000', base_unit: 'l' }),
    )
    expect(chartable([...litres, point({ observed_on: '2026-01-05' })])).toBeNull()
  })
})
