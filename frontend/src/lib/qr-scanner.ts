/**
 * One code reader for every browser the app meets.
 *
 * Chrome on Android ships `BarcodeDetector`; Safari on iOS — the device this
 * feature is mostly used on — ships nothing. Where the native API exists and
 * reads QR codes it is used as-is. Otherwise the `barcode-detector` ponyfill
 * is loaded on demand, and its WebAssembly is served from this app's own
 * build rather than the jsDelivr URL the package defaults to: a self-hosted
 * finance app should not phone a CDN to read a receipt, and a CSP that only
 * allows `'self'` would block it anyway.
 */
import type { BarcodeFormat } from 'barcode-detector'

export interface DetectedQr {
  rawValue: string
}

export interface QrDetector {
  detect(source: ImageBitmapSource): Promise<DetectedQr[]>
}

/** The QR on a receipt. */
export const QR_FORMATS = ['qr_code'] as const

/**
 * The barcode on a product. The retail GS1 set and nothing else: a
 * shelf label or a courier sticker in the same frame should not be read
 * as a product, and `normalize_gtin` on the server accepts exactly the
 * lengths these formats produce.
 */
export const PRODUCT_FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e'] as const

/** Ours is a subset of what the ponyfill reads; naming its type here is
 *  what makes adding a format to the lists above a type error if the
 *  ponyfill does not know it. */
export type CodeFormat = Extract<BarcodeFormat, (typeof QR_FORMATS)[number] | (typeof PRODUCT_FORMATS)[number]>

// lib.dom has no BarcodeDetector yet; this is the slice of the spec used here.
interface NativeBarcodeDetectorCtor {
  new (options?: { formats?: CodeFormat[] }): QrDetector
  getSupportedFormats?: () => Promise<readonly string[]>
}

async function nativeDetector(wanted: readonly CodeFormat[]): Promise<QrDetector | null> {
  const ctor = (globalThis as unknown as { BarcodeDetector?: NativeBarcodeDetectorCtor }).BarcodeDetector
  if (typeof ctor !== 'function') return null
  try {
    const supported = ctor.getSupportedFormats ? await ctor.getSupportedFormats() : [...wanted]
    // Partial support is still support: a native reader that knows EAN-13
    // but not UPC-E is better than loading a megabyte of WebAssembly.
    const usable = wanted.filter((format) => supported.includes(format))
    return usable.length > 0 ? new ctor({ formats: usable }) : null
  } catch {
    return null
  }
}

//: The WebAssembly is prepared once for the page. Two readers over one
//: module: the receipt scanner wants QR, the product scanner wants the
//: retail barcodes, and neither should pay for the other's download.
let ponyfillModule: Promise<typeof import('barcode-detector/ponyfill')> | null = null
const ponyfills = new Map<string, Promise<QrDetector>>()

function loadPonyfill(): Promise<typeof import('barcode-detector/ponyfill')> {
  ponyfillModule ??= (async () => {
    const [mod, { default: wasmUrl }] = await Promise.all([
      import('barcode-detector/ponyfill'),
      // Vite copies the binary into the build and hands back its hashed URL.
      import('zxing-wasm/reader/zxing_reader.wasm?url'),
    ])
    mod.prepareZXingModule({
      overrides: {
        locateFile: (path: string, prefix: string) =>
          path.endsWith('.wasm') ? wasmUrl : prefix + path,
      },
    })
    return mod
  })()
  return ponyfillModule
}

function ponyfillDetector(formats: readonly CodeFormat[]): Promise<QrDetector> {
  const key = [...formats].sort().join(',')
  const existing = ponyfills.get(key)
  if (existing) return existing
  const ready = loadPonyfill().then(({ BarcodeDetector }) => new BarcodeDetector({ formats: [...formats] }))
  ponyfills.set(key, ready)
  return ready
}

/** Native where it reads these formats, the ponyfill everywhere else. */
export async function createDetector(formats: readonly CodeFormat[]): Promise<QrDetector> {
  return (await nativeDetector(formats)) ?? ponyfillDetector(formats)
}

/** The receipt scanner's reader. */
export function createQrDetector(): Promise<QrDetector> {
  return createDetector(QR_FORMATS)
}

/** The product scanner's reader. */
export function createBarcodeDetector(): Promise<QrDetector> {
  return createDetector(PRODUCT_FORMATS)
}

/** The first non-empty payload in a frame, or null. */
export async function readQr(detector: QrDetector, source: ImageBitmapSource): Promise<string | null> {
  const found = await detector.detect(source)
  const hit = found.find((code) => code.rawValue && code.rawValue.trim() !== '')
  return hit ? hit.rawValue.trim() : null
}

/**
 * Read a photo the user picked. Decoded to a bitmap first: both the native
 * API and the ponyfill accept one, and it sidesteps the browsers that will
 * not detect straight from a `File`.
 */
export async function readQrFromFile(detector: QrDetector, file: Blob): Promise<string | null> {
  const bitmap = await createImageBitmap(file)
  try {
    return await readQr(detector, bitmap)
  } finally {
    bitmap.close()
  }
}
