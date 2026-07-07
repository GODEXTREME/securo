import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import { accounts as accountsApi, transactions as txApi, categories as categoriesApi, categoryGroups as categoryGroupsApi, dashboard } from '@/lib/api'
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
import type { Transaction, Account } from '@/types'
import { CreditCard, Layers } from 'lucide-react'

// Is the statement being viewed still open (accumulating) or already closed?
// We navigate by statement, bucketing purchases on their bill *due* date, so
// `month` is the statement's due month. The statement closes a few days before
// it's due (statement_close_day); when close_day > due_day the close falls in
// the previous calendar month. If today is past that close date the fatura is
// final; otherwise it's still open and one-off purchases can still land on it.
function statementStatus(card: Account | undefined, month: string): { status: 'open' | 'closed' | 'unknown'; closeDate: Date | null } {
  const closeDay = card?.statement_close_day
  if (!closeDay) return { status: 'unknown', closeDate: null }
  const dueDay = card?.payment_due_day ?? closeDay
  const [y, m] = month.split('-').map(Number)
  let cy = y, cm = m
  if (closeDay > dueDay) { cm -= 1; if (cm < 1) { cm = 12; cy -= 1 } }
  const close = new Date(cy, cm - 1, closeDay, 23, 59, 59, 999)
  return { status: Date.now() > close.getTime() ? 'closed' : 'open', closeDate: close }
}

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
  const { from, to } = monthRange(month)
  const { status: stmtStatus, closeDate: stmtClose } = statementStatus(card, month)

  // The card view is organized by statement (fatura): filter/bucket by the
  // bill's due date (effective) so it lines up with the bank's invoice, not the
  // purchase-date calendar month.
  const { data: txs, isLoading: txLoading } = useQuery({
    queryKey: ['card-txs', cardId, month],
    queryFn: () => txApi.list({ account_id: cardId, from, to, type: 'debit', sort_by: 'date', sort_dir: 'desc', limit: 300, date_basis: 'effective' }),
    enabled: !!cardId,
  })
  // Installments not yet billed that will land on this card's statement.
  const { data: projected } = useQuery({
    queryKey: ['card-projected', month],
    queryFn: () => dashboard.projectedTransactions(`${month}-01`, 'effective'),
  })

  const currency = card?.currency ?? 'BRL'
  const fmt = (n: number) => mask(formatCurrency(n, currency, locale))

  // Merge real purchases with projected (unbilled) installments for this card.
  // The parcel number lives in the purchase text itself (the provider's title,
  // e.g. "… 3/6") — that's the source of truth. The badge is parsed from that
  // same text so it always matches; the number is stripped from the name to
  // avoid showing it twice.
  const parseNM = (s: string): string | null => {
    const m = s.match(/(\d+)\s*\/\s*(\d+)/)
    return m ? `${m[1]}/${m[2]}` : null
  }
  const stripNM = (s: string): string =>
    s.replace(/\s*[-–]?\s*(parcela\s*)?\d+\s*\/\s*\d+\s*$/i, '').trim() || s
  type Row = {
    key: string; date: string; name: string; installmentLabel: string | null
    categoryName: string | null; categoryColor: string | null; categoryIcon: string | null
    amount: number; projected: boolean; tx: Transaction | null
  }
  const realRows: Row[] = (txs?.items ?? []).map((tx) => {
    const raw = tx.payee_name || tx.payee || tx.description
    const label = parseNM(raw)
      ?? (tx.total_installments && tx.total_installments > 1 ? `${tx.installment_number}/${tx.total_installments}` : null)
    return {
      key: tx.id, date: tx.date, name: stripNM(raw), installmentLabel: label,
      categoryName: tx.category?.name ?? null, categoryColor: tx.category?.color ?? null, categoryIcon: tx.category?.icon ?? null,
      amount: Math.abs(tx.amount), projected: false, tx,
    }
  })
  const projRows: Row[] = (projected ?? [])
    .filter((p) => p.kind === 'installment' && p.account_id === cardId)
    .map((p, i) => ({
      key: `proj-${i}-${p.date}`, date: p.date, name: stripNM(p.description),
      installmentLabel: p.installment_number && p.total_installments
        ? `${p.installment_number}/${p.total_installments}` : parseNM(p.description),
      categoryName: p.category_name, categoryColor: p.category_color, categoryIcon: p.category_icon,
      amount: Math.abs(p.amount), projected: true, tx: null,
    }))
  const purchaseRows = [...realRows, ...projRows].sort((a, b) => b.date.localeCompare(a.date))
  const projectedTotal = projRows.reduce((s, r) => s + r.amount, 0)

  // Pie + statement total are derived from the SAME rows shown in the list
  // (real purchases + projected installments), so the chart and the "fatura"
  // figure always cover every purchase — including unbilled installments that
  // the synced category report doesn't know about yet.
  const catSlices = (() => {
    const m = new Map<string, { name: string; color: string; value: number }>()
    for (const r of purchaseRows) {
      const key = r.categoryName ?? '__uncat__'
      const cur = m.get(key) ?? { name: r.categoryName ?? t('reports.uncategorized'), color: r.categoryColor ?? '#9ca3af', value: 0 }
      cur.value += r.amount
      m.set(key, cur)
    }
    return [...m.values()].sort((a, b) => b.value - a.value)
  })()
  const faturaTotal = catSlices.reduce((s, c) => s + c.value, 0)
  const pieData = catSlices.map((c) => ({ name: c.name, value: c.value, color: c.color }))

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
                  <p className="text-2xl font-bold tabular-nums">{fmt(faturaTotal)}</p>
                  {projectedTotal > 0 && (
                    <p className="text-[11px] text-indigo-600 dark:text-indigo-300 mt-0.5">{t('cards.includesProjected', { amount: fmt(projectedTotal) })}</p>
                  )}
                  {limit > 0 && (
                    <div className="mt-2 w-48 max-w-full">
                      <div className="flex justify-between text-[11px] text-muted-foreground mb-1">
                        <span>{usage}% {t('cards.ofLimit')}</span>
                        <span>{fmt(limit)}</span>
                      </div>
                      <div className="h-2 rounded-full bg-muted overflow-hidden">
                        <div className={`h-full rounded-full ${(usage ?? 0) >= 90 ? 'bg-rose-500' : 'bg-gradient-to-r from-indigo-400 to-indigo-600'}`} style={{ width: `${usage}%` }} />
                      </div>
                      <p className="text-[11px] text-muted-foreground mt-1">{t('cards.totalOwed', { amount: fmt(owed) })}</p>
                    </div>
                  )}
                  {card.next_due_date && (
                    <p className="text-[11px] text-muted-foreground mt-2">
                      {t('cards.dueOn', { date: new Date(card.next_due_date).toLocaleDateString(locale) })}
                    </p>
                  )}
                </div>
                <div className="flex flex-col items-start sm:items-end gap-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-muted-foreground uppercase tracking-wide">{t('cards.statement')}</span>
                    {stmtStatus !== 'unknown' && (
                      <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${stmtStatus === 'open' ? 'bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300' : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'}`}>
                        {t(stmtStatus === 'open' ? 'cards.statementOpen' : 'cards.statementClosed')}
                      </span>
                    )}
                  </div>
                  <MonthStepper value={month} onChange={setMonth} locale={locale} />
                  {stmtStatus === 'open' && stmtClose && (
                    <span className="text-[10px] text-muted-foreground">{t('cards.closesOn', { date: stmtClose.toLocaleDateString(locale) })}</span>
                  )}
                </div>
              </div>

              {/* Without the card's close/due days we can't tell which invoice
                  a purchase belongs to, so the view falls back to purchase
                  month and nothing rolls over at the cutoff. Point the user to
                  set them. */}
              {card.type === 'credit_card' && (!card.statement_close_day || !card.payment_due_day) && (
                <div className="rounded-xl border border-rose-200 bg-rose-50 dark:border-rose-900/50 dark:bg-rose-950/20 px-4 py-3 text-[13px] text-rose-800 dark:text-rose-200">
                  {t('cards.missingCycle')}
                </div>
              )}

              {/* Open-statement notice: this fatura is still accumulating, so
                  one-off purchases haven't all posted yet — only installments
                  are projected forward. */}
              {stmtStatus === 'open' && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 dark:border-amber-900/50 dark:bg-amber-950/20 px-4 py-3 text-[13px] text-amber-800 dark:text-amber-200">
                  {t('cards.openStatementNote')}
                </div>
              )}

              {/* Spending summary + pie */}
              <div className="bg-card rounded-xl border border-border shadow-sm p-5">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-sm font-semibold">{t('cards.spendingByCategory')}</h2>
                  <span className="text-sm font-semibold tabular-nums">{fmt(faturaTotal)}</span>
                </div>
                {catSlices.length === 0 ? (
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
                        <span className="text-lg font-bold tabular-nums">{fmt(faturaTotal)}</span>
                      </div>
                    </div>
                    <div className="space-y-2.5">
                      {catSlices.map((c, i) => (
                        <div key={i} className="flex items-center gap-3">
                          <span className="w-3 h-3 rounded-sm shrink-0" style={{ backgroundColor: c.color }} />
                          <span className="min-w-0 flex-1 overflow-x-auto no-scrollbar">
                            <span className="text-sm font-medium whitespace-nowrap">{c.name}</span>
                          </span>
                          <span className="shrink-0 text-xs text-muted-foreground tabular-nums w-10 text-right">{faturaTotal > 0 ? Math.round((c.value / faturaTotal) * 100) : 0}%</span>
                          <span className="shrink-0 text-sm font-medium tabular-nums text-right">{fmt(c.value)}</span>
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
                          {/* Only the merchant name truncates; the badges stay
                              shrink-0 so "Prevista" is never clipped. */}
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="text-sm font-medium truncate">{row.name}</span>
                            {row.installmentLabel && (
                              <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-indigo-100 text-indigo-600 dark:bg-indigo-950/40 dark:text-indigo-300">
                                {row.installmentLabel}
                              </span>
                            )}
                            {row.projected && (
                              <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                                {t('cards.projected')}
                              </span>
                            )}
                          </div>
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
