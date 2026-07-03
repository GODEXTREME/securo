import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { retirement } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { usePrivacyMode } from '@/hooks/use-privacy-mode'
import { formatCurrency } from '@/lib/format'
import { Flame, PartyPopper, TrendingUp } from 'lucide-react'

export default function RetirementPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const { mask } = usePrivacyMode()

  const { data: defaults, isLoading: defaultsLoading } = useQuery({
    queryKey: ['retirement-defaults'],
    queryFn: retirement.defaults,
  })

  // null → follow the server-suggested contribution until the user edits it.
  const [contribution, setContribution] = useState<number | null>(null)
  const [annualReturn, setAnnualReturn] = useState(6)
  const [annualExpenses, setAnnualExpenses] = useState(48000)
  const [withdrawalRate, setWithdrawalRate] = useState(4)
  const [age, setAge] = useState<number | ''>('')

  const contrib = contribution ?? defaults?.suggested_monthly_contribution ?? 0
  const { data } = useQuery({
    queryKey: ['retirement-project', contrib, annualReturn, annualExpenses, withdrawalRate, age],
    queryFn: () => retirement.project({
      monthly_contribution: contrib,
      annual_return: annualReturn,
      annual_expenses: annualExpenses,
      withdrawal_rate: withdrawalRate,
      current_age: age === '' ? null : Number(age),
    }),
    enabled: !!defaults,
  })

  const currency = data?.currency ?? defaults?.currency ?? 'BRL'
  const fmt = (n: number) => mask(formatCurrency(n, currency, locale))

  const chartData = (data?.series ?? []).map((p) => ({ year: p.year, value: p.value }))

  return (
    <div className="space-y-6">
      <PageHeader section={t('nav.retirement')} title={t('retirement.title')} />

      {defaultsLoading ? (
        <Skeleton className="h-40 rounded-xl" />
      ) : (
        <>
          {/* Inputs */}
          <div className="bg-card rounded-xl border border-border shadow-sm p-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <Label className="text-xs">{t('retirement.currentNetWorth')}</Label>
              <p className="text-lg font-semibold tabular-nums mt-1">{fmt(data?.current_net_worth ?? defaults?.current_net_worth ?? 0)}</p>
              <p className="text-[11px] text-muted-foreground">{t('retirement.autoFromAccounts')}</p>
            </div>
            <div>
              <Label className="text-xs">{t('retirement.monthlyContribution')}</Label>
              <Input type="number" min={0} step={100} value={contrib}
                onChange={(e) => setContribution(Math.max(0, Number(e.target.value) || 0))} className="mt-1" />
              {defaults ? <p className="text-[11px] text-muted-foreground">{t('retirement.suggested')}: {fmt(defaults.suggested_monthly_contribution)}</p> : null}
            </div>
            <div>
              <Label className="text-xs">{t('retirement.annualExpenses')}</Label>
              <Input type="number" min={0} step={1000} value={annualExpenses}
                onChange={(e) => setAnnualExpenses(Math.max(0, Number(e.target.value) || 0))} className="mt-1" />
            </div>
            <div>
              <Label className="text-xs">{t('retirement.annualReturn')} (%)</Label>
              <Input type="number" min={0} max={100} step={0.5} value={annualReturn}
                onChange={(e) => setAnnualReturn(Math.max(0, Number(e.target.value) || 0))} className="mt-1" />
            </div>
            <div>
              <Label className="text-xs">{t('retirement.withdrawalRate')} (%)</Label>
              <Input type="number" min={0.5} max={100} step={0.5} value={withdrawalRate}
                onChange={(e) => setWithdrawalRate(Math.max(0.5, Number(e.target.value) || 0.5))} className="mt-1" />
            </div>
            <div>
              <Label className="text-xs">{t('retirement.currentAge')}</Label>
              <Input type="number" min={0} max={120} step={1} value={age}
                placeholder={t('retirement.optional')}
                onChange={(e) => setAge(e.target.value === '' ? '' : Math.max(0, Number(e.target.value) || 0))} className="mt-1" />
            </div>
          </div>

          {data && (
            <>
              {/* Headline result */}
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Stat icon={<Flame size={16} className="text-orange-500" />} label={t('retirement.fireNumber')}
                  value={fmt(data.fire_number)} hint={t('retirement.fireNumberHint', { x: (100 / withdrawalRate).toFixed(0) })} />
                <Stat icon={<TrendingUp size={16} className="text-emerald-500" />} label={t('retirement.progress')}
                  value={`${data.progress_pct}%`} hint={t('retirement.progressHint')} />
                <Stat icon={<PartyPopper size={16} className="text-indigo-500" />} label={t('retirement.timeToFire')}
                  value={data.reached && data.years_to_fire != null ? t('retirement.yearsValue', { years: data.years_to_fire }) : t('retirement.notReached')}
                  hint={data.fire_date ? new Date(data.fire_date).toLocaleDateString(locale, { year: 'numeric', month: 'long' }) : t('retirement.increaseContribution')} />
                <Stat icon={<TrendingUp size={16} className="text-sky-500" />} label={t('retirement.monthlyIncomeAtFire')}
                  value={fmt(data.monthly_income_at_fire)}
                  hint={data.age_at_fire != null ? t('retirement.atAge', { age: data.age_at_fire }) : ''} />
              </div>

              {/* Progress bar */}
              <div className="bg-card rounded-xl border border-border shadow-sm p-5">
                <div className="flex justify-between text-xs text-muted-foreground mb-1.5">
                  <span>{fmt(data.current_net_worth)}</span>
                  <span>{fmt(data.fire_number)}</span>
                </div>
                <div className="h-3 rounded-full bg-muted overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-emerald-400 to-emerald-600 rounded-full transition-all"
                    style={{ width: `${Math.min(100, data.progress_pct)}%` }} />
                </div>
              </div>

              {/* Growth chart */}
              <div className="bg-card rounded-xl border border-border shadow-sm p-5">
                <h2 className="text-sm font-semibold mb-4">{t('retirement.projectedGrowth')}</h2>
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                      <XAxis dataKey="year" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} width={64}
                        tickFormatter={(v) => new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(v))} />
                      <Tooltip formatter={(v) => fmt(Number(v) || 0)} labelFormatter={(l) => String(l)} />
                      {data.fire_number > 0 && (
                        <ReferenceLine y={data.fire_number} stroke="#F97316" strokeDasharray="4 4"
                          label={{ value: 'FIRE', position: 'insideTopRight', fontSize: 11, fill: '#F97316' }} />
                      )}
                      <Area type="monotone" dataKey="value" stroke="#10B981" fill="#10B981" fillOpacity={0.15} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}

function Stat({ icon, label, value, hint }: { icon: React.ReactNode; label: string; value: string; hint?: string }) {
  return (
    <div className="bg-card rounded-xl border border-border shadow-sm p-4">
      <div className="flex items-center gap-2 mb-1.5">{icon}<span className="text-xs text-muted-foreground">{label}</span></div>
      <p className="text-xl font-bold tabular-nums">{value}</p>
      {hint ? <p className="text-[11px] text-muted-foreground mt-0.5">{hint}</p> : null}
    </div>
  )
}
