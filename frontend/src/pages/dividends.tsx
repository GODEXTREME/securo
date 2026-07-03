import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { assetIncome, assets as assetsApi } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { usePrivacyMode } from '@/hooks/use-privacy-mode'
import { formatCurrency } from '@/lib/format'
import { Coins, Trash2, TrendingUp } from 'lucide-react'

const KINDS = ['dividend', 'jcp', 'rent', 'interest', 'other'] as const

export default function DividendsPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const { mask } = usePrivacyMode()
  const queryClient = useQueryClient()

  const [assetId, setAssetId] = useState('')
  const [dateStr, setDateStr] = useState(new Date().toISOString().slice(0, 10))
  const [amount, setAmount] = useState(0)
  const [kind, setKind] = useState<typeof KINDS[number]>('dividend')

  const { data: summary } = useQuery({ queryKey: ['asset-income-summary'], queryFn: () => assetIncome.summary(12) })
  const { data: entries } = useQuery({ queryKey: ['asset-income'], queryFn: () => assetIncome.list() })
  const { data: assets } = useQuery({ queryKey: ['assets'], queryFn: () => assetsApi.list() })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['asset-income'] })
    queryClient.invalidateQueries({ queryKey: ['asset-income-summary'] })
  }
  const createMutation = useMutation({
    mutationFn: () => assetIncome.create({ asset_id: assetId, date: dateStr, amount, kind }),
    onSuccess: () => { invalidate(); setAmount(0); toast.success(t('dividends.added')) },
    onError: () => toast.error(t('common.error')),
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => assetIncome.remove(id),
    onSuccess: () => { invalidate(); toast.success(t('dividends.removed')) },
    onError: () => toast.error(t('common.error')),
  })

  const currency = summary?.currency ?? 'BRL'
  const fmt = (n: number) => mask(formatCurrency(n, currency, locale))
  const chartData = (summary?.series ?? []).map((s) => ({ month: s.month.slice(5), total: s.total }))

  return (
    <div className="space-y-6">
      <PageHeader section={t('nav.dividends')} title={t('dividends.title')} />

      {summary && (
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat icon={<Coins size={16} className="text-amber-500" />} label={t('dividends.total12m')} value={fmt(summary.total)} />
          <Stat icon={<TrendingUp size={16} className="text-emerald-500" />} label={t('dividends.monthlyAvg')} value={fmt(summary.monthly_average)} />
          <Stat icon={<Coins size={16} className="text-indigo-500" />} label={t('dividends.assetsPaying')} value={String(summary.by_asset.length)} />
        </div>
      )}

      {/* Monthly chart */}
      {chartData.some((d) => d.total > 0) && (
        <div className="bg-card rounded-xl border border-border shadow-sm p-5">
          <h2 className="text-sm font-semibold mb-4">{t('dividends.monthlyIncome')}</h2>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} width={56}
                  tickFormatter={(v) => new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(v))} />
                <Tooltip formatter={(v) => fmt(Number(v) || 0)} />
                <Bar dataKey="total" fill="#F59E0B" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Add + entries */}
        <div className="space-y-4">
          <div className="bg-card rounded-xl border border-border shadow-sm p-5">
            <h2 className="text-sm font-semibold mb-3">{t('dividends.addEntry')}</h2>
            <div className="space-y-3">
              <div>
                <Label className="text-xs">{t('dividends.asset')}</Label>
                <select value={assetId} onChange={(e) => setAssetId(e.target.value)}
                  className="mt-1 w-full h-9 rounded-lg border border-border bg-background px-2 text-sm">
                  <option value="">{t('dividends.selectAsset')}</option>
                  {(assets ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <Label className="text-xs">{t('dividends.date')}</Label>
                  <Input type="date" value={dateStr} onChange={(e) => setDateStr(e.target.value)} className="mt-1" />
                </div>
                <div>
                  <Label className="text-xs">{t('dividends.amount')}</Label>
                  <Input type="number" min={0} step={0.01} value={amount}
                    onChange={(e) => setAmount(Math.max(0, Number(e.target.value) || 0))} className="mt-1" />
                </div>
                <div>
                  <Label className="text-xs">{t('dividends.kind')}</Label>
                  <select value={kind} onChange={(e) => setKind(e.target.value as typeof KINDS[number])}
                    className="mt-1 w-full h-9 rounded-lg border border-border bg-background px-2 text-sm">
                    {KINDS.map((k) => <option key={k} value={k}>{t(`dividends.kind_${k}`)}</option>)}
                  </select>
                </div>
              </div>
              <Button className="w-full" disabled={!assetId || amount <= 0 || createMutation.isPending}
                onClick={() => createMutation.mutate()}>{t('dividends.add')}</Button>
            </div>
          </div>

          <div className="bg-card rounded-xl border border-border shadow-sm divide-y divide-muted">
            {!entries || entries.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">{t('dividends.noEntries')}</p>
            ) : entries.map((e) => (
              <div key={e.id} className="flex items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">{e.asset_name}</p>
                  <p className="text-xs text-muted-foreground">{new Date(e.date).toLocaleDateString(locale)} · {t(`dividends.kind_${e.kind}`)}</p>
                </div>
                <span className="text-sm font-semibold tabular-nums text-emerald-600">{fmt(e.amount)}</span>
                <button onClick={() => deleteMutation.mutate(e.id)} className="text-muted-foreground hover:text-rose-600 shrink-0">
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* By asset + yield */}
        <div className="bg-card rounded-xl border border-border shadow-sm p-5">
          <h2 className="text-sm font-semibold mb-3">{t('dividends.byAsset')}</h2>
          {!summary || summary.by_asset.length === 0 ? (
            <div className="text-center py-10">
              <Coins size={26} className="mx-auto mb-2 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">{t('dividends.emptyHint')}</p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {summary.by_asset.map((a) => (
                <div key={a.asset_id} className="flex items-center gap-3">
                  <span className="text-sm min-w-0 flex-1 truncate">{a.name}</span>
                  {a.yield_pct != null && (
                    <span className="text-xs text-muted-foreground shrink-0">{t('dividends.yieldOnCost')}: {a.yield_pct}%</span>
                  )}
                  <span className="text-sm font-semibold tabular-nums text-emerald-600 shrink-0 w-24 text-right">{fmt(a.total)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="bg-card rounded-xl border border-border shadow-sm p-4">
      <div className="flex items-center gap-2 mb-1.5">{icon}<span className="text-xs text-muted-foreground">{label}</span></div>
      <p className="text-xl font-bold tabular-nums">{value}</p>
    </div>
  )
}
