/**
 * A product's comparable price over time.
 *
 * Deliberately one series and no legend: the card's title names what is
 * drawn. The x axis is real time, not the position of a purchase in a list —
 * groceries are bought irregularly, and evenly spacing the points would draw
 * a steady cadence nobody has. The cheapest observation is the only one
 * emphasised, because it is the one the page's verdict argues from.
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
import { formatCurrency } from '@/lib/format'
import { comparable } from '@/lib/price-verdict'
import type { PricePoint } from '@/types'

const CURRENCY = 'BRL'
const LINE = '#6366F1'
/** Amber-600 rather than the amber-500 of the chart tokens: 500 falls outside
 *  the readable lightness band on the dark surface. */
const BEST = '#D97706'

type Datum = {
  time: number
  value: number
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
  const data: Datum[] = points.map((point) => {
    const value = comparable(point)
    return {
      time: new Date(`${point.observed_on}T00:00:00`).getTime(),
      value,
      store: point.store_name ?? t('receipts.unknownStore'),
      date: new Date(`${point.observed_on}T00:00:00`).toLocaleDateString(dateLocale),
      best: value === floor,
    }
  })

  const money = (value: number) => formatCurrency(value, CURRENCY, locale)
  // Numeric, because "04 de jan." eats a third of a phone's width.
  const shortDate = (time: number) =>
    new Date(time).toLocaleDateString(dateLocale, { day: '2-digit', month: '2-digit' })

  return (
    <div className="h-48 w-full sm:h-56">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-muted" vertical={false} />
          <XAxis
            dataKey="time"
            type="number"
            scale="time"
            domain={['dataMin', 'dataMax']}
            tickFormatter={shortDate}
            tick={{ fontSize: 11 }}
            minTickGap={28}
          />
          <YAxis
            tick={{ fontSize: 11 }}
            width={62}
            domain={['auto', 'auto']}
            tickFormatter={(value) => money(Number(value))}
          />
          <Tooltip
            cursor={{ stroke: 'var(--border)' }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const datum = payload[0].payload as Datum
              return (
                <div className="rounded-xl border border-border bg-card px-3 py-2 text-xs shadow-md">
                  <p className="font-semibold tabular-nums">
                    {money(datum.value)}
                    {baseUnit && `/${baseUnit}`}
                  </p>
                  <p className="text-muted-foreground">{datum.store}</p>
                  <p className="text-muted-foreground tabular-nums">{datum.date}</p>
                </div>
              )
            }}
          />
          <Line
            /* Straight segments, not a spline: a curve through six purchases
               would draw prices the shop never charged, and overshoot below
               the cheapest one actually paid. */
            type="linear"
            dataKey="value"
            stroke={LINE}
            strokeWidth={2}
            isAnimationActive={false}
            activeDot={{ r: 5, fill: LINE, stroke: 'var(--card)', strokeWidth: 2 }}
            dot={({ cx, cy, payload, index }) => {
              const datum = payload as Datum
              return (
                <circle
                  key={index}
                  cx={cx}
                  cy={cy}
                  r={datum.best ? 5 : 4}
                  fill={datum.best ? BEST : LINE}
                  stroke="var(--card)"
                  strokeWidth={2}
                />
              )
            }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
