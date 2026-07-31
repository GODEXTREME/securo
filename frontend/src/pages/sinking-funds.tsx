import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { sinkingFunds as fundsApi, roundups as roundupsApi, type SinkingFund } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { DatePickerInput } from '@/components/ui/date-picker-input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { useAuth } from '@/contexts/auth-context'
import { formatCurrency } from '@/lib/format'
import { PiggyBank, Plus, Pencil, Trash2, Minus } from 'lucide-react'

const SWATCHES = ['#6366F1', '#0EA5E9', '#10B981', '#F59E0B', '#EF4444', '#EC4899', '#8B5CF6', '#64748B']

export default function SinkingFundsPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const { user } = useAuth()
  const userCurrency = user?.preferences?.currency_display ?? 'USD'
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<SinkingFund | null>(null)
  const [contributing, setContributing] = useState<SinkingFund | null>(null)

  const { data: funds, isLoading } = useQuery({ queryKey: ['sinking-funds'], queryFn: () => fundsApi.list() })
  const { data: summary } = useQuery({ queryKey: ['sinking-funds', 'summary'], queryFn: fundsApi.summary })
  const [roundupMultiplier, setRoundupMultiplier] = useState(1)
  const [sweepFundId, setSweepFundId] = useState('')
  const { data: roundup } = useQuery({
    queryKey: ['roundups', roundupMultiplier],
    queryFn: () => roundupsApi.get(1, roundupMultiplier),
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['sinking-funds'] })
  }

  const createMutation = useMutation({
    mutationFn: (payload: Partial<SinkingFund>) => fundsApi.create(payload),
    onSuccess: () => { invalidate(); setDialogOpen(false); toast.success(t('sinkingFunds.created')) },
    onError: () => toast.error(t('common.error')),
  })
  const updateMutation = useMutation({
    mutationFn: ({ id, ...payload }: { id: string } & Partial<SinkingFund>) => fundsApi.update(id, payload),
    onSuccess: () => { invalidate(); setDialogOpen(false); setEditing(null); toast.success(t('sinkingFunds.updated')) },
    onError: () => toast.error(t('common.error')),
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => fundsApi.remove(id),
    onSuccess: () => { invalidate(); toast.success(t('sinkingFunds.deleted')) },
  })
  const contributeMutation = useMutation({
    mutationFn: ({ id, amount }: { id: string; amount: number }) => fundsApi.contribute(id, amount),
    onSuccess: () => { invalidate(); setContributing(null); toast.success(t('sinkingFunds.contributed')) },
    onError: () => toast.error(t('common.error')),
  })

  return (
    <div className="space-y-6">
      <PageHeader
        section={t('nav.sinkingFunds')}
        title={t('sinkingFunds.title')}
        action={
          <Button className="gap-1.5" onClick={() => { setEditing(null); setDialogOpen(true) }}>
            <Plus size={16} /> {t('sinkingFunds.add')}
          </Button>
        }
      />

      {summary && summary.count > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <Stat label={t('sinkingFunds.totalSaved')} value={formatCurrency(summary.total_saved, userCurrency, locale)} />
          <Stat label={t('sinkingFunds.totalTarget')} value={formatCurrency(summary.total_target, userCurrency, locale)} />
          <Stat label={t('sinkingFunds.monthlyNeeded')} value={formatCurrency(summary.monthly_needed, userCurrency, locale)} />
        </div>
      )}

      {/* Round-ups */}
      {roundup && roundup.roundup_total > 0 && (funds?.length ?? 0) > 0 && (
        <div className="rounded-xl border border-primary/30 bg-primary/5 p-5">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <p className="text-sm font-medium text-foreground flex items-center gap-1.5">
                <Plus size={14} className="text-primary" />
                {t('sinkingFunds.roundupTitle')}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                {t('sinkingFunds.roundupHint', { count: roundup.transaction_count, amount: formatCurrency(roundup.roundup_total, roundup.currency, locale) })}
              </p>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <div className="flex items-center rounded-lg border border-border overflow-hidden">
                {[1, 2, 5].map((m) => (
                  <button key={m} onClick={() => setRoundupMultiplier(m)}
                    className={`px-2.5 py-1 text-xs font-semibold ${roundupMultiplier === m ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground'}`}>{m}×</button>
                ))}
              </div>
              <select className="text-sm border border-border rounded-lg px-2 py-1.5 bg-card"
                value={sweepFundId} onChange={(e) => setSweepFundId(e.target.value)}>
                <option value="">{t('sinkingFunds.chooseFund')}</option>
                {funds!.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
              <Button size="sm" disabled={!sweepFundId || contributeMutation.isPending}
                onClick={() => { contributeMutation.mutate({ id: sweepFundId, amount: roundup.roundup_total }); setSweepFundId('') }}>
                {t('sinkingFunds.sweep')}
              </Button>
            </div>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-32 rounded-xl" />)}</div>
      ) : (funds?.length ?? 0) === 0 ? (
        <div className="bg-card rounded-xl border border-dashed border-border p-10 text-center">
          <PiggyBank size={28} className="mx-auto mb-2 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">{t('sinkingFunds.empty')}</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {funds!.map((f) => (
            <div key={f.id} className="bg-card rounded-xl border border-border shadow-sm p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2 min-w-0">
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0" style={{ backgroundColor: (f.color ?? '#6366F1') + '22', color: f.color ?? '#6366F1' }}>
                    <PiggyBank size={16} />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">{f.name}</p>
                    {f.target_date && <p className="text-[11px] text-muted-foreground">{t('sinkingFunds.by')} {f.target_date}</p>}
                  </div>
                </div>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted" onClick={() => { setEditing(f); setDialogOpen(true) }}><Pencil size={13} /></button>
                  <button className="p-1.5 rounded-md text-muted-foreground hover:text-rose-500 hover:bg-rose-50" onClick={() => deleteMutation.mutate(f.id)}><Trash2 size={13} /></button>
                </div>
              </div>

              <div className="mt-4">
                <div className="flex items-baseline justify-between mb-1">
                  <span className="text-lg font-semibold tabular-nums">{formatCurrency(f.current_amount, f.currency, locale)}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">/ {formatCurrency(f.target_amount, f.currency, locale)}</span>
                </div>
                <div className="h-2 rounded-full bg-muted overflow-hidden">
                  <div className="h-full rounded-full transition-all" style={{ width: `${f.percentage}%`, backgroundColor: f.color ?? '#6366F1' }} />
                </div>
                <div className="flex items-center justify-between mt-2">
                  <span className="text-[11px] text-muted-foreground">
                    {f.suggested_monthly ? t('sinkingFunds.suggested', { amount: formatCurrency(f.suggested_monthly, f.currency, locale) }) : `${f.percentage}%`}
                  </span>
                  <Button variant="outline" size="sm" className="h-7 gap-1 text-xs" onClick={() => setContributing(f)}>
                    <Plus size={12} /> {t('sinkingFunds.contribute')}
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create / edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={(o) => { if (!o) { setDialogOpen(false); setEditing(null) } }}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editing ? t('sinkingFunds.edit') : t('sinkingFunds.add')}</DialogTitle></DialogHeader>
          <FundForm
            fund={editing}
            defaultCurrency={userCurrency}
            loading={createMutation.isPending || updateMutation.isPending}
            onSubmit={(payload) => {
              if (editing) updateMutation.mutate({ id: editing.id, ...payload })
              else createMutation.mutate(payload)
            }}
          />
        </DialogContent>
      </Dialog>

      {/* Contribute dialog */}
      <Dialog open={!!contributing} onOpenChange={(o) => { if (!o) setContributing(null) }}>
        <DialogContent>
          <DialogHeader><DialogTitle>{contributing?.name}</DialogTitle></DialogHeader>
          <ContributeForm
            currency={contributing?.currency ?? userCurrency}
            locale={locale}
            loading={contributeMutation.isPending}
            onSubmit={(amount) => contributing && contributeMutation.mutate({ id: contributing.id, amount })}
          />
        </DialogContent>
      </Dialog>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-card rounded-xl border border-border px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold tabular-nums text-foreground">{value}</p>
    </div>
  )
}

function FundForm({ fund, defaultCurrency, loading, onSubmit }: {
  fund: SinkingFund | null; defaultCurrency: string; loading: boolean
  onSubmit: (payload: Partial<SinkingFund>) => void
}) {
  const { t } = useTranslation()
  const [name, setName] = useState(fund?.name ?? '')
  const [target, setTarget] = useState(fund?.target_amount?.toString() ?? '')
  const [current, setCurrent] = useState(fund?.current_amount?.toString() ?? '0')
  const [targetDate, setTargetDate] = useState(fund?.target_date ?? '')
  const [color, setColor] = useState(fund?.color ?? SWATCHES[0])

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit({
          name,
          target_amount: parseFloat(target),
          current_amount: parseFloat(current || '0'),
          currency: fund?.currency ?? defaultCurrency,
          target_date: targetDate || null,
          color,
        })
      }}
      className="space-y-4"
    >
      <div className="space-y-2">
        <Label>{t('sinkingFunds.name')}</Label>
        <Input value={name} onChange={(e) => setName(e.target.value)} required placeholder={t('sinkingFunds.namePlaceholder')} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>{t('sinkingFunds.target')}</Label>
          <Input type="number" step="0.01" min="0" value={target} onChange={(e) => setTarget(e.target.value)} required />
        </div>
        <div className="space-y-2">
          <Label>{t('sinkingFunds.current')}</Label>
          <Input type="number" step="0.01" min="0" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </div>
      </div>
      <div className="space-y-2">
        <Label>{t('sinkingFunds.targetDate')}</Label>
        <DatePickerInput value={targetDate} onChange={setTargetDate} className="w-full justify-start" />
      </div>
      <div className="space-y-2">
        <Label>{t('sinkingFunds.color')}</Label>
        <div className="flex gap-2">
          {SWATCHES.map((s) => (
            <button key={s} type="button" onClick={() => setColor(s)}
              aria-label={`${t('sinkingFunds.color')} ${s}`}
              aria-pressed={color === s}
              className={`w-6 h-6 rounded-full border-2 ${color === s ? 'border-foreground' : 'border-transparent'}`}
              style={{ backgroundColor: s }} />
          ))}
        </div>
      </div>
      <DialogFooter>
        <Button type="submit" disabled={loading}>{loading ? t('common.loading') : t('common.save')}</Button>
      </DialogFooter>
    </form>
  )
}

function ContributeForm({ currency, locale, loading, onSubmit }: {
  currency: string; locale: string; loading: boolean; onSubmit: (amount: number) => void
}) {
  const { t } = useTranslation()
  const [amount, setAmount] = useState('')
  const n = parseFloat(amount || '0')
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>{t('sinkingFunds.amount')}</Label>
        <Input type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} autoFocus placeholder={formatCurrency(0, currency, locale)} />
      </div>
      <DialogFooter className="gap-2">
        <Button variant="outline" className="gap-1" disabled={loading || !n} onClick={() => onSubmit(-Math.abs(n))}>
          <Minus size={14} /> {t('sinkingFunds.withdraw')}
        </Button>
        <Button className="gap-1" disabled={loading || !n} onClick={() => onSubmit(Math.abs(n))}>
          <Plus size={14} /> {t('sinkingFunds.deposit')}
        </Button>
      </DialogFooter>
    </div>
  )
}
