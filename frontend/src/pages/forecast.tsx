import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { forecast as forecastApi } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { formatCurrency } from '@/lib/format'
import { AlertTriangle, TrendingDown, Sparkles } from 'lucide-react'

const RANGES = [30, 90, 180]

export default function ForecastPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const [days, setDays] = useState(90)
  const [incomeAdjust, setIncomeAdjust] = useState(0)
  const [expenseAdjust, setExpenseAdjust] = useState(0)
  const whatIf = incomeAdjust !== 0 || expenseAdjust !== 0

  const { data, isLoading } = useQuery({
    queryKey: ['forecast', days, incomeAdjust, expenseAdjust],
    queryFn: () => forecastApi.get(days, incomeAdjust, expenseAdjust),
  })

  const currency = data?.currency ?? 'USD'
  const series = data?.series ?? []

  // Build an SVG path.
  const W = 800, H = 220, P = 8
  const balances = series.map((s) => s.balance)
  const min = Math.min(0, ...balances)
  const max = Math.max(1, ...balances)
  const x = (i: number) => P + (i / Math.max(1, series.length - 1)) * (W - 2 * P)
  const y = (v: number) => P + (1 - (v - min) / (max - min || 1)) * (H - 2 * P)
  const path = series.map((s, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(s.balance).toFixed(1)}`).join(' ')
  const zeroY = y(0)

  return (
    <div className="space-y-6">
      <PageHeader
        section={t('nav.forecast')}
        title={t('forecast.title')}
        action={
          <div className="flex items-center rounded-lg border border-border p-0.5">
            {RANGES.map((r) => (
              <button key={r} onClick={() => setDays(r)}
                className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${days === r ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                {t('forecast.days', { count: r })}
              </button>
            ))}
          </div>
        }
      />

      {isLoading ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : (
        <>
          {data?.first_shortfall && (
            <div className="flex items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3">
              <AlertTriangle size={18} className="text-rose-600 shrink-0" />
              <p className="text-sm text-rose-800">
                {t('forecast.shortfallWarning', { date: data.first_shortfall.date, balance: formatCurrency(data.first_shortfall.balance, currency, locale) })}
              </p>
            </div>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label={t('forecast.starting')} value={formatCurrency(data?.starting_balance ?? 0, currency, locale)} />
            <Stat label={t('forecast.ending')} value={formatCurrency(data?.ending_balance ?? 0, currency, locale)} />
            <Stat label={t('forecast.lowest')} value={formatCurrency(data?.lowest.balance ?? 0, currency, locale)}
              accent={(data?.lowest.balance ?? 0) < 0 ? 'text-rose-600' : undefined} sub={data?.lowest.date} />
            <Stat label={t('forecast.shortfallDays')} value={String(data?.shortfall_days ?? 0)}
              accent={(data?.shortfall_days ?? 0) > 0 ? 'text-rose-600' : 'text-emerald-600'} />
          </div>

          {/* What-if scenario */}
          <div className={`rounded-xl border p-5 ${whatIf ? 'border-primary/40 bg-primary/5' : 'border-border bg-card'}`}>
            <h2 className="text-sm font-semibold mb-3 flex items-center gap-2"><Sparkles size={15} className="text-primary" />{t('forecast.whatIf')}</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label className="text-xs">{t('forecast.extraIncome')}</Label>
                <Input type="number" min={0} step={100} value={incomeAdjust}
                  onChange={(e) => setIncomeAdjust(Math.max(0, Number(e.target.value) || 0))} />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">{t('forecast.expenseCut')}</Label>
                <Input type="number" min={0} step={100} value={expenseAdjust}
                  onChange={(e) => setExpenseAdjust(Math.max(0, Number(e.target.value) || 0))} />
              </div>
            </div>
            {whatIf && (
              <button onClick={() => { setIncomeAdjust(0); setExpenseAdjust(0) }}
                className="mt-3 text-xs text-muted-foreground hover:text-foreground">{t('forecast.resetWhatIf')}</button>
            )}
          </div>

          <div className="bg-card rounded-xl border border-border shadow-sm p-5">
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2"><TrendingDown size={15} className="text-muted-foreground" />{t('forecast.projectedBalance')}{whatIf && <span className="text-[11px] font-normal text-primary">· {t('forecast.whatIfActive')}</span>}</h2>
            <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-56" preserveAspectRatio="none">
              {min < 0 && <line x1={0} x2={W} y1={zeroY} y2={zeroY} stroke="currentColor" className="text-rose-300" strokeDasharray="4 4" />}
              <path d={`${path} L${x(series.length - 1)},${y(min)} L${x(0)},${y(min)} Z`} className="fill-primary/10" />
              <path d={path} className="stroke-primary" fill="none" strokeWidth={2} vectorEffect="non-scaling-stroke" />
            </svg>
            <div className="flex justify-between text-[11px] text-muted-foreground mt-1">
              <span>{series[0]?.date}</span>
              <span>{series[series.length - 1]?.date}</span>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function Stat({ label, value, accent, sub }: { label: string; value: string; accent?: string; sub?: string }) {
  return (
    <div className="bg-card rounded-xl border border-border px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${accent ?? 'text-foreground'}`}>{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
    </div>
  )
}
