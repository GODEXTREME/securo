import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { debt as debtApi } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { formatCurrency } from '@/lib/format'
import { CreditCard, Snowflake, Mountain, Trophy } from 'lucide-react'

export default function DebtPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const [extra, setExtra] = useState(200)

  const { data: accounts, isLoading } = useQuery({ queryKey: ['debt-accounts'], queryFn: debtApi.accounts })
  const { data: plan } = useQuery({
    queryKey: ['debt-plan', extra, accounts?.length],
    queryFn: () => debtApi.plan(extra),
    enabled: !!accounts && accounts.length > 0,
  })

  const currency = accounts?.[0]?.currency ?? 'USD'

  return (
    <div className="space-y-6">
      <PageHeader section={t('nav.debt')} title={t('debt.title')} />

      {isLoading ? (
        <Skeleton className="h-40 rounded-xl" />
      ) : !accounts || accounts.length === 0 ? (
        <div className="bg-card rounded-xl border border-dashed border-border p-10 text-center">
          <CreditCard size={28} className="mx-auto mb-2 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">{t('debt.empty')}</p>
        </div>
      ) : (
        <>
          {/* Debts list */}
          <div className="bg-card rounded-xl border border-border shadow-sm divide-y divide-muted">
            {accounts.map((d) => (
              <div key={d.id ?? d.name} className="flex items-center gap-3 px-5 py-3">
                <div className="w-9 h-9 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center shrink-0"><CreditCard size={16} /></div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{d.name}</p>
                  <p className="text-xs text-muted-foreground">{t('debt.apr')}: {d.apr}% · {t('debt.minPayment')}: {formatCurrency(d.min_payment, currency, locale)}</p>
                </div>
                <p className="text-sm font-semibold tabular-nums text-rose-600">{formatCurrency(d.balance, currency, locale)}</p>
              </div>
            ))}
          </div>

          {/* Extra payment input */}
          <div className="bg-card rounded-xl border border-border shadow-sm p-5">
            <Label className="text-sm">{t('debt.extraPayment')}</Label>
            <div className="flex items-center gap-3 mt-2">
              <Input type="number" min={0} step={50} value={extra}
                onChange={(e) => setExtra(Math.max(0, Number(e.target.value) || 0))} className="w-40" />
              <span className="text-xs text-muted-foreground">{t('debt.extraHint')}</span>
            </div>
          </div>

          {/* Strategy comparison */}
          {plan && (
            <div className="grid gap-4 sm:grid-cols-2">
              <StrategyCard
                title={t('debt.snowball')} subtitle={t('debt.snowballDesc')}
                icon={<Snowflake size={18} className="text-sky-600" />}
                result={plan.snowball} currency={currency} locale={locale}
                recommended={plan.recommended === 'snowball'} />
              <StrategyCard
                title={t('debt.avalanche')} subtitle={t('debt.avalancheDesc')}
                icon={<Mountain size={18} className="text-emerald-600" />}
                result={plan.avalanche} currency={currency} locale={locale}
                recommended={plan.recommended === 'avalanche'} />
            </div>
          )}
        </>
      )}
    </div>
  )
}

function StrategyCard({
  title, subtitle, icon, result, currency, locale, recommended,
}: {
  title: string; subtitle: string; icon: React.ReactNode
  result: { months: number; total_interest: number; payoff_date: string; order: string[]; amortized: boolean }
  currency: string; locale: string; recommended: boolean
}) {
  const { t } = useTranslation()
  const years = Math.floor(result.months / 12)
  const months = result.months % 12
  return (
    <div className={`rounded-xl border p-5 ${recommended ? 'border-primary ring-1 ring-primary/30 bg-primary/5' : 'border-border bg-card'}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">{icon}<h3 className="text-sm font-semibold">{title}</h3></div>
        {recommended && <span className="inline-flex items-center gap-1 text-[10px] font-medium text-primary bg-primary/10 rounded-full px-2 py-0.5"><Trophy size={11} />{t('debt.recommended')}</span>}
      </div>
      <p className="text-xs text-muted-foreground mb-4">{subtitle}</p>
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{t('debt.payoffTime')}</p>
          <p className="text-lg font-semibold tabular-nums">{years > 0 ? `${years}${t('debt.y')} ` : ''}{months}{t('debt.mo')}</p>
        </div>
        <div>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{t('debt.totalInterest')}</p>
          <p className="text-lg font-semibold tabular-nums text-rose-600">{formatCurrency(result.total_interest, currency, locale)}</p>
        </div>
      </div>
      {result.order.length > 0 && (
        <p className="text-[11px] text-muted-foreground">{t('debt.order')}: {result.order.join(' → ')}</p>
      )}
      {!result.amortized && <p className="text-[11px] text-rose-600 mt-1">{t('debt.notAmortizing')}</p>}
    </div>
  )
}
