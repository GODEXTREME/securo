import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { subscriptions as subscriptionsApi } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { formatCurrency } from '@/lib/format'
import { Repeat, TrendingUp, CalendarClock } from 'lucide-react'

export default function SubscriptionsPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()

  const { data, isLoading } = useQuery({
    queryKey: ['subscriptions'],
    queryFn: subscriptionsApi.list,
  })

  const subs = data?.subscriptions ?? []
  const currency = subs[0]?.currency ?? 'USD'

  return (
    <div className="space-y-6">
      <PageHeader section={t('nav.subscriptions')} title={t('subscriptions.title')} />

      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Stat label={t('subscriptions.count')} value={String(data.count)} />
          <Stat label={t('subscriptions.monthly')} value={formatCurrency(data.monthly_total, currency, locale)} />
          <Stat label={t('subscriptions.yearly')} value={formatCurrency(data.yearly_total, currency, locale)} />
          <Stat label={t('subscriptions.priceChanges')} value={String(data.price_changes)} accent={data.price_changes > 0 ? 'text-amber-600' : undefined} />
        </div>
      )}

      {isLoading ? (
        <div className="space-y-3">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}</div>
      ) : subs.length === 0 ? (
        <div className="bg-card rounded-xl border border-dashed border-border p-10 text-center">
          <Repeat size={28} className="mx-auto mb-2 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">{t('subscriptions.empty')}</p>
        </div>
      ) : (
        <div className="bg-card rounded-xl border border-border shadow-sm divide-y divide-muted">
          {subs.map((s) => (
            <div key={s.key} className="flex items-center gap-3 px-5 py-3">
              <div className="w-9 h-9 rounded-lg bg-violet-100 text-violet-600 flex items-center justify-center shrink-0">
                <Repeat size={16} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground truncate">{s.name}</p>
                <p className="text-xs text-muted-foreground flex items-center gap-2 flex-wrap">
                  <span>{t(`subscriptions.freq.${s.frequency}`, s.frequency)}</span>
                  <span className="inline-flex items-center gap-1"><CalendarClock size={11} /> {t('subscriptions.next')}: {s.next_date}</span>
                  {s.price_change && (
                    <span className="inline-flex items-center gap-1 text-amber-600"><TrendingUp size={11} /> {t('subscriptions.priceChanged')}</span>
                  )}
                </p>
              </div>
              <div className="text-right">
                <p className="text-sm font-semibold tabular-nums">{formatCurrency(s.typical_amount, s.currency, locale)}</p>
                <p className="text-[11px] text-muted-foreground tabular-nums">{formatCurrency(s.monthly_cost, s.currency, locale)}/{t('subscriptions.perMonth')}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="bg-card rounded-xl border border-border px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${accent ?? 'text-foreground'}`}>{value}</p>
    </div>
  )
}
