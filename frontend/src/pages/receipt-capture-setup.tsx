import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, Copy, KeyRound, Plus, Trash2 } from 'lucide-react'
import { receiptCapture } from '@/lib/api'
import { buildBookmarklet } from '@/lib/capture-bookmarklet'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { CaptureTokenCreated } from '@/types'

export default function ReceiptCaptureSetupPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [label, setLabel] = useState('')
  // Held in memory only: the server hands the secret over once, and after
  // a reload the only copy is the one in the bookmark.
  const [fresh, setFresh] = useState<CaptureTokenCreated | null>(null)

  const tokens = useQuery({ queryKey: ['receipt-capture-tokens'], queryFn: receiptCapture.tokens })

  const create = useMutation({
    mutationFn: () => receiptCapture.createToken(label.trim() || undefined),
    onSuccess: (created) => {
      setFresh(created)
      setLabel('')
      queryClient.invalidateQueries({ queryKey: ['receipt-capture-tokens'] })
    },
    onError: () => toast.error(t('receipts.capture.createFailed')),
  })

  const revoke = useMutation({
    mutationFn: (id: string) => receiptCapture.revokeToken(id),
    onSuccess: (_data, id) => {
      if (fresh?.token.id === id) setFresh(null)
      queryClient.invalidateQueries({ queryKey: ['receipt-capture-tokens'] })
      toast.success(t('receipts.capture.revoked'))
    },
    onError: () => toast.error(t('receipts.capture.revokeFailed')),
  })

  const code = fresh ? buildBookmarklet(window.location.origin, fresh.secret) : null

  const copy = async () => {
    if (!code) return
    try {
      await navigator.clipboard.writeText(code)
      toast.success(t('receipts.capture.copied'))
    } catch {
      toast.error(t('receipts.capture.copyFailed'))
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        section={t('nav.receipts')}
        title={t('receipts.capture.title')}
        action={
          <Button asChild variant="ghost" size="sm" className="gap-1.5">
            <Link to="/receipts">
              <ArrowLeft size={16} /> {t('receipts.backToList')}
            </Link>
          </Button>
        }
      />

      <div className="space-y-2 rounded-xl border border-border bg-card p-4 shadow-sm">
        <p className="text-sm text-muted-foreground">{t('receipts.capture.intro')}</p>
        <ol className="ml-4 list-decimal space-y-1 text-sm text-muted-foreground">
          <li>{t('receipts.capture.step1')}</li>
          <li>{t('receipts.capture.step2')}</li>
          <li>{t('receipts.capture.step3')}</li>
        </ol>
      </div>

      <div className="space-y-3 rounded-xl border border-border bg-card p-4 shadow-sm">
        <p className="flex items-center gap-2 text-sm font-medium">
          <KeyRound size={15} className="text-muted-foreground" /> {t('receipts.capture.newToken')}
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={t('receipts.capture.labelPlaceholder')}
            maxLength={80}
            disabled={create.isPending}
          />
          <Button onClick={() => create.mutate()} disabled={create.isPending} className="gap-1.5">
            <Plus size={16} /> {t('receipts.capture.create')}
          </Button>
        </div>

        {code && (
          <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 dark:border-amber-900/60 dark:bg-amber-950/30">
            <p className="text-sm font-medium">{t('receipts.capture.readyTitle')}</p>
            <p className="text-xs text-muted-foreground">{t('receipts.capture.readyHint')}</p>
            <textarea
              readOnly
              value={code}
              onFocus={(e) => e.currentTarget.select()}
              className="h-24 w-full rounded-md border border-border bg-background p-2 font-mono text-[11px]"
              aria-label={t('receipts.capture.title')}
            />
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => void copy()}>
              <Copy size={14} /> {t('receipts.capture.copy')}
            </Button>
          </div>
        )}
      </div>

      <div className="space-y-2 rounded-xl border border-border bg-card p-4 shadow-sm">
        <p className="text-sm font-medium">{t('receipts.capture.existing')}</p>
        {tokens.data && tokens.data.length > 0 ? (
          <ul className="divide-y divide-border">
            {tokens.data.map((token) => (
              <li key={token.id} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm">{token.label || t('receipts.capture.unnamed')}</p>
                  <p className="font-mono text-xs text-muted-foreground">
                    {token.prefix}…{' '}
                    {token.last_used_at
                      ? t('receipts.capture.lastUsed', { date: new Date(token.last_used_at).toLocaleDateString() })
                      : t('receipts.capture.neverUsed')}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="gap-1.5 text-rose-600"
                  disabled={revoke.isPending}
                  onClick={() => revoke.mutate(token.id)}
                >
                  <Trash2 size={14} /> {t('receipts.capture.revoke')}
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">{t('receipts.capture.none')}</p>
        )}
      </div>
    </div>
  )
}
