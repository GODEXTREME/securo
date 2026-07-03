import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { loans, type LoanResult } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { formatCurrency } from '@/lib/format'
import { Landmark, Trophy, TrendingDown } from 'lucide-react'

export default function LoansPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const [principal, setPrincipal] = useState(50000)
  const [rate, setRate] = useState(1.99)
  const [ratePeriod, setRatePeriod] = useState<'monthly' | 'annual'>('monthly')
  const [months, setMonths] = useState(48)
  const [extra, setExtra] = useState(0)

  const { data } = useQuery({
    queryKey: ['loan-sim', principal, rate, ratePeriod, months, extra],
    queryFn: () => loans.simulate({
      principal, rate, months, rate_period: ratePeriod, extra_payment: extra, method: 'both',
    }),
    enabled: principal > 0 && months > 0,
  })

  const currency = data?.currency ?? 'BRL'
  const price = data?.results.price
  const sac = data?.results.sac

  const chartData = useMemo(() => {
    if (!price || !sac) return []
    const len = Math.max(price.schedule.length, sac.schedule.length)
    return Array.from({ length: len }, (_, i) => ({
      n: i + 1,
      price: price.schedule[i]?.balance ?? 0,
      sac: sac.schedule[i]?.balance ?? 0,
    }))
  }, [price, sac])

  return (
    <div className="space-y-6">
      <PageHeader section={t('nav.loans')} title={t('loans.title')} />

      {/* Inputs */}
      <div className="bg-card rounded-xl border border-border shadow-sm p-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <Label className="text-xs">{t('loans.principal')}</Label>
          <Input type="number" min={0} step={1000} value={principal}
            onChange={(e) => setPrincipal(Math.max(0, Number(e.target.value) || 0))} className="mt-1" />
        </div>
        <div>
          <Label className="text-xs">{t('loans.rate')}</Label>
          <div className="flex items-center gap-2 mt-1">
            <Input type="number" min={0} step={0.01} value={rate}
              onChange={(e) => setRate(Math.max(0, Number(e.target.value) || 0))} />
            <div className="flex items-center rounded-lg border border-border overflow-hidden shrink-0">
              {(['monthly', 'annual'] as const).map((p) => (
                <button key={p} onClick={() => setRatePeriod(p)}
                  className={`px-2 py-1.5 text-xs font-semibold transition-colors ${ratePeriod === p ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                  {t(p === 'monthly' ? 'loans.perMonth' : 'loans.perYear')}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div>
          <Label className="text-xs">{t('loans.termMonths')}</Label>
          <Input type="number" min={1} max={600} step={1} value={months}
            onChange={(e) => setMonths(Math.max(1, Number(e.target.value) || 1))} className="mt-1" />
        </div>
        <div>
          <Label className="text-xs">{t('loans.extraPayment')}</Label>
          <Input type="number" min={0} step={50} value={extra}
            onChange={(e) => setExtra(Math.max(0, Number(e.target.value) || 0))} className="mt-1" />
        </div>
      </div>

      {price && sac && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <MethodCard title={t('loans.price')} subtitle={t('loans.priceDesc')} result={price}
              currency={currency} locale={locale} recommended={data?.recommended === 'price'} />
            <MethodCard title={t('loans.sac')} subtitle={t('loans.sacDesc')} result={sac}
              currency={currency} locale={locale} recommended={data?.recommended === 'sac'} />
          </div>

          {/* Balance-over-time chart */}
          <div className="bg-card rounded-xl border border-border shadow-sm p-5">
            <div className="flex items-center gap-2 mb-4">
              <TrendingDown size={16} className="text-muted-foreground" />
              <h2 className="text-sm font-semibold">{t('loans.balanceOverTime')}</h2>
            </div>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="n" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} width={64}
                    tickFormatter={(v) => new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(v))} />
                  <Tooltip formatter={(v) => formatCurrency(Number(v) || 0, currency, locale)}
                    labelFormatter={(l) => `${t('loans.month')} ${l}`} />
                  <Area type="monotone" dataKey="price" name="Price" stroke="#6366F1" fill="#6366F1" fillOpacity={0.15} />
                  <Area type="monotone" dataKey="sac" name="SAC" stroke="#10B981" fill="#10B981" fillOpacity={0.15} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function MethodCard({
  title, subtitle, result, currency, locale, recommended,
}: {
  title: string; subtitle: string; result: LoanResult
  currency: string; locale: string; recommended: boolean
}) {
  const { t } = useTranslation()
  const years = Math.floor(result.months / 12)
  const rem = result.months % 12
  return (
    <div className={`rounded-xl border p-5 ${recommended ? 'border-primary ring-1 ring-primary/30 bg-primary/5' : 'border-border bg-card'}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2"><Landmark size={18} className="text-indigo-500" /><h3 className="text-sm font-semibold">{title}</h3></div>
        {recommended && <span className="inline-flex items-center gap-1 text-[10px] font-medium text-primary bg-primary/10 rounded-full px-2 py-0.5"><Trophy size={11} />{t('loans.recommended')}</span>}
      </div>
      <p className="text-xs text-muted-foreground mb-4">{subtitle}</p>
      <div className="grid grid-cols-2 gap-3">
        <Metric label={t('loans.firstPayment')} value={formatCurrency(result.first_payment, currency, locale)} />
        <Metric label={t('loans.lastPayment')} value={formatCurrency(result.last_payment, currency, locale)} />
        <Metric label={t('loans.totalInterest')} value={formatCurrency(result.total_interest, currency, locale)} accent="text-rose-600" />
        <Metric label={t('loans.totalPaid')} value={formatCurrency(result.total_paid, currency, locale)} />
        <Metric label={t('loans.payoffTime')} value={`${years > 0 ? `${years}${t('loans.y')} ` : ''}${rem}${t('loans.mo')}`} />
      </div>
    </div>
  )
}

function Metric({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div>
      <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className={`text-base font-semibold tabular-nums ${accent ?? ''}`}>{value}</p>
    </div>
  )
}
