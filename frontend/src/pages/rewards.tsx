import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { rewards, accounts as accountsApi, categories as categoriesApi } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { MonthStepper } from '@/components/month-stepper'
import { currentMonth } from '@/lib/month-utils'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { usePrivacyMode } from '@/hooks/use-privacy-mode'
import { formatCurrency } from '@/lib/format'
import { Gift, Trash2, Trophy, CreditCard } from 'lucide-react'

export default function RewardsPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const { mask } = usePrivacyMode()
  const queryClient = useQueryClient()

  const [month, setMonth] = useState(currentMonth())
  const [yr, mo] = month.split('-').map(Number)

  const [accountId, setAccountId] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [rate, setRate] = useState(1)

  const { data: rules, isLoading } = useQuery({ queryKey: ['rewards'], queryFn: rewards.list })
  const { data: summary } = useQuery({
    queryKey: ['rewards-summary', month],
    queryFn: () => rewards.summary({ year: yr, month: mo }),
  })
  const { data: accounts } = useQuery({ queryKey: ['accounts'], queryFn: () => accountsApi.list() })
  const { data: cats } = useQuery({ queryKey: ['categories'], queryFn: () => categoriesApi.list() })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['rewards'] })
    queryClient.invalidateQueries({ queryKey: ['rewards-summary'] })
  }
  const createMutation = useMutation({
    mutationFn: () => rewards.create({ account_id: accountId, category_id: categoryId || null, rate }),
    onSuccess: () => { invalidate(); setAccountId(''); setCategoryId(''); setRate(1); toast.success(t('rewards.ruleAdded')) },
    onError: () => toast.error(t('common.error')),
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => rewards.remove(id),
    onSuccess: () => { invalidate(); toast.success(t('rewards.ruleRemoved')) },
    onError: () => toast.error(t('common.error')),
  })

  const currency = summary?.currency ?? 'BRL'
  const fmt = (n: number) => mask(formatCurrency(n, currency, locale))

  return (
    <div className="space-y-6">
      <PageHeader section={t('nav.rewards')} title={t('rewards.title')}
        action={<MonthStepper value={month} onChange={setMonth} locale={locale} />} />

      {/* Summary */}
      {summary && (
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat icon={<Gift size={16} className="text-emerald-500" />} label={t('rewards.earned')} value={fmt(summary.total_earned)} />
          <Stat icon={<CreditCard size={16} className="text-indigo-500" />} label={t('rewards.rewardedSpend')} value={fmt(summary.total_spend)} />
          <Stat icon={<Trophy size={16} className="text-amber-500" />} label={t('rewards.effectiveRate')} value={`${summary.effective_rate}%`} />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Rules */}
        <div className="space-y-4">
          <div className="bg-card rounded-xl border border-border shadow-sm p-5">
            <h2 className="text-sm font-semibold mb-3">{t('rewards.addRule')}</h2>
            <div className="space-y-3">
              <div>
                <Label className="text-xs">{t('rewards.card')}</Label>
                <select value={accountId} onChange={(e) => setAccountId(e.target.value)}
                  className="mt-1 w-full h-9 rounded-lg border border-border bg-background px-2 text-sm">
                  <option value="">{t('rewards.selectCard')}</option>
                  {(accounts ?? []).map((a) => (
                    <option key={a.id} value={a.id}>{a.display_name || a.name}</option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs">{t('rewards.category')}</Label>
                  <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}
                    className="mt-1 w-full h-9 rounded-lg border border-border bg-background px-2 text-sm">
                    <option value="">{t('rewards.allCategories')}</option>
                    {(cats ?? []).map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <Label className="text-xs">{t('rewards.rate')} (%)</Label>
                  <Input type="number" min={0} step={0.1} value={rate}
                    onChange={(e) => setRate(Math.max(0, Number(e.target.value) || 0))} className="mt-1" />
                </div>
              </div>
              <Button className="w-full" disabled={!accountId || createMutation.isPending}
                onClick={() => createMutation.mutate()}>{t('rewards.add')}</Button>
            </div>
          </div>

          <div className="bg-card rounded-xl border border-border shadow-sm divide-y divide-muted">
            {isLoading ? (
              <div className="p-5"><Skeleton className="h-16 w-full" /></div>
            ) : !rules || rules.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">{t('rewards.noRules')}</p>
            ) : rules.map((r) => (
              <div key={r.id} className="flex items-center gap-3 px-5 py-3">
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: r.category_color || '#94A3B8' }} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">{r.account_name}</p>
                  <p className="text-xs text-muted-foreground truncate">{r.category_name || t('rewards.allCategories')}</p>
                </div>
                <span className="text-sm font-semibold tabular-nums text-emerald-600">{r.rate}%</span>
                <button onClick={() => deleteMutation.mutate(r.id)} className="text-muted-foreground hover:text-rose-600 shrink-0">
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Breakdown + recommendations */}
        <div className="space-y-4">
          {summary && summary.best_per_category.length > 0 && (
            <div className="bg-card rounded-xl border border-border shadow-sm p-5">
              <h2 className="text-sm font-semibold mb-3">{t('rewards.bestCardPerCategory')}</h2>
              <div className="space-y-2">
                {summary.best_per_category.map((b, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: b.category_color || '#94A3B8' }} />
                    <span className="text-sm min-w-0 flex-1 truncate">{b.category_name || t('rewards.allCategories')}</span>
                    <span className="text-xs text-muted-foreground truncate max-w-[40%]">{b.account_name}</span>
                    <span className="text-sm font-semibold tabular-nums text-emerald-600 shrink-0">{b.rate}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {summary && summary.by_card.length > 0 && (
            <div className="bg-card rounded-xl border border-border shadow-sm p-5">
              <h2 className="text-sm font-semibold mb-3">{t('rewards.earnedByCard')}</h2>
              <div className="space-y-2">
                {summary.by_card.map((c) => (
                  <div key={c.account_id} className="flex items-center gap-3">
                    <span className="text-sm min-w-0 flex-1 truncate">{c.name}</span>
                    <span className="text-xs text-muted-foreground tabular-nums shrink-0">{fmt(c.spend)}</span>
                    <span className="text-sm font-semibold tabular-nums text-emerald-600 shrink-0 w-24 text-right">{fmt(c.earned)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {(!summary || summary.by_card.length === 0) && (
            <div className="bg-card rounded-xl border border-dashed border-border p-10 text-center">
              <Gift size={26} className="mx-auto mb-2 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">{t('rewards.emptyHint')}</p>
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
