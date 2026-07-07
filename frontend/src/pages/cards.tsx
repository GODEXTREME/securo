import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import { accounts as accountsApi, transactions as txApi, categories as categoriesApi, categoryGroups as categoryGroupsApi, advancedReports, dashboard } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { MonthStepper } from '@/components/month-stepper'
import { CategoryIcon } from '@/components/category-icon'
import { TransactionDialog, extractApiError } from '@/components/transaction-dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { currentMonth, monthRange } from '@/lib/month-utils'
import { getAccountName } from '@/lib/account-utils'
import { invalidateFinancialQueries } from '@/lib/invalidate-queries'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { usePrivacyMode } from '@/hooks/use-privacy-mode'
import { formatCurrency } from '@/lib/format'
import type { Transaction } from '@/types'
import { CreditCard, Layers } from 'lucide-react'

export default function CardsPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const { mask } = usePrivacyMode()

  const queryClient = useQueryClient()
  const { data: accounts, isLoading } = useQuery({ queryKey: ['accounts'], queryFn: () => accountsApi.list() })
  const { data: categoriesList } = useQuery({ queryKey: ['categories'], queryFn: categoriesApi.list })
  const { data: categoryGroupsList } = useQuery({ queryKey: ['category-groups'], queryFn: categoryGroupsApi.list })

  const [editingTx, setEditingTx] = useState<Transaction | null>(null)
  const invalidateTx = () => {
    invalidateFinancialQueries(queryClient)
    queryClient.invalidateQueries({ queryKey: ['card-txs'] })
    queryClient.invalidateQueries({ queryKey: ['card-breakdown'] })
    queryClient.invalidateQueries({ queryKey: ['card-projected'] })
  }
  const updateMutation = useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Partial<Transaction>) => txApi.update(id, data),
    onSuccess: () => { invalidateTx(); setEditingTx(null); toast.success(t('transactions.updated')) },
    onError: (e) => toast.error(extractApiError(e)),
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => txApi.delete(id),
    onSuccess: () => { invalidateTx(); setEditingTx(null); toast.success(t('transactions.deleted')) },
    onError: (e) => toast.error(extractApiError(e)),
  })
  // Cards with an open balance first (by nearest due date), then paid-off cards
  // (also by due date). Null due dates sort last within each group.
  const cards = (accounts ?? [])
    .filter((a) => a.type === 'credit_card' && !a.is_closed)
    .sort((a, b) => {
      const aPaid = (a.balance ?? 0) <= 0
      const bPaid = (b.balance ?? 0) <= 0
      if (aPaid !== bPaid) return aPaid ? 1 : -1
      const ad = a.next_due_date ?? ''
      const bd = b.next_due_date ?? ''
      if (!ad && !bd) return 0
      if (!ad) return 1
      if (!bd) return -1
      return ad.localeCompare(bd)
    })

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const cardId = selectedId && cards.some((c) => c.id === selectedId) ? selectedId : cards[0]?.id
  const card = cards.find((c) => c.id === cardId)

  const [month, setMonth] = useState(currentMonth())
  const [yr, mo] = month.split('-').map(Number)
  const { from, to } = monthRange(month)

  const { data: breakdown } = useQuery({
    queryKey: ['card-breakdown', cardId, month],
    queryFn: () => advancedReports.categoryBreakdown({ accountIds: [cardId!], year: yr, month: mo, flow: 'expense' }),
    enabled: !!cardId,
  })
  const { data: txs, isLoading: txLoading } = useQuery({
    queryKey: ['card-txs', cardId, month],
    queryFn: () => txApi.list({ account_id: cardId, from, to, type: 'debit', sort_by: 'date', sort_dir: 'desc', limit: 300 }),
    enabled: !!cardId,
  })
  // Installments not yet billed that will land on this card in the selected month.
  const { data: projected } = useQuery({
    queryKey: ['card-projected', month],
    queryFn: () => dashboard.projectedTransactions(`${month}-01`),
  })

  const currency = breakdown?.currency ?? card?.currency ?? 'BRL'
  const fmt = (n: number) => mask(formatCurrency(n, currency, locale))
  const groups = breakdown?.groups ?? []
  const labelOf = (name: string | null, uncat: boolean) => (uncat ? t('reports.uncategorized') : (name ?? '—'))
  const pieData = groups.map((g) => ({ name: labelOf(g.name, g.uncategorized), value: g.total, color: g.color }))

  // Merge real purchases with projected (unbilled) installments for this card.
  // The parcel number lives in the purchase text itself (the provider's title,
  // e.g. "… 3/6") — that's the source of truth, so we don't render a separate
  // badge that could disagree with it. Real rows keep the provider title as-is;
  // projected rows already come as "Merchant k/N" from the backend.
  type Row = {
    key: string; date: string; name: string; categoryName: string | null
    categoryColor: string | null; categoryIcon: string | null; amount: number
    projected: boolean; tx: Transaction | null
  }
  const realRows: Row[] = (txs?.items ?? []).map((tx) => {
    const raw = tx.payee_name || tx.payee || tx.description
    const hasNum = /\d+\s*\/\s*\d+/.test(raw)
    const name = !hasNum && tx.total_installments && tx.total_installments > 1
      ? `${raw} ${tx.installment_number}/${tx.total_installments}` : raw
    return {
      key: tx.id, date: tx.date, name,
      categoryName: tx.category?.name ?? null, categoryColor: tx.category?.color ?? null, categoryIcon: tx.category?.icon ?? null,
      amount: Math.abs(tx.amount), projected: false, tx,
    }
  })
  const projRows: Row[] = (projected ?? [])
    .filter((p) => p.kind === 'installment' && p.account_id === cardId)
    .map((p, i) => ({
      key: `proj-${i}-${p.date}`, date: p.date, name: p.description,
      categoryName: p.category_name, categoryColor: p.category_color, categoryIcon: p.category_icon,
      amount: Math.abs(p.amount), projected: true, tx: null,
    }))
  const purchaseRows = [...realRows, ...projRows].sort((a, b) => b.date.localeCompare(a.date))
  const projectedTotal = projRows.reduce((s, r) => s + r.amount, 0)

  // Limit usage (credit card balance is the amount owed).
  const owed = card?.balance ?? 0
  const limit = card?.credit_limit ?? 0
  const usage = limit > 0 ? Math.min(100, Math.round((owed / limit) * 100)) : null

  return (
    <div className="space-y-6">
      <PageHeader section={t('nav.cards')} title={t('cards.title')} />

      {isLoading ? (
        <Skeleton className="h-40 rounded-xl" />
      ) : cards.length === 0 ? (
        <div className="bg-card rounded-xl border border-dashed border-border p-10 text-center">
          <CreditCard size={28} className="mx-auto mb-2 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">{t('cards.empty')}</p>
        </div>
      ) : (
        <>
          {/* Card selector */}
          <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
            {cards.map((c) => (
              <button key={c.id} onClick={() => setSelectedId(c.id)}
                className={`shrink-0 flex items-center gap-2 rounded-xl border px-4 py-3 text-left transition-colors ${c.id === cardId ? 'border-primary ring-1 ring-primary/30 bg-primary/5' : 'border-border bg-card hover:bg-muted/50'}`}>
                {c.institution_logo_url
                  ? <img src={c.institution_logo_url} alt="" className="w-6 h-6 rounded" />
                  : <span className="w-6 h-6 rounded bg-muted flex items-center justify-center"><CreditCard size={14} /></span>}
                <span className="min-w-0">
                  <span className="block text-sm font-medium truncate max-w-[10rem]">{getAccountName(c)}</span>
                  <span className="block text-[11px] text-muted-foreground">{[c.card_brand, c.card_level].filter(Boolean).join(' · ') || t('cards.creditCard')}</span>
                </span>
              </button>
            ))}
          </div>

          {card && (
            <>
              {/* Header: balance / limit + month stepper */}
              <div className="bg-card rounded-xl border border-border shadow-sm p-5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                <div>
                  <p className="text-xs text-muted-foreground">{t('cards.currentBalance')}</p>
                  <p className="text-2xl font-bold tabular-nums">{fmt(owed)}</p>
                  {limit > 0 && (
                    <div className="mt-2 w-48 max-w-full">
                      <div className="flex justify-between text-[11px] text-muted-foreground mb-1">
                        <span>{usage}% {t('cards.ofLimit')}</span>
                        <span>{fmt(limit)}</span>
                      </div>
                      <div className="h-2 rounded-full bg-muted overflow-hidden">
                        <div className={`h-full rounded-full ${(usage ?? 0) >= 90 ? 'bg-rose-500' : 'bg-gradient-to-r from-indigo-400 to-indigo-600'}`} style={{ width: `${usage}%` }} />
                      </div>
                    </div>
                  )}
                  {card.next_due_date && (
                    <p className="text-[11px] text-muted-foreground mt-2">
                      {t('cards.dueOn', { date: new Date(card.next_due_date).toLocaleDateString(locale) })}
                    </p>
                  )}
                </div>
                <MonthStepper value={month} onChange={setMonth} locale={locale} />
              </div>

              {/* Spending summary + pie */}
              <div className="bg-card rounded-xl border border-border shadow-sm p-5">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-sm font-semibold">{t('cards.spendingByCategory')}</h2>
                  <span className="text-sm font-semibold tabular-nums">{fmt(breakdown?.total ?? 0)}</span>
                </div>
                {groups.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-10">{t('cards.noPurchases')}</p>
                ) : (
                  <div className="grid gap-6 md:grid-cols-2 items-center">
                    <div className="relative h-64">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={58} outerRadius={92} paddingAngle={1}>
                            {pieData.map((d, i) => <Cell key={i} fill={d.color} />)}
                          </Pie>
                          <Tooltip formatter={(v) => fmt(Number(v) || 0)} />
                        </PieChart>
                      </ResponsiveContainer>
                      <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                        <span className="text-[11px] text-muted-foreground">{t('reports.total')}</span>
                        <span className="text-lg font-bold tabular-nums">{fmt(breakdown?.total ?? 0)}</span>
                      </div>
                    </div>
                    <div className="space-y-2.5">
                      {groups.map((g) => (
                        <div key={g.id} className="flex items-center gap-3">
                          <span className="w-3 h-3 rounded-sm shrink-0" style={{ backgroundColor: g.color }} />
                          <span className="min-w-0 flex-1 overflow-x-auto no-scrollbar">
                            <span className="text-sm font-medium whitespace-nowrap">{labelOf(g.name, g.uncategorized)}</span>
                          </span>
                          <span className="shrink-0 text-xs text-muted-foreground tabular-nums w-10 text-right">{g.percentage}%</span>
                          <span className="shrink-0 text-sm font-medium tabular-nums text-right">{fmt(g.total)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Purchases list (real + projected installments) */}
              <div className="bg-card rounded-xl border border-border shadow-sm">
                <div className="px-5 py-3 border-b border-border flex items-center justify-between gap-2 flex-wrap">
                  <h2 className="text-sm font-semibold">{t('cards.purchases')}</h2>
                  <div className="flex items-center gap-3">
                    {projectedTotal > 0 && (
                      <span className="text-[11px] text-indigo-600 dark:text-indigo-300">{t('cards.projectedTotal', { amount: fmt(projectedTotal) })}</span>
                    )}
                    <span className="text-xs text-muted-foreground">{purchaseRows.length} {t('cards.items')}</span>
                  </div>
                </div>
                {txLoading ? (
                  <div className="p-5"><Skeleton className="h-24 w-full" /></div>
                ) : purchaseRows.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-10">{t('cards.noPurchases')}</p>
                ) : (
                  <div className="divide-y divide-muted">
                    {purchaseRows.map((row) => (
                      <div key={row.key} role={row.tx ? 'button' : undefined} tabIndex={row.tx ? 0 : undefined}
                        onClick={row.tx ? () => setEditingTx(row.tx) : undefined}
                        onKeyDown={row.tx ? (e) => { if (e.key === 'Enter') setEditingTx(row.tx) } : undefined}
                        className={`flex items-center gap-3 px-5 py-3 ${row.projected ? 'opacity-80' : 'cursor-pointer hover:bg-muted/50 transition-colors'}`}>
                        {row.categoryIcon
                          ? <CategoryIcon icon={row.categoryIcon} color={row.categoryColor ?? undefined} size="sm" />
                          : <span className="w-7 h-7 rounded-lg bg-muted flex items-center justify-center shrink-0"><Layers size={13} className="text-muted-foreground" /></span>}
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium truncate">
                            {row.name}
                            {row.projected && (
                              <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                                {t('cards.projected')}
                              </span>
                            )}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {new Date(row.date).toLocaleDateString(locale)}{row.categoryName ? ` · ${row.categoryName}` : ''}
                          </p>
                        </div>
                        <span className={`text-sm font-semibold tabular-nums shrink-0 ${row.projected ? 'text-muted-foreground' : ''}`}>{fmt(row.amount)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </>
      )}

      <TransactionDialog
        open={!!editingTx}
        onClose={() => { setEditingTx(null); updateMutation.reset() }}
        transaction={editingTx}
        categories={categoriesList ?? []}
        categoryGroups={categoryGroupsList ?? []}
        accounts={(accounts ?? []).map((a) => ({ id: a.id, name: getAccountName(a), type: a.type }))}
        onSave={(data) => { if (editingTx) updateMutation.mutate({ id: editingTx.id, ...data }) }}
        onDelete={editingTx ? () => deleteMutation.mutate(editingTx.id) : undefined}
        isSynced={editingTx?.source === 'sync'}
        loading={updateMutation.isPending || deleteMutation.isPending}
        error={updateMutation.error ? extractApiError(updateMutation.error) : null}
      />
    </div>
  )
}
