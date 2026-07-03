import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { healthScore as healthScoreApi } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { formatCurrency } from '@/lib/format'
import { HeartPulse } from 'lucide-react'

const BAND_COLOR: Record<string, string> = {
  excellent: 'text-emerald-600',
  good: 'text-sky-600',
  fair: 'text-amber-600',
  poor: 'text-rose-600',
}

function barColor(score: number) {
  if (score >= 80) return 'bg-emerald-500'
  if (score >= 60) return 'bg-sky-500'
  if (score >= 40) return 'bg-amber-500'
  return 'bg-rose-500'
}

export default function HealthScorePage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const { data, isLoading } = useQuery({ queryKey: ['health-score'], queryFn: healthScoreApi.get })

  if (isLoading || !data) {
    return (
      <div className="space-y-6">
        <PageHeader section={t('nav.healthScore')} title={t('healthScore.title')} />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    )
  }

  const circumference = 2 * Math.PI * 52
  const dash = (data.score / 100) * circumference

  return (
    <div className="space-y-6">
      <PageHeader section={t('nav.healthScore')} title={t('healthScore.title')} />

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Score gauge */}
        <div className="bg-card rounded-xl border border-border shadow-sm p-6 flex flex-col items-center justify-center">
          <div className="relative w-36 h-36">
            <svg viewBox="0 0 120 120" className="w-full h-full -rotate-90">
              <circle cx="60" cy="60" r="52" fill="none" strokeWidth="12" className="stroke-muted" />
              <circle cx="60" cy="60" r="52" fill="none" strokeWidth="12" strokeLinecap="round"
                className={barColor(data.score).replace('bg-', 'stroke-')}
                strokeDasharray={`${dash} ${circumference}`} />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-3xl font-bold tabular-nums">{data.score}</span>
              <span className={`text-xs font-medium capitalize ${BAND_COLOR[data.band]}`}>{t(`healthScore.band.${data.band}`, data.band)}</span>
            </div>
          </div>
          <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
            <HeartPulse size={14} /> {t('healthScore.outOf100')}
          </div>
        </div>

        {/* Components */}
        <div className="lg:col-span-2 bg-card rounded-xl border border-border shadow-sm p-6 space-y-4">
          {data.components.map((c) => (
            <div key={c.key}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-medium text-foreground">{t(`healthScore.component.${c.key}`, c.label)}</span>
                <span className="text-sm font-semibold tabular-nums">{c.score}</span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div className={`h-full rounded-full ${barColor(c.score)}`} style={{ width: `${c.score}%` }} />
              </div>
              <p className="text-xs text-muted-foreground mt-1">{c.detail}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Stat label={t('healthScore.monthlyIncome')} value={formatCurrency(data.monthly_income, data.currency, locale)} />
        <Stat label={t('healthScore.monthlyExpense')} value={formatCurrency(data.monthly_expense, data.currency, locale)} />
        <Stat label={t('healthScore.liquid')} value={formatCurrency(data.liquid_balance, data.currency, locale)} />
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-card rounded-xl border border-border px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-base font-semibold tabular-nums text-foreground">{value}</p>
    </div>
  )
}
