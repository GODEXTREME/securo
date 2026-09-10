/**
 * A product's comparable price over time.
 *
 * Two lines. The purchases themselves, in the design system's first series
 * colour, and a trailing average over the last three of them — dashed, in the
 * muted ink of a guide rather than a second colour, because it is the same
 * measurement smoothed and not a second thing being measured. The x axis is
 * real time, not the position of a purchase in a list: groceries are bought
 * irregularly, and evenly spacing the points would draw a cadence nobody has.
 * The cheapest observation is the only one emphasised, because it is what the
 * page's verdict argues from.
 */
import { useTranslation } from 'react-i18next'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AXIS, CHART, REFERENCE_LINE, TOOLTIP_STYLE } from '@/lib/chart-theme'
import { formatCurrency } from '@/lib/format'
import { AVERAGE_WINDOW, comparable, movingAverage } from '@/lib/price-verdict'
import type { PricePoint } from '@/types'

const CURRENCY = 'BRL'

type Datum = {
  time: number
  value: number
  average: number | null
  store: string
  date: string
  best: boolean
}

export function PriceHistoryChart({
  points,
  baseUnit,
  locale,
  dateLocale,
}: {
  points: PricePoint[]
  baseUnit: string | null
  locale: string
  dateLocale: string
}) {
  const { t } = useTranslation()
  const floor = Math.min(...points.map(comparable))
  const averages = movingAverage(points)
  const data: Datum[] = points.map((point, index) => {
    const value = comparable(point)
    const day = new Date(`${point.observed_on}T00:00:00`)
    return {
      time: day.getTime(),
      value,
      average: averages[index],
      store: point.store_name ?? t('receipts.unknownStore'),
      date: day.toLocaleDateString(dateLocale),
      best: value === floor,
    }
  })

  const money = (value: number) => formatCurrency(value, CURRENCY, locale)
  const perUnit = (value: number) => (baseUnit ? `${money(value)}/${baseUnit}` : money(value))
  // Numeric, because "04 de jan." eats a third of a phone's width.
  const shortDate = (time: number) =>
    new Date(time).toLocaleDateString(dateLocale, { day: '2-digit', month: '2-digit' })

  return (
    <>
      <div className="h-48 w-full sm:h-56">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" vertical={false} />
            <XAxis
              {...AXIS}
              dataKey="time"
              type="number"
              scale="time"
              domain={['dataMin', 'dataMax']}
              tickFormatter={shortDate}
              minTickGap={28}
            />
            <YAxis
              {...AXIS}
              width={58}
              domain={['auto', 'auto']}
              tickCount={5}
              tickFormatter={(value) => money(Number(value))}
            />
            <Tooltip
              cursor={{ stroke: 'var(--border)' }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const datum = payload[0].payload as Datum
                return (
                  <div style={TOOLTIP_STYLE} className="px-3 py-2">
                    <p className="font-semibold tabular-nums">{perUnit(datum.value)}</p>
                    <p className="text-muted-foreground">{datum.store}</p>
                    <p className="text-muted-foreground tabular-nums">{datum.date}</p>
                    {datum.average !== null && (
                      <p className="mt-1 text-muted-foreground tabular-nums">
                        {t('products.chartAverage', { n: AVERAGE_WINDOW })}: {perUnit(datum.average)}
                      </p>
                    )}
                  </div>
                )
              }}
            />
            <Line
              type="linear"
              dataKey="average"
              stroke={REFERENCE_LINE.stroke}
              strokeDasharray={REFERENCE_LINE.strokeDasharray}
              strokeOpacity={0.7}
              strokeWidth={2}
              dot={false}
              activeDot={false}
              connectNulls
              isAnimationActive={false}
            />
            <Line
              /* Straight segments, not a spline: a curve through six purchases
                 would draw prices the shop never charged, and overshoot below
                 the cheapest one actually paid. */
              type="linear"
              dataKey="value"
              stroke={CHART.primary}
              strokeWidth={2}
              isAnimationActive={false}
              activeDot={{ r: 5, fill: CHART.primary, stroke: 'var(--card)', strokeWidth: 2 }}
              dot={({ cx, cy, payload, index }) => {
                const datum = payload as Datum
                return (
                  <circle
                    key={index}
                    cx={cx}
                    cy={cy}
                    r={datum.best ? 5 : 4}
                    fill={datum.best ? CHART.emphasis : CHART.primary}
                    stroke="var(--card)"
                    strokeWidth={2}
                  />
                )
              }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Direct labels rather than a legend box: two marks, and on a phone a
          legend costs more height than the thing it explains. */}
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ background: CHART.emphasis }} aria-hidden />
          {t('products.chartBestDot')}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="h-0 w-4 border-t-2 border-dashed border-muted-foreground/70"
            aria-hidden
          />
          {t('products.chartAverage', { n: AVERAGE_WINDOW })}
        </span>
      </p>
    </>
  )
}
