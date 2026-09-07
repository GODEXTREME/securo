import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  ArrowLeft,
  Barcode,
  ClipboardPaste,
  RefreshCw,
  Store as StoreIcon,
  Trash2,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import { receipts as receiptsApi } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { DeleteConfirmationDialog } from '@/components/delete-confirmation-dialog'
import { ReceiptPastePanel } from '@/components/receipts/receipt-paste-panel'
import { ReceiptStatusBadge, ReceiptStatusMessage } from '@/components/receipts/receipt-status'
import { useDisplayLocale, useDateLocale } from '@/hooks/use-display-locale'
import { usePrivacyMode } from '@/hooks/use-privacy-mode'
import { useWorkspace } from '@/contexts/workspace-context'
import { formatCurrency } from '@/lib/format'
import {
  apiErrorKey,
  canRetry,
  formatAccessKey,
  formatCnpj,
  isPending,
  wantsPaste,
} from '@/lib/receipt-status'
import { cn } from '@/lib/utils'
import type { Receipt, ReceiptItem, VariationItem } from '@/types'

const CURRENCY = 'BRL'

function storeAddress(receipt: Receipt): string | null {
  const store = receipt.store
  if (!store) return null
  const line1 = [store.street, store.number].filter(Boolean).join(', ')
  const line2 = [store.district, [store.city, store.uf].filter(Boolean).join('/')].filter(Boolean).join(' · ')
  return [line1, line2].filter(Boolean).join(' — ') || null
}

export default function ReceiptDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const locale = useDisplayLocale()
  const dateLocale = useDateLocale()
  const { mask } = usePrivacyMode()
  const { canWrite } = useWorkspace()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [pasteOpen, setPasteOpen] = useState(false)

  const { data: receipt, isLoading, isError } = useQuery({
    queryKey: ['receipts', 'detail', id],
    queryFn: () => receiptsApi.get(id!),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const current = query.state.data
      return current && isPending(current.status) ? 5000 : false
    },
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['receipts'] })

  const retry = useMutation({
    mutationFn: () => receiptsApi.retry(id!),
    onSuccess: () => {
      invalidate()
      toast.success(t('receipts.retried'))
    },
    onError: (error) => toast.error(t(apiErrorKey(error))),
  })
  const update = useMutation({
    mutationFn: (notMyPurchase: boolean) => receiptsApi.update(id!, { not_my_purchase: notMyPurchase }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['receipts', 'detail', id], updated)
      queryClient.invalidateQueries({ queryKey: ['receipts', 'list'] })
      toast.success(t('receipts.updated'))
    },
    onError: (error) => toast.error(t(apiErrorKey(error))),
  })
  const remove = useMutation({
    mutationFn: () => receiptsApi.remove(id!),
    onSuccess: () => {
      invalidate()
      toast.success(t('receipts.discarded'))
      navigate('/receipts', { replace: true })
    },
    onError: () => toast.error(t('common.error')),
  })

  const money = (value: string | number | null | undefined) =>
    value == null ? '—' : mask(formatCurrency(Number(value), CURRENCY, locale))

  const backLink = (
    <Button asChild variant="ghost" size="sm" className="gap-1.5">
      <Link to="/receipts">
        <ArrowLeft size={16} /> {t('receipts.backToList')}
      </Link>
    </Button>
  )

  if (isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader section={t('nav.receipts')} title={t('receipts.title')} action={backLink} />
        <Skeleton className="h-28 rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    )
  }

  if (isError || !receipt) {
    return (
      <div className="space-y-6">
        <PageHeader section={t('nav.receipts')} title={t('receipts.title')} action={backLink} />
        <div className="bg-card rounded-xl border border-dashed border-border p-10 text-center">
          <p className="text-sm text-muted-foreground">{t('receipts.notFound')}</p>
        </div>
      </div>
    )
  }

  const pending = isPending(receipt.status)
  const paste = wantsPaste(receipt)
  const showPaste = canWrite && (paste || pasteOpen)
  const variation = receipt.variation_summary ?? null
  const variationByOrdinal = new Map<number, VariationItem>(
    (variation?.items ?? []).map((item) => [item.ordinal, item]),
  )
  const title = receipt.store?.trade_name || receipt.store?.legal_name || t('receipts.numberSeries', { number: receipt.number, series: receipt.series })
  const address = storeAddress(receipt)
  const issued = receipt.issued_at ? new Date(receipt.issued_at) : null

  return (
    <div className="space-y-6">
      <PageHeader section={t('nav.receipts')} title={title} action={backLink} />

      {/* Store header */}
      <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted">
            <StoreIcon size={20} />
          </span>
          <div className="min-w-0 flex-1 space-y-0.5">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-semibold">{receipt.store ? title : t('receipts.unknownStore')}</p>
              <ReceiptStatusBadge status={receipt.status} />
              {receipt.link.not_my_purchase && (
                <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                  {t('receipts.notMyPurchase')}
                </span>
              )}
            </div>
            {receipt.store?.legal_name && receipt.store.trade_name && (
              <p className="text-xs text-muted-foreground">{receipt.store.legal_name}</p>
            )}
            {address && <p className="text-xs text-muted-foreground">{address}</p>}
            <p className="text-xs text-muted-foreground">
              {t('receipts.cnpj')} {formatCnpj(receipt.store?.cnpj ?? receipt.issuer_cnpj)}
            </p>
          </div>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4">
          <div>
            <dt className="text-muted-foreground">{t('receipts.issuedAt')}</dt>
            <dd className="font-medium tabular-nums">
              {issued
                ? issued.toLocaleString(dateLocale, { dateStyle: 'medium', timeStyle: 'short' })
                : '—'}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t('receipts.numberLabel')}</dt>
            <dd className="font-medium tabular-nums">
              {t('receipts.numberSeries', { number: receipt.number, series: receipt.series })}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t('receipts.protocol')}</dt>
            <dd className="font-medium tabular-nums">{receipt.protocol ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t('receipts.scannedAt')}</dt>
            <dd className="font-medium tabular-nums">
              {new Date(receipt.link.scanned_at).toLocaleDateString(dateLocale)}
            </dd>
          </div>
          <div className="col-span-2 sm:col-span-4">
            <dt className="text-muted-foreground">{t('receipts.accessKey')}</dt>
            <dd className="break-all font-mono text-[11px]">{formatAccessKey(receipt.access_key)}</dd>
          </div>
        </dl>
      </div>

      {/* What is going on, and what to do about it */}
      {receipt.status !== 'authorized' && (
        <div className="space-y-3">
          <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
            <ReceiptStatusMessage receipt={receipt} className="text-sm" />
            {pending && (
              <p className="mt-1 text-[11px] text-muted-foreground tabular-nums">
                {t('receipts.attempts', { count: receipt.attempts })}
                {receipt.next_attempt_at
                  ? ` · ${t('receipts.nextAttempt', { time: new Date(receipt.next_attempt_at).toLocaleString(dateLocale, { dateStyle: 'short', timeStyle: 'short' }) })}`
                  : ` · ${t('receipts.noNextAttempt')}`}
              </p>
            )}
            {receipt.last_error && (
              <p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">{receipt.last_error}</p>
            )}
            {canWrite && (canRetry(receipt) || (pending && !showPaste)) && (
              <div className="mt-3 flex flex-wrap gap-2">
                {canRetry(receipt) && (
                  <Button size="sm" variant="outline" className="gap-1.5" disabled={retry.isPending} onClick={() => retry.mutate()}>
                    <RefreshCw size={14} className={retry.isPending ? 'animate-spin' : undefined} /> {t('receipts.retry')}
                  </Button>
                )}
                {pending && !showPaste && (
                  <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setPasteOpen(true)}>
                    <ClipboardPaste size={14} /> {t('receipts.pastePage')}
                  </Button>
                )}
              </div>
            )}
          </div>
          {showPaste && (
            <ReceiptPastePanel
              receipt={receipt}
              onDone={(updated) => {
                queryClient.setQueryData(['receipts', 'detail', id], updated)
                setPasteOpen(false)
              }}
            />
          )}
        </div>
      )}

      {/* Price variation */}
      {variation && (
        <VariationBlock
          compared={variation.compared_items}
          total={variation.total_items}
          delta={Number(variation.delta_total)}
          money={money}
        />
      )}

      {/* Items */}
      {receipt.items.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">
            {t('receipts.items')} · {t('receipts.itemCount', { count: receipt.items.length })}
          </h2>
          <div className="divide-y divide-border rounded-xl border border-border bg-card shadow-sm">
            {receipt.items.map((item) => (
              <ItemRow
                key={item.id}
                item={item}
                variation={variationByOrdinal.get(item.ordinal) ?? null}
                locale={locale}
                dateLocale={dateLocale}
                money={money}
              />
            ))}
          </div>
        </section>
      )}

      {/* Totals */}
      {receipt.total != null && (
        <section className="rounded-xl border border-border bg-card p-4 shadow-sm">
          <h2 className="mb-2 text-sm font-semibold">{t('receipts.totals.title')}</h2>
          <dl className="space-y-1 text-sm">
            <TotalLine label={t('receipts.totals.products')} value={money(receipt.products_total)} />
            {Number(receipt.discount) > 0 && (
              <TotalLine label={t('receipts.totals.discount')} value={`− ${money(receipt.discount)}`} />
            )}
            {Number(receipt.addition) > 0 && (
              <TotalLine label={t('receipts.totals.addition')} value={`+ ${money(receipt.addition)}`} />
            )}
            {Number(receipt.shipping) > 0 && (
              <TotalLine label={t('receipts.totals.shipping')} value={`+ ${money(receipt.shipping)}`} />
            )}
            <TotalLine label={t('receipts.totals.total')} value={money(receipt.total)} strong />
            {receipt.approx_taxes != null && (
              <TotalLine label={t('receipts.totals.approxTaxes')} value={money(receipt.approx_taxes)} muted />
            )}
          </dl>
        </section>
      )}

      {/* Payments */}
      {receipt.payments && receipt.payments.length > 0 && (
        <section className="rounded-xl border border-border bg-card p-4 shadow-sm">
          <h2 className="mb-2 text-sm font-semibold">{t('receipts.payments.title')}</h2>
          <dl className="space-y-1 text-sm">
            {receipt.payments.map((payment, index) => (
              <TotalLine
                key={index}
                label={[payment.label ?? payment.type ?? t('receipts.payments.other'), payment.brand].filter(Boolean).join(' · ')}
                value={money(payment.amount)}
              />
            ))}
            {receipt.payments.some((p) => p.change > 0) && (
              <TotalLine
                label={t('receipts.payments.change')}
                value={money(receipt.payments.reduce((sum, p) => sum + (p.change || 0), 0))}
                muted
              />
            )}
          </dl>
        </section>
      )}

      {/* Yours to keep or not */}
      {canWrite && (
        <section className="space-y-4 rounded-xl border border-border bg-card p-4 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p id="receipt-not-mine" className="text-sm font-medium">{t('receipts.notMyPurchase')}</p>
              <p className="text-xs text-muted-foreground">{t('receipts.notMyPurchaseHint')}</p>
            </div>
            <Switch
              aria-labelledby="receipt-not-mine"
              checked={receipt.link.not_my_purchase}
              disabled={update.isPending}
              onCheckedChange={(checked) => update.mutate(checked)}
            />
          </div>
          <div className="border-t border-border pt-4">
            <Button variant="outline" className="gap-1.5 text-rose-600 hover:text-rose-700" onClick={() => setConfirmDelete(true)}>
              <Trash2 size={14} /> {t('receipts.delete')}
            </Button>
          </div>
        </section>
      )}

      <DeleteConfirmationDialog
        open={confirmDelete}
        title={t('receipts.discardTitle')}
        description={t('receipts.discardDesc')}
        isPending={remove.isPending}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => remove.mutate()}
      />
    </div>
  )
}

function VariationBlock({
  compared,
  total,
  delta,
  money,
}: {
  compared: number
  total: number
  delta: number
  money: (value: number) => string
}) {
  const { t } = useTranslation()
  const up = delta > 0
  const flat = delta === 0
  return (
    <section
      className={cn(
        'rounded-xl border p-4 shadow-sm',
        compared === 0
          ? 'border-border bg-card'
          : up
            ? 'border-rose-200 bg-rose-50/60 dark:border-rose-900/60 dark:bg-rose-950/20'
            : 'border-emerald-200 bg-emerald-50/60 dark:border-emerald-900/60 dark:bg-emerald-950/20',
      )}
    >
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        {compared > 0 && (up ? <TrendingUp size={16} className="text-rose-600" /> : <TrendingDown size={16} className="text-emerald-600" />)}
        {t('receipts.variation.title')}
      </h2>
      {compared === 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">{t('receipts.variation.none')}</p>
      ) : (
        <p className="mt-1 text-sm">
          {t('receipts.variation.compared', { compared, total })}
          {' · '}
          <span className={cn('font-semibold', up ? 'text-rose-700' : flat ? '' : 'text-emerald-700')}>
            {flat
              ? t('receipts.variation.same')
              : t(up ? 'receipts.variation.more' : 'receipts.variation.less', { amount: money(Math.abs(delta)) })}
          </span>
        </p>
      )}
    </section>
  )
}

function ItemRow({
  item,
  variation,
  locale,
  dateLocale,
  money,
}: {
  item: ReceiptItem
  variation: VariationItem | null
  locale: string
  dateLocale: string
  money: (value: string | number | null | undefined) => string
}) {
  const { t } = useTranslation()
  const qty = Number(item.quantity).toLocaleString(locale, { maximumFractionDigits: 3 })
  const unitPrice = money(item.effective_unit_price)
  const corrected = item.unit_price_corrected != null
  const delta = variation && variation.comparable ? Number(variation.delta_unit) : null
  const showProductName = item.product_name && item.product_name !== item.description

  return (
    <div className="flex items-start gap-3 px-4 py-3">
      <span className="mt-0.5 w-6 shrink-0 text-right text-[11px] text-muted-foreground tabular-nums">{item.ordinal}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium leading-snug">{item.description}</p>
        {/* The line names what the till printed; the product is what the
            catalogue made of it, and the only way to its price history. */}
        {item.product_id ? (
          <Link to={`/products/${item.product_id}`} className="text-xs text-muted-foreground hover:underline">
            {showProductName ? item.product_name : t('products.seeHistory')}
          </Link>
        ) : (
          showProductName && <p className="text-xs text-muted-foreground">{item.product_name}</p>
        )}
        <p className="mt-0.5 text-xs text-muted-foreground tabular-nums">
          {t('receipts.lineMath', { qty, unit: item.unit, price: unitPrice })}
          {corrected && (
            <span className="ml-1 text-amber-700">({t('receipts.corrected', { price: money(item.unit_price) })})</span>
          )}
          {item.normalized_price != null && item.base_unit && (
            <span className="ml-1">· {money(item.normalized_price)}/{item.base_unit}</span>
          )}
        </p>
        {Number(item.discount) > 0 && (
          <p className="text-xs text-muted-foreground tabular-nums">
            {t('receipts.totals.discount')}: − {money(item.discount)}
          </p>
        )}
        {variation && delta != null && (
          <p className={cn('mt-0.5 text-xs tabular-nums', delta > 0 ? 'text-rose-700' : delta < 0 ? 'text-emerald-700' : 'text-muted-foreground')}>
            {delta === 0 ? t('receipts.variation.sameUnit') : `${delta > 0 ? '+' : '−'} ${money(Math.abs(delta))}`}
            {variation.delta_pct != null && delta !== 0 && ` (${delta > 0 ? '+' : ''}${variation.delta_pct.toFixed(0)}%)`}
            {' · '}
            {variation.previous_store_name
              ? t('receipts.variation.previousAt', {
                  price: money(variation.previous_unit_price),
                  date: new Date(`${variation.previous_on}T00:00:00`).toLocaleDateString(dateLocale),
                  store: variation.previous_store_name,
                })
              : t('receipts.variation.previous', {
                  price: money(variation.previous_unit_price),
                  date: new Date(`${variation.previous_on}T00:00:00`).toLocaleDateString(dateLocale),
                })}
          </p>
        )}
        {(item.product_scope === 'chain' || !item.gtin) && (
          <div className="mt-1 flex flex-wrap gap-1">
            {item.product_scope === 'chain' && (
              <span className="rounded-full bg-sky-100 px-1.5 py-0.5 text-[10px] font-medium text-sky-700">
                {t('receipts.variation.chainOnly')}
              </span>
            )}
            {!item.gtin && (
              <span className="inline-flex items-center gap-1 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                <Barcode size={10} /> {t('receipts.noBarcode')}
              </span>
            )}
          </div>
        )}
      </div>
      <span className="shrink-0 text-sm font-semibold tabular-nums">{money(item.total)}</span>
    </div>
  )
}

function TotalLine({ label, value, strong, muted }: { label: string; value: string; strong?: boolean; muted?: boolean }) {
  return (
    <div className={cn('flex items-center justify-between gap-4', strong && 'border-t border-border pt-1 text-base font-semibold', muted && 'text-xs text-muted-foreground')}>
      <dt className="truncate">{label}</dt>
      <dd className="shrink-0 tabular-nums">{value}</dd>
    </div>
  )
}
