/**
 * Which reader is picked, and — the part no browser here can show — that
 * the ponyfill is told to fetch its WebAssembly from this build instead of
 * the CDN it defaults to.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const ponyfill = vi.hoisted(() => ({
  prepareZXingModule: vi.fn(),
  BarcodeDetector: vi.fn(function (this: { formats?: string[] }, options?: { formats?: string[] }) {
    this.formats = options?.formats
  }),
}))
vi.mock('barcode-detector/ponyfill', () => ponyfill)
vi.mock('zxing-wasm/reader/zxing_reader.wasm?url', () => ({ default: '/static/zxing_reader-abc123.wasm' }))

type G = typeof globalThis & { BarcodeDetector?: unknown }

async function load() {
  // A fresh module per test: the ponyfill promise is cached at module scope.
  vi.resetModules()
  return import('./qr-scanner')
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  delete (globalThis as G).BarcodeDetector
})

describe('createQrDetector', () => {
  it('uses the native reader when it can read QR codes', async () => {
    const native = vi.fn(function (this: { native: boolean }) {
      this.native = true
    }) as unknown as { getSupportedFormats: () => Promise<string[]> }
    native.getSupportedFormats = vi.fn().mockResolvedValue(['qr_code', 'ean_13'])
    ;(globalThis as G).BarcodeDetector = native

    const { createQrDetector } = await load()
    const detector = await createQrDetector()

    expect(detector).toMatchObject({ native: true })
    expect(native).toHaveBeenCalledWith({ formats: ['qr_code'] })
    expect(ponyfill.prepareZXingModule).not.toHaveBeenCalled()
  })

  it('skips a native reader that does not do QR codes', async () => {
    const native = vi.fn() as unknown as { getSupportedFormats: () => Promise<string[]> }
    native.getSupportedFormats = vi.fn().mockResolvedValue(['ean_13'])
    ;(globalThis as G).BarcodeDetector = native

    const { createQrDetector } = await load()
    await createQrDetector()

    expect(native).not.toHaveBeenCalled()
    expect(ponyfill.BarcodeDetector).toHaveBeenCalledWith({ formats: ['qr_code'] })
  })

  it('points the ponyfill at the bundled wasm, never at a CDN', async () => {
    // Safari: no BarcodeDetector at all.
    const { createQrDetector } = await load()
    await createQrDetector()

    expect(ponyfill.prepareZXingModule).toHaveBeenCalledTimes(1)
    const { overrides } = ponyfill.prepareZXingModule.mock.calls[0][0] as {
      overrides: { locateFile: (path: string, prefix: string) => string }
    }
    expect(overrides.locateFile('zxing_reader.wasm', 'https://fastly.jsdelivr.net/npm/zxing-wasm@3.1.3/dist/reader/')).toBe(
      '/static/zxing_reader-abc123.wasm',
    )
    // Anything that is not the wasm keeps the module's own resolution.
    expect(overrides.locateFile('zxing_reader.worker.js', '/prefix/')).toBe('/prefix/zxing_reader.worker.js')
  })

  it('prepares the ponyfill once for however many detectors are asked for', async () => {
    const { createQrDetector } = await load()
    await Promise.all([createQrDetector(), createQrDetector()])
    expect(ponyfill.prepareZXingModule).toHaveBeenCalledTimes(1)
  })
})

describe('readQr', () => {
  it('returns the first non-empty payload, trimmed, or null', async () => {
    const { readQr } = await load()
    const source = {} as ImageBitmapSource
    expect(await readQr({ detect: async () => [] }, source)).toBeNull()
    expect(await readQr({ detect: async () => [{ rawValue: '   ' }, { rawValue: ' https://x ' }] }, source)).toBe('https://x')
  })
})
