import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { statusMessageKey } from '@/lib/receipt-status'
import { cn } from '@/lib/utils'
import type { Receipt, ReceiptStatus } from '@/types'

// Same palette the installments and notifications pages use for their pills.
const STATUS_CLASS: Record<ReceiptStatus, string> = {
  authorized: 'bg-emerald-100 text-emerald-700',
  pending: 'bg-sky-100 text-sky-700',
  fetching: 'bg-sky-100 text-sky-700',
  waiting_sefaz: 'bg-amber-100 text-amber-700',
  parse_error: 'bg-amber-100 text-amber-700',
  gave_up: 'bg-rose-100 text-rose-700',
  invalid: 'bg-rose-100 text-rose-700',
  cancelled: 'bg-muted text-muted-foreground',
}

export function ReceiptStatusBadge({ status, className }: { status: ReceiptStatus; className?: string }) {
  const { t } = useTranslation()
  return (
    <Badge className={cn(STATUS_CLASS[status] ?? STATUS_CLASS.pending, className)}>
      {t(`receipts.status.${status}`)}
    </Badge>
  )
}

/** The one sentence that says what is going on with a receipt that is not
 *  authorised yet: specific to the reason, and what to do about it. */
export function ReceiptStatusMessage({
  receipt,
  className,
}: {
  receipt: Pick<Receipt, 'status' | 'status_reason' | 'uf'>
  className?: string
}) {
  const { t } = useTranslation()
  return (
    <p className={cn('text-xs text-foreground/80', className)}>
      {t(statusMessageKey(receipt), { uf: receipt.uf })}
    </p>
  )
}
