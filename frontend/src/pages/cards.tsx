import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import { accounts as accountsApi, transactions as txApi, advancedReports } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { MonthStepper } from '@/components/month-stepper'
import { CategoryIcon } from '@/components/category-icon'
import { Skeleton } from '@/components/ui/skeleton'
import { currentMonth, monthRange } from '@/lib/month-utils'
import { getAccountName } from '@/lib/account-utils'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { usePrivacyMode } from '@/hooks/use-privacy-mode'
import { formatCurrency } from '@/lib/format'
import { CreditCard, Layers } from 'lucide-react'

export default function CardsPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const { mask } = usePrivacyMode()

  const { data: accounts, isLoading } = useQuery({ queryKey: ['accounts'], queryFn: () => accountsApi.list() })
  const cards = (accounts ?? []).filter((a) => a.type === 'credit_card' && !a.is_closed)

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

  const currency = breakdown?.currency ?? card?.currency ?? 'BRL'
  const fmt = (n: number) => mask(formatCurrency(n, currency, locale))
  const groups = breakdown?.groups ?? []
  const labelOf = (name: string | null, uncat: boolean) => (uncat ? t('reports.uncategorized') : (name ?? '—'))
  const pieData = groups.map((g) => ({ name: labelOf(g.name, g.uncategorized), value: g.total, color: g.color }))

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

              {/* Purchases list */}
              <div className="bg-card rounded-xl border border-border shadow-sm">
                <div className="px-5 py-3 border-b border-border flex items-center justify-between">
                  <h2 className="text-sm font-semibold">{t('cards.purchases')}</h2>
                  <span className="text-xs text-muted-foreground">{txs?.items?.length ?? 0} {t('cards.items')}</span>
                </div>
                {txLoading ? (
                  <div className="p-5"><Skeleton className="h-24 w-full" /></div>
                ) : !txs || txs.items.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-10">{t('cards.noPurchases')}</p>
                ) : (
                  <div className="divide-y divide-muted">
                    {txs.items.map((tx) => (
                      <div key={tx.id} className="flex items-center gap-3 px-5 py-3">
                        {tx.category
                          ? <CategoryIcon icon={tx.category.icon} color={tx.category.color} size="sm" />
                          : <span className="w-7 h-7 rounded-lg bg-muted flex items-center justify-center shrink-0"><Layers size={13} className="text-muted-foreground" /></span>}
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium truncate">
                            {tx.payee_name || tx.payee || tx.description}
                            {tx.total_installments && tx.total_installments > 1 && (
                              <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-indigo-100 text-indigo-600 dark:bg-indigo-950/40 dark:text-indigo-300">
                                {tx.installment_number}/{tx.total_installments}
                              </span>
                            )}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {new Date(tx.date).toLocaleDateString(locale)}{tx.category ? ` · ${tx.category.name}` : ''}
                          </p>
                        </div>
                        <span className="text-sm font-semibold tabular-nums shrink-0">{fmt(Math.abs(tx.amount))}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
