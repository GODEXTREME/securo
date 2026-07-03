import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { purchase } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { formatCurrency } from '@/lib/format'
import { Banknote, CreditCard, Trophy } from 'lucide-react'

export default function PurchasePlannerPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const [cashPrice, setCashPrice] = useState(950)
  const [installmentTotal, setInstallmentTotal] = useState(1000)
  const [n, setN] = useState(10)
  const [rate, setRate] = useState(10.5)
  const [ratePeriod, setRatePeriod] = useState<'annual' | 'monthly'>('annual')

  const { data } = useQuery({
    queryKey: ['cash-vs-inst', cashPrice, installmentTotal, n, rate, ratePeriod],
    queryFn: () => purchase.cashVsInstallments({
      cash_price: cashPrice, installment_total: installmentTotal, n_installments: n,
      investment_rate: rate, rate_period: ratePeriod,
    }),
    enabled: cashPrice > 0 && installmentTotal > 0 && n > 0,
  })

  const currency = data?.currency ?? 'BRL'
  const fmt = (v: number) => formatCurrency(v, currency, locale)

  return (
    <div className="space-y-6">
      <PageHeader section={t('nav.purchasePlanner')} title={t('purchase.title')} />

      <div className="bg-card rounded-xl border border-border shadow-sm p-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <Label className="text-xs">{t('purchase.cashPrice')}</Label>
          <Input type="number" min={0} step={10} value={cashPrice}
            onChange={(e) => setCashPrice(Math.max(0, Number(e.target.value) || 0))} className="mt-1" />
        </div>
        <div>
          <Label className="text-xs">{t('purchase.installmentTotal')}</Label>
          <Input type="number" min={0} step={10} value={installmentTotal}
            onChange={(e) => setInstallmentTotal(Math.max(0, Number(e.target.value) || 0))} className="mt-1" />
        </div>
        <div>
          <Label className="text-xs">{t('purchase.installments')}</Label>
          <Input type="number" min={1} max={360} step={1} value={n}
            onChange={(e) => setN(Math.max(1, Number(e.target.value) || 1))} className="mt-1" />
        </div>
        <div>
          <Label className="text-xs">{t('purchase.investmentRate')}</Label>
          <div className="flex items-center gap-2 mt-1">
            <Input type="number" min={0} step={0.1} value={rate}
              onChange={(e) => setRate(Math.max(0, Number(e.target.value) || 0))} />
            <div className="flex items-center rounded-lg border border-border overflow-hidden shrink-0">
              {(['monthly', 'annual'] as const).map((p) => (
                <button key={p} onClick={() => setRatePeriod(p)}
                  className={`px-2 py-1.5 text-xs font-semibold transition-colors ${ratePeriod === p ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                  {t(p === 'monthly' ? 'purchase.perMonth' : 'purchase.perYear')}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {data && (
        <>
          {/* Verdict */}
          <div className="bg-card rounded-xl border border-border shadow-sm p-5 text-center">
            <p className="text-sm text-muted-foreground">{t('purchase.verdict')}</p>
            <p className="text-2xl font-bold mt-1">
              {data.cheaper === 'cash' ? t('purchase.payCash') : t('purchase.payInstallments')}
            </p>
            <p className="text-sm text-emerald-600 font-medium mt-1">
              {t('purchase.savesYou', { amount: fmt(data.savings) })}
            </p>
            <p className="text-xs text-muted-foreground mt-2">
              {t('purchase.breakevenNote', { pct: data.breakeven_discount_pct, price: fmt(data.breakeven_cash_price) })}
            </p>
          </div>

          {/* Comparison */}
          <div className="grid gap-4 sm:grid-cols-2">
            <OptionCard title={t('purchase.cash')} icon={<Banknote size={18} className="text-emerald-600" />}
              chosen={data.cheaper === 'cash'} label={t('purchase.youPayNow')} value={fmt(data.cash_price)}
              pv={fmt(data.pv_cash)} sub={t('purchase.discountPct', { pct: data.nominal_discount_pct })} />
            <OptionCard title={t('purchase.installmentsTitle', { n: data.n_installments })} icon={<CreditCard size={18} className="text-indigo-500" />}
              chosen={data.cheaper === 'installments'} label={t('purchase.perInstallment')} value={fmt(data.per_installment)}
              pv={fmt(data.pv_installments)} sub={t('purchase.totalNominal', { total: fmt(data.installment_total) })} />
          </div>
        </>
      )}
    </div>
  )
}

function OptionCard({
  title, icon, chosen, label, value, pv, sub,
}: {
  title: string; icon: React.ReactNode; chosen: boolean; label: string; value: string; pv: string; sub: string
}) {
  const { t } = useTranslation()
  return (
    <div className={`rounded-xl border p-5 ${chosen ? 'border-primary ring-1 ring-primary/30 bg-primary/5' : 'border-border bg-card'}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">{icon}<h3 className="text-sm font-semibold">{title}</h3></div>
        {chosen && <span className="inline-flex items-center gap-1 text-[10px] font-medium text-primary bg-primary/10 rounded-full px-2 py-0.5"><Trophy size={11} />{t('purchase.cheaper')}</span>}
      </div>
      <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold tabular-nums">{value}</p>
      <p className="text-xs text-muted-foreground mt-1">{sub}</p>
      <p className="text-xs text-muted-foreground mt-3">{t('purchase.presentValue')}: <span className="font-medium text-foreground tabular-nums">{pv}</span></p>
    </div>
  )
}
