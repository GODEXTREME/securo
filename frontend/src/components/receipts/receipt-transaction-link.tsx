import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Link2, Link2Off, Loader2 } from 'lucide-react'
import { receipts as receiptsApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { formatCurrency } from '@/lib/format'
import type { Receipt } from '@/types'

const CURRENCY = 'BRL'

/**
 * Tying a note to the charge it produced.
 *
 * The suggestion is deliberately narrow — a debit within a few days and
 * a couple of reais — and the two numbers that justify each one are on
 * screen. A close amount on a close date is a good reason to ask a
 * person; it is not a reason to decide for them, so nothing here links
 * anything without a click.
 */
export function ReceiptTransactionLink({
  receipt,
  locale,
  dateLocale,
  canWrite,
}: {
  receipt: Receipt
  locale: string
  dateLocale: string
  canWrite: boolean
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const linked = receipt.link.transaction_id

  const { data: candidates, isLoading } = useQuery({
    queryKey: ['receipt-candidates', receipt.id],
    queryFn: () => receiptsApi.transactionCandidates(receipt.id),
    // Nothing to suggest for a note that is not read yet, and nothing to
    // replace once one is chosen.
    enabled: canWrite && !linked && receipt.status === 'authorized',
  })

  const link = useMutation({
    mutationFn: (transactionId: string | null) =>
      receiptsApi.update(
        receipt.id,
        transactionId === null ? { clear_transaction: true } : { transaction_id: transactionId },
      ),
    onSuccess: (_data, transactionId) => {
      queryClient.invalidateQueries({ queryKey: ['receipt', receipt.id] })
      queryClient.invalidateQueries({ queryKey: ['receipts'] })
      queryClient.invalidateQueries({ queryKey: ['receipt-candidates', receipt.id] })
      toast.success(t(transactionId === null ? 'receipts.link.cleared' : 'receipts.link.linked'))
    },
    onError: () => toast.error(t('common.error')),
  })

  if (!canWrite || receipt.status !== 'authorized') return null

  return (
    <section className="space-y-3 rounded-xl border border-border bg-card p-4 shadow-sm">
      <div>
        <p className="flex items-center gap-2 text-sm font-medium">
          <Link2 size={15} className="text-muted-foreground" /> {t('receipts.link.title')}
        </p>
        <p className="text-xs text-muted-foreground">{t('receipts.link.hint')}</p>
      </div>

      {linked ? (
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm">{t('receipts.link.isLinked')}</p>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            disabled={link.isPending}
            onClick={() => link.mutate(null)}
          >
            <Link2Off size={14} /> {t('receipts.link.unlink')}
          </Button>
        </div>
      ) : isLoading ? (
        <p className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> {t('receipts.link.looking')}
        </p>
      ) : candidates && candidates.length > 0 ? (
        <ul className="divide-y divide-border">
          {candidates.map((candidate) => (
            <li key={candidate.id} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm">{candidate.payee || candidate.description}</p>
                <p className="text-[11px] text-muted-foreground tabular-nums">
                  {new Date(`${candidate.date}T00:00:00`).toLocaleDateString(dateLocale)} ·{' '}
                  {formatCurrency(Number(candidate.amount), CURRENCY, locale)}
                  {Number(candidate.amount_difference) !== 0 &&
                    ` · ${t('receipts.link.off', {
                      amount: formatCurrency(Number(candidate.amount_difference), CURRENCY, locale),
                    })}`}
                  {candidate.days_apart > 0 && ` · ${t('receipts.link.daysApart', { count: candidate.days_apart })}`}
                </p>
              </div>
              <Button size="sm" variant="outline" disabled={link.isPending} onClick={() => link.mutate(candidate.id)}>
                {t('receipts.link.thisOne')}
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">{t('receipts.link.none')}</p>
      )}
    </section>
  )
}
