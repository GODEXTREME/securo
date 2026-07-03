import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { insights as insightsApi, advancedReports } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { formatCurrency } from '@/lib/format'
import { Lightbulb, TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight, Store } from 'lucide-react'

export default function InsightsPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()

  const { data, isLoading } = useQuery({ queryKey: ['insights'], queryFn: insightsApi.get })
  const { data: comparison } = useQuery({ queryKey: ['period-comparison'], queryFn: () => advancedReports.periodComparison(1) })

  const currency = data?.currency ?? 'USD'

  if (isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader section={t('nav.insights')} title={t('insights.title')} />
        <div className="space-y-3">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}</div>
      </div>
    )
  }

  const maxExp = Math.max(1, ...(data?.savings_series ?? []).map((s) => s.expense))

  return (
    <div className="space-y-6">
      <PageHeader section={t('nav.insights')} title={t('insights.title')} />

      {/* Insight cards */}
      {(data?.insights.length ?? 0) > 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          {data!.insights.map((ins, i) => (
            <div key={i} className={`rounded-xl border p-4 flex gap-3 ${
              ins.severity === 'warning' ? 'border-amber-200 bg-amber-50' :
              ins.severity === 'positive' ? 'border-emerald-200 bg-emerald-50' : 'border-border bg-card'}`}>
              <Lightbulb size={18} className={ins.severity === 'warning' ? 'text-amber-600' : ins.severity === 'positive' ? 'text-emerald-600' : 'text-sky-600'} />
              <div>
                <p className="text-sm font-medium text-foreground">{ins.title}</p>
                <p className="text-xs text-muted-foreground mt-0.5">{ins.detail}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Savings rate trend */}
        <section className="bg-card rounded-xl border border-border shadow-sm p-5">
          <h2 className="text-sm font-semibold mb-4">{t('insights.savingsTrend')}</h2>
          <div className="flex items-end gap-2 h-32">
            {(data?.savings_series ?? []).map((s) => (
              <div key={s.month} className="flex-1 flex flex-col items-center gap-1">
                <div className="w-full flex items-end justify-center h-24">
                  <div className="w-full max-w-8 rounded-t bg-rose-400/70" style={{ height: `${(s.expense / maxExp) * 100}%` }} title={formatCurrency(s.expense, currency, locale)} />
                </div>
                <span className={`text-[10px] tabular-nums ${s.savings_rate >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>{s.savings_rate}%</span>
                <span className="text-[9px] text-muted-foreground">{s.month.slice(5)}</span>
              </div>
            ))}
          </div>
        </section>

        {/* Top merchants */}
        <section className="bg-card rounded-xl border border-border shadow-sm p-5">
          <h2 className="text-sm font-semibold mb-4">{t('insights.topMerchants')}</h2>
          <div className="space-y-2">
            {(data?.top_merchants ?? []).map((m, i) => (
              <div key={i} className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-lg bg-muted flex items-center justify-center shrink-0"><Store size={13} className="text-muted-foreground" /></div>
                <span className="text-sm text-foreground truncate flex-1">{m.name}</span>
                <span className="text-xs text-muted-foreground tabular-nums">{m.count}×</span>
                <span className="text-sm font-medium tabular-nums">{formatCurrency(m.total, currency, locale)}</span>
              </div>
            ))}
            {(data?.top_merchants.length ?? 0) === 0 && <p className="text-sm text-muted-foreground">{t('insights.noData')}</p>}
          </div>
        </section>
      </div>

      {/* Category movers */}
      {(data?.movers.length ?? 0) > 0 && (
        <section className="bg-card rounded-xl border border-border shadow-sm p-5">
          <h2 className="text-sm font-semibold mb-4">{t('insights.movers')}</h2>
          <div className="grid gap-2 sm:grid-cols-2">
            {data!.movers.map((m, i) => (
              <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-muted/40">
                <span className="text-sm text-foreground">{m.category}</span>
                <span className={`text-sm font-medium tabular-nums flex items-center gap-1 ${m.direction === 'up' ? 'text-rose-600' : 'text-emerald-600'}`}>
                  {m.direction === 'up' ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
                  {formatCurrency(m.current, currency, locale)} ({m.change_pct > 0 ? '+' : ''}{m.change_pct}%)
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Period comparison (advanced report) */}
      {comparison && comparison.rows.length > 0 && (
        <section className="bg-card rounded-xl border border-border shadow-sm p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold">{t('insights.periodComparison')}</h2>
            <span className="text-xs text-muted-foreground tabular-nums">
              {formatCurrency(comparison.previous_total, comparison.currency, locale)} → {formatCurrency(comparison.current_total, comparison.currency, locale)}
            </span>
          </div>
          <div className="space-y-1.5">
            {comparison.rows.slice(0, 10).map((r, i) => (
              <div key={i} className="flex items-center justify-between text-sm">
                <span className="text-foreground truncate flex-1">{r.category}</span>
                <span className={`tabular-nums flex items-center gap-1 ${r.change > 0 ? 'text-rose-600' : 'text-emerald-600'}`}>
                  {r.change > 0 ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
                  {formatCurrency(Math.abs(r.change), comparison.currency, locale)}
                  {r.change_pct != null && <span className="text-xs text-muted-foreground">({r.change_pct > 0 ? '+' : ''}{r.change_pct}%)</span>}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
