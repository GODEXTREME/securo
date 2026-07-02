import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { connections } from '@/lib/api'
import { invalidateFinancialQueries } from '@/lib/invalidate-queries'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { ExternalLink } from 'lucide-react'
import { toast } from 'sonner'

interface TokenConnectDialogProps {
  open: boolean
  onClose: () => void
  provider: string
}

const PROVIDER_BRIDGE_URLS: Record<string, string> = {
  simplefin: 'https://bridge.simplefin.org/simplefin/create',
}

export function TokenConnectDialog({ open, onClose, provider }: TokenConnectDialogProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [token, setToken] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) {
      setToken('')
      setSubmitting(false)
    }
  }, [open])

  const bridgeUrl = PROVIDER_BRIDGE_URLS[provider]
  const i18nKey = `accounts.tokenConnect.${provider}`

  const handleSubmit = async () => {
    if (!token.trim()) return
    setSubmitting(true)
    try {
      await connections.handleCallback(token.trim(), provider)
      invalidateFinancialQueries(queryClient)
      queryClient.invalidateQueries({ queryKey: ['connections'] })
      toast.success(t('accounts.connected'))
      onClose()
    } catch (err) {
      const detail =
        axios.isAxiosError(err) && err.response?.data?.detail
          ? typeof err.response.data.detail === 'string'
            ? err.response.data.detail
            : err.response.data.detail.message
          : null
      toast.error(detail || t('accounts.connectError'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && !submitting && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t(`${i18nKey}.title`, t('accounts.tokenConnect.defaultTitle'))}</DialogTitle>
          <p className="text-sm text-muted-foreground">
            {t(`${i18nKey}.description`, t('accounts.tokenConnect.defaultDescription'))}
          </p>
        </DialogHeader>

        {bridgeUrl && (
          <Button asChild variant="outline" className="w-full justify-between">
            <a href={bridgeUrl} target="_blank" rel="noreferrer">
              <span>{t('accounts.tokenConnect.openBridge')}</span>
              <ExternalLink size={14} />
            </a>
          </Button>
        )}

        <div className="space-y-1.5">
          <label className="text-sm font-medium" htmlFor="securo-token-input">
            {t('accounts.tokenConnect.tokenLabel')}
          </label>
          <textarea
            id="securo-token-input"
            className="w-full min-h-[110px] rounded-md border border-input bg-background px-3 py-2 text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-0"
            placeholder={t('accounts.tokenConnect.tokenPlaceholder')}
            value={token}
            onChange={(e) => setToken(e.target.value)}
            spellCheck={false}
            autoComplete="off"
            disabled={submitting}
          />
          <p className="text-xs text-muted-foreground">
            {t('accounts.tokenConnect.tokenHelp')}
          </p>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={!token.trim() || submitting}>
            {submitting
              ? t('accounts.tokenConnect.connecting')
              : t('accounts.tokenConnect.connect')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
