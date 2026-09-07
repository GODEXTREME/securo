import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, Barcode, Camera, CameraOff, Loader2, Store as StoreIcon } from 'lucide-react'
import { products as productsApi } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { createBarcodeDetector, readQr, type QrDetector } from '@/lib/qr-scanner'
import { useDateLocale, useDisplayLocale } from '@/hooks/use-display-locale'
import { formatCurrency } from '@/lib/format'
import { priceLabel } from '@/lib/product-format'
import type { CandidateItem, GtinLookup } from '@/types'

const CURRENCY = 'BRL'
/** A barcode takes longer to line up than a QR; reading a little less
 *  often keeps a phone cool without costing a scan. */
const DETECT_EVERY_MS = 200

type CameraState = 'starting' | 'scanning' | 'denied' | 'unavailable' | 'insecure' | 'stopped'

const CAMERA_MESSAGE: Partial<Record<CameraState, string>> = {
  denied: 'receipts.cameraDenied',
  unavailable: 'receipts.cameraUnavailable',
  insecure: 'receipts.cameraInsecure',
}

export default function ProductScanPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const locale = useDisplayLocale()
  const dateLocale = useDateLocale()
  const queryClient = useQueryClient()
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const detectorRef = useRef<QrDetector | null>(null)
  const [camera, setCamera] = useState<CameraState>('starting')
  const [ready, setReady] = useState(false)
  const [manual, setManual] = useState('')
  const [answer, setAnswer] = useState<GtinLookup | null>(null)

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
  }, [])

  const startCamera = useCallback(async () => {
    if (!window.isSecureContext) return setCamera('insecure')
    if (!navigator.mediaDevices?.getUserMedia) return setCamera('unavailable')
    setCamera('starting')
    try {
      let stream: MediaStream
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
      } catch (error) {
        if ((error as DOMException).name !== 'OverconstrainedError') throw error
        stream = await navigator.mediaDevices.getUserMedia({ video: true })
      }
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play().catch(() => {})
      }
      setCamera('scanning')
    } catch (error) {
      const name = (error as DOMException).name
      setCamera(name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'unavailable')
    }
  }, [])

  const lookup = useMutation({
    mutationFn: (gtin: string) => productsApi.byGtin(gtin),
    onSuccess: (result) => {
      setAnswer(result)
      stopCamera()
      setCamera('stopped')
    },
    onError: () => {
      toast.error(t('products.lookupFailed'))
      if (!streamRef.current) void startCamera()
    },
  })
  const ask = lookup.mutate

  const link = useMutation({
    mutationFn: ({ productId, gtin }: { productId: string; gtin: string }) =>
      productsApi.linkGtin(productId, gtin),
    onSuccess: (product) => {
      queryClient.invalidateQueries({ queryKey: ['product'] })
      queryClient.invalidateQueries({ queryKey: ['receipts'] })
      toast.success(t('products.linked'))
      navigate(`/products/${product.id}`)
    },
    onError: () => toast.error(t('products.linkFailed')),
  })

  useEffect(() => {
    let cancelled = false
    createBarcodeDetector()
      .then((detector) => {
        if (cancelled) return
        detectorRef.current = detector
        setReady(true)
      })
      .catch(() => undefined)
    void startCamera()
    return () => {
      cancelled = true
      stopCamera()
    }
  }, [startCamera, stopCamera])

  useEffect(() => {
    if (camera !== 'scanning' || !ready) return
    let busy = false
    let done = false
    const timer = window.setInterval(async () => {
      const video = videoRef.current
      const detector = detectorRef.current
      if (busy || done || !video || !detector || video.readyState < 2) return
      busy = true
      try {
        const value = await readQr(detector, video)
        if (value && !done) {
          done = true
          ask(value)
        }
      } catch {
        // Nothing readable in this frame; the next one is 200 ms away.
      } finally {
        busy = false
      }
    }, DETECT_EVERY_MS)
    return () => window.clearInterval(timer)
  }, [camera, ready, ask])

  const scanAgain = () => {
    setAnswer(null)
    void startCamera()
  }

  const busy = lookup.isPending || link.isPending
  const cameraMessage = CAMERA_MESSAGE[camera]

  return (
    <div className="space-y-6">
      <PageHeader
        section={t('nav.receipts')}
        title={t('products.scanTitle')}
        action={
          <Button asChild variant="ghost" size="sm" className="gap-1.5">
            <Link to="/receipts">
              <ArrowLeft size={16} /> {t('receipts.backToList')}
            </Link>
          </Button>
        }
      />

      {!answer && (
        <>
          <div className="relative overflow-hidden rounded-xl border border-border bg-black shadow-sm">
            <video
              ref={videoRef}
              playsInline
              muted
              autoPlay
              aria-label={t('products.scanTitle')}
              className="block w-full aspect-[3/4] object-cover sm:aspect-video"
            />
            {camera === 'scanning' && (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                <div className="h-24 w-64 rounded-xl border-2 border-white/80 shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]" />
              </div>
            )}
            <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent px-4 pb-4 pt-8 text-center text-xs text-white">
              {busy ? (
                <span className="inline-flex items-center gap-1.5">
                  <Loader2 size={14} className="animate-spin" /> {t('products.looking')}
                </span>
              ) : camera === 'starting' ? (
                t('receipts.cameraStarting')
              ) : camera === 'scanning' ? (
                t('products.scanHint')
              ) : cameraMessage ? (
                <span className="inline-flex items-center gap-1.5">
                  <CameraOff size={14} /> {t(cameraMessage)}
                </span>
              ) : null}
            </div>
          </div>

          {camera !== 'scanning' && camera !== 'starting' && !busy && (
            <Button variant="outline" className="w-full gap-1.5 sm:w-auto" onClick={() => void startCamera()}>
              <Camera size={16} /> {t('receipts.retryCamera')}
            </Button>
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault()
              const value = manual.trim()
              if (value) ask(value)
            }}
            className="space-y-2 rounded-xl border border-border bg-card p-4 shadow-sm"
          >
            <label htmlFor="gtin" className="flex items-center gap-2 text-sm font-medium">
              <Barcode size={15} className="text-muted-foreground" /> {t('products.orType')}
            </label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                id="gtin"
                value={manual}
                onChange={(e) => setManual(e.target.value)}
                inputMode="numeric"
                autoComplete="off"
                placeholder="7891234567895"
                disabled={busy}
              />
              <Button type="submit" disabled={busy || manual.trim() === ''}>
                {t('products.look')}
              </Button>
            </div>
          </form>
        </>
      )}

      {answer && (
        <Answer
          answer={answer}
          locale={locale}
          dateLocale={dateLocale}
          linking={link.isPending}
          onLink={(candidate) => {
            if (candidate.product_id) link.mutate({ productId: candidate.product_id, gtin: answer.gtin })
          }}
          onAgain={scanAgain}
        />
      )}
    </div>
  )
}

function Answer({
  answer,
  locale,
  dateLocale,
  linking,
  onLink,
  onAgain,
}: {
  answer: GtinLookup
  locale: string
  dateLocale: string
  linking: boolean
  onLink: (candidate: CandidateItem) => void
  onAgain: () => void
}) {
  const { t } = useTranslation()
  const detail = answer.product

  return (
    <div className="space-y-4">
      <div className="space-y-2 rounded-xl border border-border bg-card p-4 shadow-sm">
        <p className="inline-flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
          <Barcode size={13} /> {answer.gtin}
        </p>

        {detail ? (
          <>
            <Link to={`/products/${detail.product.id}`} className="block text-lg font-semibold hover:underline">
              {detail.product.name}
            </Link>
            {detail.last_paid ? (
              <p className="text-sm">
                {t('products.youPaid', {
                  price: formatCurrency(Number(detail.last_paid.unit_price), CURRENCY, locale),
                  store: detail.last_paid.store_name ?? t('receipts.unknownStore'),
                  date: new Date(detail.last_paid.observed_on).toLocaleDateString(dateLocale),
                })}
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">{t('products.noPurchases')}</p>
            )}
            {detail.best_price_30d && (
              <p className="text-xs text-muted-foreground">
                {t('products.bestWas', {
                  price: formatCurrency(Number(detail.best_price_30d.unit_price), CURRENCY, locale),
                  store: detail.best_price_30d.store_name ?? t('receipts.unknownStore'),
                })}{' '}
                · {priceLabel(detail.best_price_30d, locale, t)}
              </p>
            )}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">{t('products.unknownGtin')}</p>
        )}
      </div>

      {!detail && (
        <div className="space-y-2 rounded-xl border border-border bg-card p-4 shadow-sm">
          <p className="text-sm font-medium">{t('products.pickLine')}</p>
          <p className="text-xs text-muted-foreground">{t('products.pickLineHint')}</p>
          {answer.candidates.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('products.noCandidates')}</p>
          ) : (
            <ul className="divide-y divide-border">
              {answer.candidates.map((candidate) => (
                <li key={candidate.receipt_item_id} className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm">{candidate.product_name || candidate.description}</p>
                    <p className="flex items-center gap-1 truncate text-[11px] text-muted-foreground">
                      <StoreIcon size={11} /> {candidate.store_name ?? t('receipts.unknownStore')}
                      {candidate.issued_on && ` · ${new Date(candidate.issued_on).toLocaleDateString(dateLocale)}`}
                      {` · ${formatCurrency(Number(candidate.unit_price), CURRENCY, locale)}`}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={linking || !candidate.product_id}
                    onClick={() => onLink(candidate)}
                  >
                    {t('products.thisOne')}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <Button variant="outline" className="w-full gap-1.5 sm:w-auto" onClick={onAgain}>
        <Barcode size={16} /> {t('products.scanAnother')}
      </Button>
    </div>
  )
}
