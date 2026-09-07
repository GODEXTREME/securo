import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowDownRight, ArrowUpRight, Store as StoreIcon } from 'lucide-react'
import { receipts as receiptsApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { formatCurrency } from '@/lib/format'
import type { ReceiptMover } from '@/types'

const CURRENCY = 'BRL'

/** The windows worth offering. Ninety days is the default: long enough
 *  for a product to have been bought twice, short enough that a price
 *  from it still means something. */
const WINDOWS = [30, 90, 365] as const

/**
 * What the notes add up to.
 *
 * The headline is not the spend — a bank statement already knows that —
 * but the difference: on the items bought again, what they cost compared
 * with last time. Everything else on the panel exists to make that
 * number answerable: which products moved it, and where.
 */
export function ReceiptSummaryPanel({ locale, dateLocale }: { locale: string; dateLocale: string }) {
  const { t } = useTranslation()
  const [days, setDays] = useState<number>(90)

  const { data, isLoading } = useQuery({
    queryKey: ['receipt-summary', days],
    queryFn: () => receiptsApi.summary(days),
  })

  if (isLoading) return <Skeleton className="h-40 rounded-xl" />
  // Nothing read yet: the list below already says what to do about that,
  // and an empty panel of zeros would only be in the way.
  if (!data || data.receipts === 0) return null

  const delta = Number(data.delta_total)
  const money = (value: string | number) => formatCurrency(Number(value), CURRENCY, locale)

  return (
    <section className="space-y-4 rounded-xl border border-border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">{t('receipts.summary.title')}</p>
        <div className="flex gap-1">
          {WINDOWS.map((window) => (
            <Button
              key={window}
              size="sm"
              variant={window === days ? 'secondary' : 'ghost'}
              className="h-7 px-2 text-xs"
              onClick={() => setDays(window)}
            >
              {t('receipts.summary.days', { count: window })}
            </Button>
          ))}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <p className="text-xs text-muted-foreground">{t('receipts.summary.spent')}</p>
          <p className="text-xl font-semibold tabular-nums">{money(data.total_spent)}</p>
          <p className="text-[11px] text-muted-foreground">
            {t('receipts.itemCount', { count: data.receipts })}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t('receipts.summary.versusLast')}</p>
          {data.compared_items === 0 ? (
            <>
              <p className="text-sm text-muted-foreground">{t('receipts.summary.nothingRepeated')}</p>
              <p className="text-[11px] text-muted-foreground">{t('receipts.summary.nothingRepeatedHint')}</p>
            </>
          ) : (
            <>
              <p
                className={cn(
                  'text-xl font-semibold tabular-nums',
                  delta > 0 ? 'text-rose-700 dark:text-rose-400' : delta < 0 ? 'text-emerald-700 dark:text-emerald-400' : '',
                )}
              >
                {delta > 0 ? '+' : delta < 0 ? '−' : ''}
                {money(Math.abs(delta))}
              </p>
              <p className="text-[11px] text-muted-foreground">
                {t('receipts.summary.comparedItems', { count: data.compared_items })}
              </p>
            </>
          )}
        </div>
      </div>

      {data.movers.length > 0 && (
        <div className="space-y-1 border-t border-border pt-3">
          <p className="text-xs font-medium text-muted-foreground">{t('receipts.summary.movers')}</p>
          <ul className="divide-y divide-border">
            {data.movers.map((mover, i) => (
              <MoverRow key={`${mover.product_id ?? mover.name}-${i}`} mover={mover} money={money} dateLocale={dateLocale} />
            ))}
          </ul>
        </div>
      )}

      {data.stores.length > 0 && (
        <div className="space-y-1 border-t border-border pt-3">
          <p className="text-xs font-medium text-muted-foreground">{t('receipts.summary.stores')}</p>
          <ul className="space-y-1">
            {data.stores.map((store) => (
              <li key={store.store_id ?? store.name} className="flex items-center justify-between gap-3 text-sm">
                <span className="inline-flex min-w-0 items-center gap-1.5">
                  <StoreIcon size={13} className="shrink-0 text-muted-foreground" />
                  <span className="truncate">{store.name || t('receipts.unknownStore')}</span>
                </span>
                <span className="shrink-0 tabular-nums">{money(store.total)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

function MoverRow({
  mover,
  money,
  dateLocale,
}: {
  mover: ReceiptMover
  money: (value: string | number) => string
  dateLocale: string
}) {
  const { t } = useTranslation()
  const delta = Number(mover.delta_unit)
  const rose = delta > 0
  const name = (
    <span className="truncate text-sm">{mover.name}</span>
  )

  return (
    <li className="flex items-center justify-between gap-3 py-1.5">
      <span className="min-w-0">
        {mover.product_id ? (
          <Link to={`/products/${mover.product_id}`} className="block truncate hover:underline">
            {name}
          </Link>
        ) : (
          name
        )}
        <span className="block text-[11px] text-muted-foreground">
          {[mover.store_name, mover.observed_on ? new Date(`${mover.observed_on}T00:00:00`).toLocaleDateString(dateLocale) : null]
            .filter(Boolean)
            .join(' · ')}
        </span>
      </span>
      <span
        className={cn(
          'inline-flex shrink-0 items-center gap-1 text-sm tabular-nums',
          rose ? 'text-rose-700 dark:text-rose-400' : 'text-emerald-700 dark:text-emerald-400',
        )}
        title={t('receipts.summary.perUnit')}
      >
        {rose ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
        {money(Math.abs(delta))}
        {mover.delta_pct != null && <span className="text-[11px]">({rose ? '+' : ''}{mover.delta_pct.toFixed(0)}%)</span>}
      </span>
    </li>
  )
}
