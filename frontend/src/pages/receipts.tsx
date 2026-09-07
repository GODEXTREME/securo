import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Barcode, ChevronRight, ClipboardPaste, Clock, RefreshCw, ScanLine, Store as StoreIcon, Trash2, Zap } from 'lucide-react'
import { receipts as receiptsApi } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { DeleteConfirmationDialog } from '@/components/delete-confirmation-dialog'
import { ReceiptPastePanel } from '@/components/receipts/receipt-paste-panel'
import { ReceiptStatusBadge, ReceiptStatusMessage } from '@/components/receipts/receipt-status'
import { ReceiptSummaryPanel } from '@/components/receipts/receipt-summary-panel'
import { useDisplayLocale, useDateLocale } from '@/hooks/use-display-locale'
import { usePrivacyMode } from '@/hooks/use-privacy-mode'
import { useWorkspace } from '@/contexts/workspace-context'
import { formatCurrency } from '@/lib/format'
import { apiErrorKey, canRetry, hasPending, isPending, storeName, wantsPaste } from '@/lib/receipt-status'
import type { Receipt } from '@/types'

/** Receipts are Brazilian consumer receipts; the state prints them in reais. */
const CURRENCY = 'BRL'

/** "6 Sep, 14:32" — short enough for the line under a pending receipt. */
function formatWhen(iso: string, locale: string): string {
  return new Date(iso).toLocaleString(locale, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export default function ReceiptsPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const locale = useDisplayLocale()
  const dateLocale = useDateLocale()
  const { mask } = usePrivacyMode()
  const { canWrite } = useWorkspace()
  const [discarding, setDiscarding] = useState<Receipt | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['receipts', 'list'],
    queryFn: () => receiptsApi.list({ limit: 200 }),
    // The worker moves a receipt on its own only while it is pending, so
    // that is the only time polling buys anything.
    refetchInterval: (query) => (hasPending(query.state.data) ? 5000 : false),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['receipts'] })

  const retry = useMutation({
    mutationFn: (id: string) => receiptsApi.retry(id),
    onSuccess: () => {
      invalidate()
      toast.success(t('receipts.retried'))
    },
    onError: (error) => toast.error(t(apiErrorKey(error))),
  })
  const discard = useMutation({
    mutationFn: (id: string) => receiptsApi.remove(id),
    onSuccess: () => {
      invalidate()
      setDiscarding(null)
      toast.success(t('receipts.discarded'))
    },
    onError: () => toast.error(t('common.error')),
  })

  const receipts = data ?? []
  const pending = receipts.filter((r) => isPending(r.status))
  const settled = receipts.filter((r) => !isPending(r.status))

  const scanButton = canWrite ? (
    <div className="flex items-center gap-2">
      <Button variant="ghost" size="sm" className="gap-1.5" onClick={() => navigate('/receipts/setup')}>
        <Zap size={16} /> {t('receipts.capture.link')}
      </Button>
      <Button variant="outline" size="sm" className="gap-1.5" onClick={() => navigate('/products/scan')}>
        <Barcode size={16} /> {t('products.scanProduct')}
      </Button>
      <Button className="gap-1.5" onClick={() => navigate('/receipts/scan')}>
        <ScanLine size={16} /> {t('receipts.scan')}
      </Button>
    </div>
  ) : undefined

  return (
    <div className="space-y-6">
      <PageHeader section={t('nav.receipts')} title={t('receipts.title')} action={scanButton} />

      <ReceiptSummaryPanel locale={locale} dateLocale={dateLocale} />

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      ) : (
        <>
          {pending.length > 0 && (
            <section className="space-y-3">
              <div>
                <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Clock size={15} className="text-amber-600" />
                  {t('receipts.waitingTitle')}
                </h2>
                <p className="text-xs text-muted-foreground mt-0.5">{t('receipts.waitingHint')}</p>
              </div>
              {pending.map((receipt) => (
                <PendingRow
                  key={receipt.id}
                  receipt={receipt}
                  locale={dateLocale}
                  canWrite={canWrite}
                  retrying={retry.isPending && retry.variables === receipt.id}
                  onRetry={() => retry.mutate(receipt.id)}
                  onDiscard={() => setDiscarding(receipt)}
                />
              ))}
            </section>
          )}

          {settled.length === 0 && pending.length === 0 ? (
            <div className="bg-card rounded-xl border border-dashed border-border p-10 text-center">
              <ScanLine size={28} className="mx-auto mb-2 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">{t('receipts.empty')}</p>
              {canWrite && (
                <Button className="mt-4 gap-1.5" onClick={() => navigate('/receipts/scan')}>
                  <ScanLine size={16} /> {t('receipts.scanFirst')}
                </Button>
              )}
            </div>
          ) : settled.length > 0 ? (
            <section className="space-y-3">
              {pending.length > 0 && (
                <h2 className="text-sm font-semibold text-foreground">{t('receipts.listTitle')}</h2>
              )}
              <div className="space-y-2">
                {settled.map((receipt) => (
                  <button
                    key={receipt.id}
                    type="button"
                    onClick={() => navigate(`/receipts/${receipt.id}`)}
                    className="group flex w-full items-center gap-3 rounded-xl border border-border bg-card p-4 text-left shadow-sm hover:bg-muted/50 transition-colors"
                  >
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted">
                      <StoreIcon size={18} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-sm font-semibold">
                          {storeName(receipt, t('receipts.unknownStore'))}
                        </span>
                        {receipt.status !== 'authorized' && <ReceiptStatusBadge status={receipt.status} />}
                        {receipt.link.not_my_purchase && (
                          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                            {t('receipts.notMyPurchase')}
                          </span>
                        )}
                      </span>
                      <span className="block truncate text-[11px] text-muted-foreground">
                        {[
                          receipt.issued_at
                            ? new Date(receipt.issued_at).toLocaleDateString(dateLocale)
                            : new Date(receipt.first_scanned_at).toLocaleDateString(dateLocale),
                          receipt.items_count != null
                            ? t('receipts.itemCount', { count: receipt.items_count })
                            : null,
                          receipt.status !== 'authorized'
                            ? t('receipts.numberSeries', { number: receipt.number, series: receipt.series })
                            : null,
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      </span>
                    </span>
                    {receipt.total != null && (
                      <span className="shrink-0 text-sm font-bold tabular-nums">
                        {mask(formatCurrency(Number(receipt.total), CURRENCY, locale))}
                      </span>
                    )}
                    <ChevronRight
                      size={16}
                      className="shrink-0 text-muted-foreground group-hover:translate-x-0.5 transition-transform"
                    />
                  </button>
                ))}
              </div>
            </section>
          ) : null}
        </>
      )}

      <DeleteConfirmationDialog
        open={discarding !== null}
        title={t('receipts.discardTitle')}
        description={t('receipts.discardDesc')}
        isPending={discard.isPending}
        onClose={() => setDiscarding(null)}
        onConfirm={() => discarding && discard.mutate(discarding.id)}
      />
    </div>
  )
}

function PendingRow({
  receipt,
  locale,
  canWrite,
  retrying,
  onRetry,
  onDiscard,
}: {
  receipt: Receipt
  locale: string
  canWrite: boolean
  retrying: boolean
  onRetry: () => void
  onDiscard: () => void
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const paste = wantsPaste(receipt)
  // The panel opens by itself when the portal asked for a person: for
  // Espírito Santo that is the normal path and hiding it behind a click
  // would only teach people to wait for a retry that will never come.
  const [pasteOpen, setPasteOpen] = useState(paste)
  // The backend clears `next_attempt_at` whenever nothing is scheduled, so
  // its presence is the whole test.
  const next = receipt.next_attempt_at ? formatWhen(receipt.next_attempt_at, locale) : null

  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={() => navigate(`/receipts/${receipt.id}`)}
            className="text-left text-sm font-medium text-foreground hover:underline"
          >
            {storeName(receipt, t('receipts.numberSeries', { number: receipt.number, series: receipt.series }))}
          </button>
          <p className="text-[11px] text-muted-foreground">
            {receipt.store
              ? `${t('receipts.numberSeries', { number: receipt.number, series: receipt.series })} · ${receipt.uf}`
              : `${receipt.uf} · ${t('receipts.scannedOn', { date: new Date(receipt.first_scanned_at).toLocaleDateString(locale) })}`}
          </p>
          <ReceiptStatusMessage receipt={receipt} className="mt-1.5" />
          <p className="mt-0.5 text-[11px] text-muted-foreground tabular-nums">
            {t('receipts.attempts', { count: receipt.attempts })}
            {' · '}
            {next ? t('receipts.nextAttempt', { time: next }) : t('receipts.noNextAttempt')}
          </p>
        </div>
        <ReceiptStatusBadge status={receipt.status} />
      </div>

      {canWrite && (
        <div className="mt-3 flex flex-wrap gap-2">
          {canRetry(receipt) && (
            <Button size="sm" variant="outline" className="gap-1.5" disabled={retrying} onClick={onRetry}>
              <RefreshCw size={14} className={retrying ? 'animate-spin' : undefined} /> {t('receipts.retry')}
            </Button>
          )}
          <Button
            size="sm"
            variant={paste && !pasteOpen ? 'default' : 'outline'}
            className="gap-1.5"
            aria-expanded={pasteOpen}
            onClick={() => setPasteOpen((open) => !open)}
          >
            <ClipboardPaste size={14} /> {t('receipts.pastePage')}
          </Button>
          <Button size="sm" variant="ghost" className="gap-1.5 text-rose-600 hover:text-rose-700" onClick={onDiscard}>
            <Trash2 size={14} /> {t('receipts.discard')}
          </Button>
        </div>
      )}

      {canWrite && pasteOpen && (
        <ReceiptPastePanel receipt={receipt} className="mt-3" onDone={() => setPasteOpen(false)} />
      )}
    </div>
  )
}
