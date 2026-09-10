import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, Barcode, Store as StoreIcon, Trophy } from 'lucide-react'
import { products as productsApi } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { PriceHistoryChart } from '@/components/products/price-history-chart'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useDateLocale, useDisplayLocale } from '@/hooks/use-display-locale'
import { formatCurrency } from '@/lib/format'
import { describeSize, priceLabel } from '@/lib/product-format'
import { chartable, cheapestStore, verdict } from '@/lib/price-verdict'
import { cn } from '@/lib/utils'
import type { PricePoint } from '@/types'

const CURRENCY = 'BRL'
/** Enough of the history to see the shape of it on a phone; the rest is a tap away. */
const HISTORY_PREVIEW = 8

export default function ProductDetailPage() {
  const { id = '' } = useParams()
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const dateLocale = useDateLocale()
  const queryClient = useQueryClient()
  const [name, setName] = useState<string | null>(null)
  const [allHistory, setAllHistory] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['product', id],
    queryFn: () => productsApi.get(id),
    enabled: id !== '',
  })

  const rename = useMutation({
    mutationFn: (value: string) => productsApi.update(id, { name: value }),
    onSuccess: () => {
      setName(null)
      queryClient.invalidateQueries({ queryKey: ['product', id] })
      toast.success(t('products.renamed'))
    },
    onError: () => toast.error(t('common.error')),
  })

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-32 rounded-xl" />
      </div>
    )
  }

  const { product, last_paid: lastPaid, best_price_30d: best, history } = data
  const size = describeSize(product)
  const call = verdict(lastPaid, history)
  const cheapest = cheapestStore(history)
  const drawable = chartable(history)
  const baseUnit = drawable?.[0]?.normalized_price === null ? null : (drawable?.[0]?.base_unit ?? null)
  const hiddenOutliers = history.some((point) => point.is_outlier)
  // The old page showed "last paid" and "cheapest in 30 days" side by side,
  // which on a short history is the same number printed twice.
  const bestIsLast =
    best != null &&
    lastPaid != null &&
    best.observed_on === lastPaid.observed_on &&
    best.store_id === lastPaid.store_id &&
    best.unit_price === lastPaid.unit_price
  const shown = allHistory ? history : history.slice(0, HISTORY_PREVIEW)

  const money = (value: string | number) => formatCurrency(Number(value), CURRENCY, locale)
  const day = (value: string) => new Date(`${value}T00:00:00`).toLocaleDateString(dateLocale)

  return (
    <div className="space-y-4">
      <PageHeader
        section={t('nav.receipts')}
        title={product.name}
        action={
          <Button asChild variant="ghost" size="sm" className="gap-1.5">
            <Link to="/receipts">
              <ArrowLeft size={16} /> {t('receipts.backToList')}
            </Link>
          </Button>
        }
      />

      {/* What was it worth — the question the page is opened with, answered
          before anything about the product's identity. */}
      <div className="space-y-3 rounded-xl border border-border bg-card p-4 shadow-sm">
        {lastPaid ? (
          <>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t('products.lastPaid')}
            </p>
            <Hero point={lastPaid} locale={locale} dateLocale={dateLocale} />
            {call && <VerdictLine call={call} locale={locale} />}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">{t('products.noPurchases')}</p>
        )}

        {(cheapest || (best && !bestIsLast)) && (
          <div className="space-y-1 border-t border-border pt-3 text-xs text-muted-foreground">
            {cheapest && (
              <p className="flex items-center gap-1.5">
                <StoreIcon size={13} className="shrink-0" />
                {t('products.cheapestAt', {
                  store: cheapest.store_name ?? t('receipts.unknownStore'),
                  price: priceOf(cheapest, locale, t),
                })}
              </p>
            )}
            {best && !bestIsLast && (
              <p className="flex items-center gap-1.5">
                <Trophy size={13} className="shrink-0 text-amber-600" />
                {t('products.bestWas', {
                  price: priceOf(best, locale, t),
                  store: best.store_name ?? t('receipts.unknownStore'),
                })}
              </p>
            )}
          </div>
        )}
      </div>

      {drawable && (
        <div className="space-y-2 rounded-xl border border-border bg-card p-4 shadow-sm">
          <p className="text-sm font-medium">
            {baseUnit ? t('products.chartPerUnit', { unit: baseUnit }) : t('products.chartPaid')}
          </p>
          <PriceHistoryChart points={drawable} baseUnit={baseUnit} locale={locale} dateLocale={dateLocale} />
          {hiddenOutliers && (
            <p className="text-[11px] text-muted-foreground">{t('products.chartOutliersOff')}</p>
          )}
        </div>
      )}

      {/* Identity: brand, size, whether the price compares beyond this chain.
          Below the prices because it answers "what is this" — a question the
          person holding the product has already answered for themselves. */}
      <div className="space-y-3 rounded-xl border border-border bg-card p-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {product.brand && <span className="font-medium text-foreground">{product.brand}</span>}
          {size && <span>{size}</span>}
          <span
            className={
              product.scope === 'global'
                ? 'rounded-full bg-emerald-100 px-2 py-0.5 font-medium text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300'
                : 'rounded-full bg-muted px-2 py-0.5 font-medium'
            }
          >
            {t(product.scope === 'global' ? 'products.scopeGlobal' : 'products.scopeChain')}
          </span>
          {product.gtin && (
            <span className="inline-flex items-center gap-1 font-mono">
              <Barcode size={13} /> {product.gtin}
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {t(product.scope === 'global' ? 'products.scopeGlobalHint' : 'products.scopeChainHint')}
        </p>

        <div className="flex flex-wrap gap-2">
          {/* Only a product without one: a barcode already read came from
              the portal or from someone's scan, and replacing it is a
              different, riskier thing than supplying the first. */}
          {!product.gtin && (
            <Button asChild variant="outline" size="sm" className="gap-1.5">
              <Link to={`/products/scan?link=${product.id}`}>
                <Barcode size={15} /> {t('products.addGtin')}
              </Link>
            </Button>
          )}
          {name === null && (
            <Button variant="outline" size="sm" onClick={() => setName(product.name)}>
              {t('products.rename')}
            </Button>
          )}
        </div>

        {name !== null && (
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
            <Button
              onClick={() => rename.mutate(name.trim())}
              disabled={rename.isPending || name.trim() === '' || name.trim() === product.name}
            >
              {t('common.save')}
            </Button>
            <Button variant="ghost" onClick={() => setName(null)}>
              {t('common.cancel')}
            </Button>
          </div>
        )}
      </div>

      <div className="space-y-2 rounded-xl border border-border bg-card p-4 shadow-sm">
        <p className="text-sm font-medium">{t('products.history')}</p>
        {history.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('products.noHistory')}</p>
        ) : (
          <>
            <ul className="divide-y divide-border">
              {shown.map((point, i) => (
                <li key={`${point.observed_on}-${point.store_id}-${i}`} className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0">
                    <p className="flex items-center gap-1.5 truncate text-sm">
                      <StoreIcon size={13} className="shrink-0 text-muted-foreground" />
                      {point.store_name ?? t('receipts.unknownStore')}
                      {!point.mine && (
                        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          {t('products.someoneElse')}
                        </span>
                      )}
                    </p>
                    <p className="text-[11px] text-muted-foreground">
                      {day(point.observed_on)}
                      {point.is_outlier && ` · ${t('products.outlier')}`}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className={point.is_outlier ? 'text-sm text-muted-foreground line-through' : 'text-sm font-semibold'}>
                      {money(point.unit_price)}
                    </p>
                    <p className="text-[11px] text-muted-foreground">{priceLabel(point, locale, t)}</p>
                  </div>
                </li>
              ))}
            </ul>
            {history.length > HISTORY_PREVIEW && (
              <Button variant="ghost" size="sm" className="w-full" onClick={() => setAllHistory(!allHistory)}>
                {allHistory
                  ? t('common.showLess')
                  : t('common.showMore', { count: history.length - HISTORY_PREVIEW })}
              </Button>
            )}
          </>
        )}
      </div>
    </div>
  )
}

/** The comparable price when there is one, because R$ 3,58/l is what tells a
 *  500 ml from a 1,5 L; the paid price otherwise. */
function priceOf(point: PricePoint, locale: string, t: (key: string) => string): string {
  const label = priceLabel(point, locale, t)
  return point.normalized_price === null || point.base_unit === null
    ? formatCurrency(Number(point.unit_price), CURRENCY, locale)
    : label
}

function Hero({ point, locale, dateLocale }: { point: PricePoint; locale: string; dateLocale: string }) {
  const { t } = useTranslation()
  const store = point.store_name ?? t('receipts.unknownStore')
  const date = new Date(`${point.observed_on}T00:00:00`).toLocaleDateString(dateLocale)
  const paid = formatCurrency(Number(point.unit_price), CURRENCY, locale)
  const perUnit = point.normalized_price !== null && point.base_unit !== null

  return (
    <div className="space-y-0.5">
      <p className="text-3xl font-semibold tabular-nums">
        {perUnit ? priceLabel(point, locale, t) : paid}
      </p>
      <p className="text-xs text-muted-foreground">
        {perUnit ? t('products.youPaid', { price: paid, store, date }) : `${store} · ${date}`}
      </p>
    </div>
  )
}

function VerdictLine({
  call,
  locale,
}: {
  call: NonNullable<ReturnType<typeof verdict>>
  locale: string
}) {
  const { t } = useTranslation()
  if (call.kind === 'only') {
    return <p className="text-xs text-muted-foreground">{t('products.verdictOnly')}</p>
  }
  if (call.kind === 'cheapest') {
    return (
      <p className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300">
        <Trophy size={13} /> {t('products.verdictCheapest')}
      </p>
    )
  }
  return (
    <p className={cn('inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-800', 'dark:bg-amber-950/50 dark:text-amber-300')}>
      {t('products.verdictAbove', {
        percent: call.percent,
        price: priceOf(call.best, locale, t),
      })}
    </p>
  )
}
