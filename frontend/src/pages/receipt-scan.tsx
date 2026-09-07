import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, Camera, CameraOff, ImagePlus, Link2, Loader2, ScanLine } from 'lucide-react'
import { receipts as receiptsApi } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { createQrDetector, readQr, readQrFromFile, type QrDetector } from '@/lib/qr-scanner'
import { apiErrorKey } from '@/lib/receipt-status'

/** How often a frame is read. QR codes decode in a few milliseconds; the
 *  interval is what keeps a phone from running its CPU flat out. */
const DETECT_EVERY_MS = 150

type CameraState =
  | 'starting'
  | 'scanning'
  | 'denied'
  | 'unavailable'
  | 'insecure'
  | 'stopped'
type ReaderState = 'loading' | 'ready' | 'failed'

const CAMERA_MESSAGE: Partial<Record<CameraState, string>> = {
  denied: 'receipts.cameraDenied',
  unavailable: 'receipts.cameraUnavailable',
  insecure: 'receipts.cameraInsecure',
}

export default function ReceiptScanPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const detectorRef = useRef<QrDetector | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [camera, setCamera] = useState<CameraState>('starting')
  const [reader, setReader] = useState<ReaderState>('loading')
  const [manual, setManual] = useState('')
  const [errorKey, setErrorKey] = useState<string | null>(null)
  const [photoBusy, setPhotoBusy] = useState(false)

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
  }, [])

  const startCamera = useCallback(async () => {
    if (!window.isSecureContext) {
      setCamera('insecure')
      return
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setCamera('unavailable')
      return
    }
    setCamera('starting')
    try {
      let stream: MediaStream
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
      } catch (error) {
        // A laptop has no rear camera; take whatever there is.
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

  const scan = useMutation({
    mutationFn: (payload: string) => receiptsApi.scan(payload),
    onSuccess: (result) => {
      stopCamera()
      setCamera('stopped')
      queryClient.invalidateQueries({ queryKey: ['receipts'] })
      toast.success(t(result.already_linked ? 'receipts.alreadyScanned' : 'receipts.scanned'))
      navigate(`/receipts/${result.receipt.id}`, { replace: true })
    },
    onError: (error) => {
      setErrorKey(apiErrorKey(error))
      // The code was read fine and the server did not like it; let the
      // person aim at another one without a page reload.
      if (!streamRef.current) void startCamera()
    },
  })
  const submitPayload = scan.mutate

  // Camera and reader come up together and independently; whichever is
  // slower gates the first read.
  useEffect(() => {
    let cancelled = false
    createQrDetector()
      .then((detector) => {
        if (cancelled) return
        detectorRef.current = detector
        setReader('ready')
      })
      .catch(() => {
        if (!cancelled) setReader('failed')
      })
    void startCamera()
    return () => {
      cancelled = true
      stopCamera()
    }
  }, [startCamera, stopCamera])

  // The read loop. Runs only while there is a live stream and a reader; the
  // first payload stops the camera and goes to the server.
  useEffect(() => {
    if (camera !== 'scanning' || reader !== 'ready') return
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
          stopCamera()
          setCamera('stopped')
          setErrorKey(null)
          submitPayload(value)
        }
      } catch {
        // A frame that could not be decoded: the next one is 150 ms away.
      } finally {
        busy = false
      }
    }, DETECT_EVERY_MS)
    return () => window.clearInterval(timer)
  }, [camera, reader, stopCamera, submitPayload])

  const onManualSubmit = (event: FormEvent) => {
    event.preventDefault()
    const payload = manual.trim()
    if (!payload) return
    setErrorKey(null)
    scan.mutate(payload)
  }

  const onPhoto = async (file: File | undefined) => {
    if (!file) return
    setErrorKey(null)
    setPhotoBusy(true)
    try {
      const detector = detectorRef.current ?? (await createQrDetector())
      detectorRef.current = detector
      const value = await readQrFromFile(detector, file)
      if (value) scan.mutate(value)
      else setErrorKey('receipts.photoNoQr')
    } catch {
      setErrorKey('receipts.photoNoQr')
    } finally {
      setPhotoBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const busy = scan.isPending || photoBusy
  const cameraMessage = CAMERA_MESSAGE[camera]

  return (
    <div className="space-y-6">
      <PageHeader
        section={t('nav.receipts')}
        title={t('receipts.scanTitle')}
        action={
          <Button asChild variant="ghost" size="sm" className="gap-1.5">
            <Link to="/receipts">
              <ArrowLeft size={16} /> {t('receipts.backToList')}
            </Link>
          </Button>
        }
      />

      <div className="relative overflow-hidden rounded-xl border border-border bg-black shadow-sm">
        <video
          ref={videoRef}
          playsInline
          muted
          autoPlay
          aria-label={t('receipts.scanTitle')}
          className="block w-full aspect-[3/4] object-cover sm:aspect-video"
        />
        {camera === 'scanning' && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div className="h-56 w-56 rounded-2xl border-2 border-white/80 shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]" />
          </div>
        )}
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent px-4 pb-4 pt-8 text-center text-xs text-white">
          {busy ? (
            <span className="inline-flex items-center gap-1.5">
              <Loader2 size={14} className="animate-spin" /> {t('receipts.reading')}
            </span>
          ) : camera === 'starting' ? (
            t('receipts.cameraStarting')
          ) : camera === 'scanning' && reader === 'loading' ? (
            t('receipts.detectorLoading')
          ) : camera === 'scanning' && reader === 'failed' ? (
            t('receipts.detectorFailed')
          ) : camera === 'scanning' ? (
            t('receipts.scanHint')
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

      {errorKey && (
        <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">
          {t(errorKey)}
        </p>
      )}

      <form onSubmit={onManualSubmit} className="space-y-2 rounded-xl border border-border bg-card p-4 shadow-sm">
        <label htmlFor="receipt-payload" className="flex items-center gap-2 text-sm font-medium">
          <Link2 size={15} className="text-muted-foreground" /> {t('receipts.orPaste')}
        </label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            id="receipt-payload"
            value={manual}
            onChange={(e) => setManual(e.target.value)}
            placeholder={t('receipts.pastePlaceholder')}
            inputMode="text"
            autoComplete="off"
            disabled={busy}
          />
          <Button type="submit" disabled={busy || manual.trim() === ''} className="gap-1.5">
            <ScanLine size={16} /> {t('receipts.submit')}
          </Button>
        </div>
      </form>

      <div className="space-y-2 rounded-xl border border-border bg-card p-4 shadow-sm">
        <p className="flex items-center gap-2 text-sm font-medium">
          <ImagePlus size={15} className="text-muted-foreground" /> {t('receipts.orPhoto')}
        </p>
        {/* No `capture`: it would send the phone straight to the camera, and
            the camera is the loop above. This button is for the photo already
            in the roll — the receipt someone snapped at the till. Without it
            the picker still offers the camera as one of its choices. */}
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          className="sr-only"
          aria-label={t('receipts.choosePhoto')}
          disabled={busy}
          onChange={(e) => void onPhoto(e.target.files?.[0])}
        />
        <Button
          type="button"
          variant="outline"
          className="w-full gap-1.5 sm:w-auto"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
        >
          <ImagePlus size={16} /> {t('receipts.choosePhoto')}
        </Button>
      </div>
    </div>
  )
}
