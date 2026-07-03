import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { fixedIncome, type FixedIncomeOption } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { usePrivacyMode } from '@/hooks/use-privacy-mode'
import { formatCurrency } from '@/lib/format'
import { Landmark, Trash2, Trophy, Zap } from 'lucide-react'

const RATE_KINDS: FixedIncomeOption['rate_kind'][] = ['cdi', 'prefixed', 'ipca_plus']

export default function FixedIncomePage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const { mask } = usePrivacyMode()
  const queryClient = useQueryClient()

  // Assumptions.
  const [amount, setAmount] = useState(1000)
  const [horizon, setHorizon] = useState(365)
  const [cdi, setCdi] = useState(10.5)
  const [ipca, setIpca] = useState(4)

  // New-option form.
  const [name, setName] = useState('')
  const [institution, setInstitution] = useState('')
  const [productType, setProductType] = useState('CDB')
  const [rateKind, setRateKind] = useState<FixedIncomeOption['rate_kind']>('cdi')
  const [rate, setRate] = useState(100)
  const [liquidity, setLiquidity] = useState<'daily' | 'maturity'>('daily')
  const [taxExempt, setTaxExempt] = useState(false)

  const { data: comparison } = useQuery({
    queryKey: ['fixed-income-compare', amount, horizon, cdi, ipca],
    queryFn: () => fixedIncome.compare({ amount, horizon_days: horizon, cdi, ipca }),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['fixed-income-compare'] })
  const createMutation = useMutation({
    mutationFn: () => fixedIncome.create({
      name, institution: institution || null, product_type: productType,
      rate_kind: rateKind, rate, liquidity, tax_exempt: taxExempt,
    }),
    onSuccess: () => { invalidate(); setName(''); setInstitution(''); setRate(100); toast.success(t('fixedIncome.added')) },
    onError: () => toast.error(t('common.error')),
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => fixedIncome.remove(id),
    onSuccess: () => { invalidate(); toast.success(t('fixedIncome.removed')) },
    onError: () => toast.error(t('common.error')),
  })

  const options = comparison?.options ?? []
  const fmt = (n: number) => mask(formatCurrency(n, 'BRL', locale))
  const rateLabel = (o: { rate_kind: string; rate: number }) => {
    if (o.rate_kind === 'cdi') return `${o.rate}% CDI`
    if (o.rate_kind === 'ipca_plus') return `IPCA + ${o.rate}%`
    return `${o.rate}% a.a.`
  }

  return (
    <div className="space-y-6">
      <PageHeader section={t('nav.fixedIncome')} title={t('fixedIncome.title')} />

      {/* Assumptions */}
      <div className="bg-card rounded-xl border border-border shadow-sm p-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <Label className="text-xs">{t('fixedIncome.amount')}</Label>
          <Input type="number" min={0} step={100} value={amount}
            onChange={(e) => setAmount(Math.max(0, Number(e.target.value) || 0))} className="mt-1" />
        </div>
        <div>
          <Label className="text-xs">{t('fixedIncome.horizonDays')}</Label>
          <Input type="number" min={1} step={30} value={horizon}
            onChange={(e) => setHorizon(Math.max(1, Number(e.target.value) || 1))} className="mt-1" />
        </div>
        <div>
          <Label className="text-xs">CDI (% a.a.)</Label>
          <Input type="number" min={0} step={0.1} value={cdi}
            onChange={(e) => setCdi(Math.max(0, Number(e.target.value) || 0))} className="mt-1" />
        </div>
        <div>
          <Label className="text-xs">IPCA (% a.a.)</Label>
          <Input type="number" min={0} step={0.1} value={ipca}
            onChange={(e) => setIpca(Math.max(0, Number(e.target.value) || 0))} className="mt-1" />
        </div>
      </div>
      {comparison ? (
        <p className="text-[11px] text-muted-foreground -mt-3">
          {t('fixedIncome.irNote', { rate: comparison.ir_rate })}
        </p>
      ) : null}

      {/* Add form */}
      <div className="bg-card rounded-xl border border-border shadow-sm p-5">
        <h2 className="text-sm font-semibold mb-3">{t('fixedIncome.addOption')}</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="lg:col-span-2">
            <Label className="text-xs">{t('fixedIncome.name')}</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="CDB Banco X" className="mt-1" />
          </div>
          <div>
            <Label className="text-xs">{t('fixedIncome.institution')}</Label>
            <Input value={institution} onChange={(e) => setInstitution(e.target.value)} className="mt-1" />
          </div>
          <div>
            <Label className="text-xs">{t('fixedIncome.productType')}</Label>
            <Input value={productType} onChange={(e) => setProductType(e.target.value)} className="mt-1" />
          </div>
          <div>
            <Label className="text-xs">{t('fixedIncome.rateKind')}</Label>
            <select value={rateKind} onChange={(e) => setRateKind(e.target.value as FixedIncomeOption['rate_kind'])}
              className="mt-1 w-full h-9 rounded-lg border border-border bg-background px-2 text-sm">
              {RATE_KINDS.map((k) => <option key={k} value={k}>{t(`fixedIncome.rateKind_${k}`)}</option>)}
            </select>
          </div>
          <div>
            <Label className="text-xs">{t('fixedIncome.rate')}</Label>
            <Input type="number" min={0} step={0.1} value={rate}
              onChange={(e) => setRate(Math.max(0, Number(e.target.value) || 0))} className="mt-1" />
          </div>
          <div>
            <Label className="text-xs">{t('fixedIncome.liquidity')}</Label>
            <select value={liquidity} onChange={(e) => setLiquidity(e.target.value as 'daily' | 'maturity')}
              className="mt-1 w-full h-9 rounded-lg border border-border bg-background px-2 text-sm">
              <option value="daily">{t('fixedIncome.liquidityDaily')}</option>
              <option value="maturity">{t('fixedIncome.liquidityMaturity')}</option>
            </select>
          </div>
          <label className="flex items-center gap-2 mt-6 text-sm cursor-pointer">
            <input type="checkbox" checked={taxExempt} onChange={(e) => setTaxExempt(e.target.checked)} className="rounded" />
            {t('fixedIncome.taxExempt')}
          </label>
        </div>
        <Button className="mt-4" disabled={!name || createMutation.isPending} onClick={() => createMutation.mutate()}>
          {t('fixedIncome.add')}
        </Button>
      </div>

      {/* Comparison table */}
      {options.length === 0 ? (
        <div className="bg-card rounded-xl border border-dashed border-border p-10 text-center">
          <Landmark size={26} className="mx-auto mb-2 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">{t('fixedIncome.emptyHint')}</p>
        </div>
      ) : (
        <div className="bg-card rounded-xl border border-border shadow-sm overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground border-b border-border">
                <th className="text-left font-medium px-4 py-2.5">{t('fixedIncome.option')}</th>
                <th className="text-right font-medium px-3 py-2.5 whitespace-nowrap">{t('fixedIncome.headlineRate')}</th>
                <th className="text-right font-medium px-3 py-2.5 whitespace-nowrap">{t('fixedIncome.netAnnual')}</th>
                <th className="text-right font-medium px-3 py-2.5 whitespace-nowrap">{t('fixedIncome.netEarnings')}</th>
                <th className="text-right font-medium px-3 py-2.5 whitespace-nowrap">{t('fixedIncome.finalAmount')}</th>
                <th className="px-3 py-2.5"></th>
              </tr>
            </thead>
            <tbody>
              {options.map((o) => {
                const isBest = o.id === comparison?.best_id
                const isBestDaily = o.id === comparison?.best_daily_id
                return (
                  <tr key={o.id} className={`border-b border-muted last:border-0 ${isBest ? 'bg-emerald-500/5' : ''}`}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{o.name}</span>
                        {isBest && <span className="inline-flex items-center gap-1 text-[10px] font-medium text-emerald-700 bg-emerald-500/10 rounded-full px-1.5 py-0.5"><Trophy size={10} />{t('fixedIncome.best')}</span>}
                        {isBestDaily && !isBest && <span className="inline-flex items-center gap-1 text-[10px] font-medium text-sky-700 bg-sky-500/10 rounded-full px-1.5 py-0.5"><Zap size={10} />{t('fixedIncome.bestDaily')}</span>}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {[o.institution, o.product_type, o.liquidity === 'daily' ? t('fixedIncome.liquidityDaily') : t('fixedIncome.liquidityMaturity'), o.tax_exempt ? t('fixedIncome.taxExemptShort') : null].filter(Boolean).join(' · ')}
                      </p>
                    </td>
                    <td className="px-3 py-3 text-right whitespace-nowrap tabular-nums">{rateLabel(o)}</td>
                    <td className="px-3 py-3 text-right whitespace-nowrap tabular-nums font-semibold text-emerald-600">{o.net_annual}%</td>
                    <td className="px-3 py-3 text-right whitespace-nowrap tabular-nums">{fmt(o.net_earnings)}</td>
                    <td className="px-3 py-3 text-right whitespace-nowrap tabular-nums font-medium">{fmt(o.final_amount)}</td>
                    <td className="px-3 py-3 text-right">
                      <button onClick={() => deleteMutation.mutate(o.id)} className="text-muted-foreground hover:text-rose-600">
                        <Trash2 size={15} />
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
