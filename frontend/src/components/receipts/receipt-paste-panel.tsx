import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ClipboardPaste, Copy, ExternalLink } from 'lucide-react'
import { receipts as receiptsApi } from '@/lib/api'
import { apiErrorKey } from '@/lib/receipt-status'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Receipt } from '@/types'

interface ReceiptPastePanelProps {
  receipt: Pick<Receipt, 'id' | 'qr_url' | 'status_reason'>
  /** Called with the receipt as the backend returned it after reading the page. */
  onDone?: (receipt: Receipt) => void
  className?: string
}

/**
 * The paste path. For Espírito Santo it is how a receipt normally gets read:
 * the portal shows a machine a Cloudflare Turnstile challenge, so the person
 * opens the QR link in a browser, passes the check, selects all, copies, and
 * pastes here. Whatever landed — the page's HTML, Chrome's view-source dump,
 * or the plain text a phone copies — is sent as-is; the backend normalises.
 */
export function ReceiptPastePanel({ receipt, onDone, className }: ReceiptPastePanelProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const [errorKey, setErrorKey] = useState<string | null>(null)

  /** iOS reports a home-screen install here; every other platform leaves
   *  it undefined, which reads as false. */
  const standalone =
    typeof navigator !== 'undefined' &&
    (navigator as Navigator & { standalone?: boolean }).standalone === true

  const copyUrl = async () => {
    if (!receipt.qr_url) return
    try {
      await navigator.clipboard.writeText(receipt.qr_url)
      toast.success(t('receipts.paste.linkCopied'))
    } catch {
      toast.error(t('receipts.capture.copyFailed'))
    }
  }

  const submit = useMutation({
    mutationFn: (html: string) => receiptsApi.submitHtml(receipt.id, html),
    onSuccess: (updated) => {
      setText('')
      setErrorKey(null)
      queryClient.invalidateQueries({ queryKey: ['receipts'] })
      toast.success(
        t(updated.status === 'cancelled' ? 'receipts.paste.cancelled' : 'receipts.paste.success'),
      )
      onDone?.(updated)
    },
    onError: (error) => setErrorKey(apiErrorKey(error)),
  })

  const canSubmit = text.trim() !== '' && !submit.isPending

  return (
    <div
      className={cn(
        'rounded-xl border border-amber-200 bg-amber-50/60 p-4 space-y-3 dark:border-amber-900/60 dark:bg-amber-950/20',
        className,
      )}
    >
      <p className="flex items-center gap-2 text-sm font-medium text-foreground">
        <ClipboardPaste size={16} className="text-amber-600" />
        {t('receipts.paste.title')}
      </p>
      <p className="text-xs text-muted-foreground">{t('receipts.paste.intro')}</p>

      {/* A URL the portal has already refused is not worth offering: it
          would open the same "QR Code Inválido" every time. The key is
          what the person consults with instead. */}
      {receipt.status_reason === 'qr_rejected' ? (
        <p className="text-xs text-muted-foreground">{t('receipts.paste.qrRefused')}</p>
      ) : receipt.qr_url ? (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline" size="sm" className="gap-1.5">
              <a href={receipt.qr_url} target="_blank" rel="noopener noreferrer">
                <ExternalLink size={14} />
                {t('receipts.paste.open')}
              </a>
            </Button>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => void copyUrl()}>
              <Copy size={14} />
              {t('receipts.paste.copyLink')}
            </Button>
          </div>
          {/* Installed to the home screen, iOS opens links in an in-app
              browser: it renders the note, but it has no bookmarks, so the
              capture bookmarklet is not reachable there. And the address it
              ends on cannot be carried to Safari — the portal redirects to a
              page whose `cid` names a server-side session, meaningless
              anywhere else. The original QR link is the one that travels. */}
          {standalone && (
            <p className="text-xs text-muted-foreground">{t('receipts.paste.standaloneHint')}</p>
          )}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">{t('receipts.paste.noUrl')}</p>
      )}

      <textarea
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          if (errorKey) setErrorKey(null)
        }}
        rows={5}
        aria-label={t('receipts.paste.title')}
        placeholder={t('receipts.paste.placeholder')}
        disabled={submit.isPending}
        className="w-full rounded-md border border-input bg-card px-3 py-2 text-sm font-mono shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/30 focus-visible:ring-[2px] disabled:opacity-50"
      />

      {errorKey && (
        <p role="alert" className="text-xs text-rose-600">
          {t(errorKey)}
        </p>
      )}

      <div className="flex justify-end">
        <Button onClick={() => submit.mutate(text)} disabled={!canSubmit} className="gap-1.5">
          {submit.isPending ? t('receipts.paste.submitting') : t('receipts.paste.submit')}
        </Button>
      </div>
    </div>
  )
}
