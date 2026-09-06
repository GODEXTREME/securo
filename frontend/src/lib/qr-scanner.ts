/**
 * One QR reader for every browser the app meets.
 *
 * Chrome on Android ships `BarcodeDetector`; Safari on iOS — the device this
 * feature is mostly used on — ships nothing. Where the native API exists and
 * reads QR codes it is used as-is. Otherwise the `barcode-detector` ponyfill
 * is loaded on demand, and its WebAssembly is served from this app's own
 * build rather than the jsDelivr URL the package defaults to: a self-hosted
 * finance app should not phone a CDN to read a receipt, and a CSP that only
 * allows `'self'` would block it anyway.
 */

export interface DetectedQr {
  rawValue: string
}

export interface QrDetector {
  detect(source: ImageBitmapSource): Promise<DetectedQr[]>
}

// lib.dom has no BarcodeDetector yet; this is the slice of the spec used here.
interface NativeBarcodeDetectorCtor {
  new (options?: { formats?: string[] }): QrDetector
  getSupportedFormats?: () => Promise<string[]>
}

async function nativeQrDetector(): Promise<QrDetector | null> {
  const ctor = (globalThis as { BarcodeDetector?: NativeBarcodeDetectorCtor }).BarcodeDetector
  if (typeof ctor !== 'function') return null
  try {
    const formats = ctor.getSupportedFormats ? await ctor.getSupportedFormats() : ['qr_code']
    if (!formats.includes('qr_code')) return null
    return new ctor({ formats: ['qr_code'] })
  } catch {
    return null
  }
}

let ponyfillReady: Promise<QrDetector> | null = null

function ponyfillQrDetector(): Promise<QrDetector> {
  ponyfillReady ??= (async () => {
    const [{ BarcodeDetector, prepareZXingModule }, { default: wasmUrl }] = await Promise.all([
      import('barcode-detector/ponyfill'),
      // Vite copies the binary into the build and hands back its hashed URL.
      import('zxing-wasm/reader/zxing_reader.wasm?url'),
    ])
    prepareZXingModule({
      overrides: {
        locateFile: (path: string, prefix: string) =>
          path.endsWith('.wasm') ? wasmUrl : prefix + path,
      },
    })
    return new BarcodeDetector({ formats: ['qr_code'] })
  })()
  return ponyfillReady
}

/** Native where it reads QR codes, the ponyfill everywhere else. */
export async function createQrDetector(): Promise<QrDetector> {
  return (await nativeQrDetector()) ?? ponyfillQrDetector()
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
