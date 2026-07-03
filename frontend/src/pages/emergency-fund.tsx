import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { emergencyFund, accounts as accountsApi, type EmergencyFund } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { usePrivacyMode } from '@/hooks/use-privacy-mode'
import { formatCurrency } from '@/lib/format'
import { ShieldCheck, CalendarClock, Wallet } from 'lucide-react'

export default function EmergencyFundPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const { mask } = usePrivacyMode()
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({ queryKey: ['emergency-fund'], queryFn: emergencyFund.get })
  const { data: accounts } = useQuery({ queryKey: ['accounts'], queryFn: () => accountsApi.list() })

  // Draft state seeded from the server value; null until loaded.
  const [draft, setDraft] = useState<Partial<EmergencyFund> | null>(null)
  const view = { ...(data ?? {}), ...(draft ?? {}) } as EmergencyFund

  const saveMutation = useMutation({
    mutationFn: (payload: Partial<EmergencyFund>) => emergencyFund.update({
      target_months: payload.target_months,
      current_amount: payload.current_amount,
      account_id: payload.account_id ?? null,
      monthly_contribution: payload.monthly_contribution ?? null,
    }),
    onSuccess: (fresh) => {
      queryClient.setQueryData(['emergency-fund'], fresh)
      setDraft(null)
      toast.success(t('emergencyFund.saved'))
    },
    onError: () => toast.error(t('common.error')),
  })

  const currency = view.currency ?? 'BRL'
  const fmt = (n: number) => mask(formatCurrency(n ?? 0, currency, locale))
  const usingAccount = !!view.account_id
  const set = (patch: Partial<EmergencyFund>) => setDraft((d) => ({ ...(d ?? {}), ...patch }))

  return (
    <div className="space-y-6">
      <PageHeader section={t('nav.emergencyFund')} title={t('emergencyFund.title')} />

      {isLoading || !data ? (
        <Skeleton className="h-40 rounded-xl" />
      ) : (
        <>
          {/* Headline */}
          <div className="grid gap-4 sm:grid-cols-3">
            <Stat icon={<ShieldCheck size={16} className="text-emerald-500" />} label={t('emergencyFund.target')}
              value={fmt(view.target_amount)} hint={t('emergencyFund.targetHint', { months: view.target_months, avg: fmt(view.avg_monthly_expense) })} />
            <Stat icon={<Wallet size={16} className="text-indigo-500" />} label={t('emergencyFund.savedAmount')}
              value={fmt(view.saved_amount)} hint={t('emergencyFund.monthsCovered', { months: view.months_covered })} />
            <Stat icon={<CalendarClock size={16} className="text-amber-500" />} label={t('emergencyFund.timeToComplete')}
              value={view.shortfall <= 0 ? t('emergencyFund.complete') : (view.months_to_complete != null ? t('emergencyFund.monthsValue', { months: view.months_to_complete }) : t('emergencyFund.setContribution'))}
              hint={view.shortfall > 0 ? t('emergencyFund.shortfall', { amount: fmt(view.shortfall) }) : ''} />
          </div>

          {/* Progress */}
          <div className="bg-card rounded-xl border border-border shadow-sm p-5">
            <div className="flex justify-between text-xs text-muted-foreground mb-1.5">
              <span>{view.progress_pct}%</span>
              <span>{fmt(view.target_amount)}</span>
            </div>
            <div className="h-3 rounded-full bg-muted overflow-hidden">
              <div className={`h-full rounded-full transition-all ${view.progress_pct >= 100 ? 'bg-emerald-500' : 'bg-gradient-to-r from-amber-400 to-emerald-500'}`}
                style={{ width: `${Math.min(100, view.progress_pct)}%` }} />
            </div>
          </div>

          {/* Config */}
          <div className="bg-card rounded-xl border border-border shadow-sm p-5">
            <h2 className="text-sm font-semibold mb-4">{t('emergencyFund.settings')}</h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <Label className="text-xs">{t('emergencyFund.targetMonths')}</Label>
                <Input type="number" min={1} max={36} step={1} value={view.target_months}
                  onChange={(e) => set({ target_months: Math.max(1, Number(e.target.value) || 1) })} className="mt-1" />
              </div>
              <div>
                <Label className="text-xs">{t('emergencyFund.linkedAccount')}</Label>
                <select value={view.account_id ?? ''} onChange={(e) => set({ account_id: e.target.value || null })}
                  className="mt-1 w-full h-9 rounded-lg border border-border bg-background px-2 text-sm">
                  <option value="">{t('emergencyFund.manualAmount')}</option>
                  {(accounts ?? []).map((a) => <option key={a.id} value={a.id}>{a.display_name || a.name}</option>)}
                </select>
              </div>
              <div>
                <Label className="text-xs">{t('emergencyFund.currentAmount')}</Label>
                <Input type="number" min={0} step={100} value={view.current_amount} disabled={usingAccount}
                  onChange={(e) => set({ current_amount: Math.max(0, Number(e.target.value) || 0) })} className="mt-1" />
                {usingAccount ? <p className="text-[11px] text-muted-foreground">{t('emergencyFund.usingAccount', { name: view.account_name })}</p> : null}
              </div>
              <div>
                <Label className="text-xs">{t('emergencyFund.monthlyContribution')}</Label>
                <Input type="number" min={0} step={50} value={view.monthly_contribution ?? 0}
                  onChange={(e) => set({ monthly_contribution: Math.max(0, Number(e.target.value) || 0) })} className="mt-1" />
              </div>
            </div>
            <Button className="mt-4" disabled={!draft || saveMutation.isPending} onClick={() => saveMutation.mutate(view)}>
              {t('emergencyFund.save')}
            </Button>
          </div>
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
