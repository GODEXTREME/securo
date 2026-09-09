import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, Barcode, Store as StoreIcon, TrendingDown, Trophy } from 'lucide-react'
import { products as productsApi } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useDateLocale, useDisplayLocale } from '@/hooks/use-display-locale'
import { formatCurrency } from '@/lib/format'
import { describeSize, priceLabel } from '@/lib/product-format'
import type { PricePoint } from '@/types'

const CURRENCY = 'BRL'

export default function ProductDetailPage() {
  const { id = '' } = useParams()
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const dateLocale = useDateLocale()
  const queryClient = useQueryClient()
  const [name, setName] = useState<string | null>(null)

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

  return (
    <div className="space-y-6">
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

        {name === null ? (
          <Button variant="outline" size="sm" onClick={() => setName(product.name)}>
            {t('products.rename')}
          </Button>
        ) : (
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

      <div className="grid gap-3 sm:grid-cols-2">
        <PriceCard
          icon={<TrendingDown size={15} className="text-muted-foreground" />}
          title={t('products.lastPaid')}
          point={lastPaid}
          locale={locale}
          dateLocale={dateLocale}
          empty={t('products.noPurchases')}
        />
        <PriceCard
          icon={<Trophy size={15} className="text-amber-600" />}
          title={t('products.best30d')}
          point={best}
          locale={locale}
          dateLocale={dateLocale}
          empty={t('products.noRecent')}
        />
      </div>

      <div className="space-y-2 rounded-xl border border-border bg-card p-4 shadow-sm">
        <p className="text-sm font-medium">{t('products.history')}</p>
        {history.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('products.noHistory')}</p>
        ) : (
          <ul className="divide-y divide-border">
            {history.map((point, i) => (
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
                    {new Date(point.observed_on).toLocaleDateString(dateLocale)}
                    {point.is_outlier && ` · ${t('products.outlier')}`}
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  <p className={point.is_outlier ? 'text-sm text-muted-foreground line-through' : 'text-sm font-semibold'}>
                    {formatCurrency(Number(point.unit_price), CURRENCY, locale)}
                  </p>
                  <p className="text-[11px] text-muted-foreground">{priceLabel(point, locale, t)}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function PriceCard({
  icon,
  title,
  point,
  locale,
  dateLocale,
  empty,
}: {
  icon: React.ReactNode
  title: string
  point: PricePoint | null
  locale: string
  dateLocale: string
  empty: string
}) {
  const { t } = useTranslation()
  return (
    <div className="space-y-1 rounded-xl border border-border bg-card p-4 shadow-sm">
      <p className="flex items-center gap-2 text-sm font-medium">
        {icon} {title}
      </p>
      {point ? (
        <>
          <p className="text-xl font-semibold">{formatCurrency(Number(point.unit_price), CURRENCY, locale)}</p>
          <p className="text-xs text-muted-foreground">
            {point.store_name ?? t('receipts.unknownStore')} ·{' '}
            {new Date(point.observed_on).toLocaleDateString(dateLocale)}
          </p>
          <p className="text-[11px] text-muted-foreground">{priceLabel(point, locale, t)}</p>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">{empty}</p>
      )}
    </div>
  )
}
