import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { accounts as accountsApi } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { getAccountName } from '@/lib/account-utils'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { usePrivacyMode } from '@/hooks/use-privacy-mode'
import { formatCurrency } from '@/lib/format'
import { CreditCard, ChevronRight } from 'lucide-react'

// A lightweight launcher: every credit card in one place, ordered the way the
// user asked (open invoices first by nearest due date, paid-off cards last),
// each linking into its full account view (bills, cycle, spending, currency).
export default function CardsPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const locale = useDisplayLocale()
  const { mask } = usePrivacyMode()
  const { data: accounts, isLoading } = useQuery({ queryKey: ['accounts'], queryFn: () => accountsApi.list() })

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
        <div className="grid gap-3 sm:grid-cols-2">
          {cards.map((c) => {
            const owed = c.balance ?? 0
            const limit = c.credit_limit ?? 0
            const usage = limit > 0 ? Math.min(100, Math.round((owed / limit) * 100)) : null
            return (
              <button
                key={c.id}
                onClick={() => navigate(`/accounts/${c.id}`)}
                className="group flex items-center gap-3 rounded-xl border border-border bg-card p-4 text-left shadow-sm hover:bg-muted/50 transition-colors"
              >
                {c.institution_logo_url
                  ? <img src={c.institution_logo_url} alt="" className="w-9 h-9 rounded-lg shrink-0" />
                  : <span className="w-9 h-9 rounded-lg bg-muted flex items-center justify-center shrink-0"><CreditCard size={18} /></span>}
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold truncate">{getAccountName(c)}</p>
                  <p className="text-[11px] text-muted-foreground truncate">
                    {[c.card_brand, c.card_level].filter(Boolean).join(' · ') || t('cards.creditCard')}
                  </p>
                  {limit > 0 && (
                    <div className="mt-2 h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className={`h-full rounded-full ${(usage ?? 0) >= 90 ? 'bg-rose-500' : 'bg-gradient-to-r from-indigo-400 to-indigo-600'}`}
                        style={{ width: `${usage}%` }}
                      />
                    </div>
                  )}
                </div>
                <div className="flex flex-col items-end shrink-0">
                  <span className="text-sm font-bold tabular-nums">{mask(formatCurrency(owed, c.currency, locale))}</span>
                  {c.next_due_date && (
                    <span className="text-[11px] text-muted-foreground">
                      {t('cards.dueOn', { date: new Date(c.next_due_date).toLocaleDateString(locale) })}
                    </span>
                  )}
                </div>
                <ChevronRight size={16} className="text-muted-foreground shrink-0 group-hover:translate-x-0.5 transition-transform" />
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
