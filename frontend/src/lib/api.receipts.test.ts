/**
 * The receipts client, checked against the routes in
 * backend/app/api/receipts.py: paths, verbs, and the shape of each body.
 * axios is replaced at the module boundary so nothing leaves the process.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    create: () => ({
      ...http,
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    }),
    isAxiosError: () => false,
  },
}))

import { receipts } from '@/lib/api'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('receipts api', () => {
  it('scans whatever was read or typed', async () => {
    const body = { receipt: { id: 'r1', status: 'pending' }, created: true, already_linked: false }
    http.post.mockResolvedValue({ data: body })

    const result = await receipts.scan('https://app.sefaz.es.gov.br/ConsultaNFCe?p=…')

    expect(http.post).toHaveBeenCalledWith('/receipts/scan', {
      payload: 'https://app.sefaz.es.gov.br/ConsultaNFCe?p=…',
    })
    expect(result).toEqual(body)
  })

  it('lists with the filters as query parameters, and with none by default', async () => {
    http.get.mockResolvedValue({ data: [] })

    await receipts.list()
    expect(http.get).toHaveBeenLastCalledWith('/receipts', { params: {} })

    await receipts.list({ pending: true, limit: 200 })
    expect(http.get).toHaveBeenLastCalledWith('/receipts', { params: { pending: true, limit: 200 } })
  })

  it('reads one receipt with its items', async () => {
    http.get.mockResolvedValue({ data: { id: 'r1', items: [] } })
    expect(await receipts.get('r1')).toEqual({ id: 'r1', items: [] })
    expect(http.get).toHaveBeenCalledWith('/receipts/r1')
  })

  it('retries with an empty POST', async () => {
    http.post.mockResolvedValue({ data: { id: 'r1', status: 'pending' } })
    expect(await receipts.retry('r1')).toEqual({ id: 'r1', status: 'pending' })
    expect(http.post).toHaveBeenCalledWith('/receipts/r1/retry')
  })

  it('sends the pasted page as-is under `html`', async () => {
    http.post.mockResolvedValue({ data: { id: 'r1', status: 'authorized' } })
    const pasted = 'NFC-e\nChave de acesso 3226 0800 …'
    expect(await receipts.submitHtml('r1', pasted)).toEqual({ id: 'r1', status: 'authorized' })
    expect(http.post).toHaveBeenCalledWith('/receipts/r1/html', { html: pasted })
  })

  it('patches the link, passing exactly the fields given', async () => {
    http.patch.mockResolvedValue({ data: { id: 'r1' } })
    await receipts.update('r1', { not_my_purchase: true })
    expect(http.patch).toHaveBeenCalledWith('/receipts/r1', { not_my_purchase: true })

    await receipts.update('r1', { clear_transaction: true })
    expect(http.patch).toHaveBeenLastCalledWith('/receipts/r1', { clear_transaction: true })
  })

  it('corrects an item price by ordinal, and null restores the printed one', async () => {
    http.patch.mockResolvedValue({ data: { ordinal: 3, effective_unit_price: '4.79' } })
    await receipts.updateItem('r1', 3, '4.79')
    expect(http.patch).toHaveBeenCalledWith('/receipts/r1/items/3', { unit_price_corrected: '4.79' })

    await receipts.updateItem('r1', 3, null)
    expect(http.patch).toHaveBeenLastCalledWith('/receipts/r1/items/3', { unit_price_corrected: null })
  })

  it('unlinks with DELETE and resolves to nothing', async () => {
    http.delete.mockResolvedValue({ status: 204 })
    await expect(receipts.remove('r1')).resolves.toBeUndefined()
    expect(http.delete).toHaveBeenCalledWith('/receipts/r1')
  })

  it('unwraps the supported states', async () => {
    http.get.mockResolvedValue({ data: { ufs: ['ES'] } })
    expect(await receipts.supportedUfs()).toEqual(['ES'])
    expect(http.get).toHaveBeenCalledWith('/receipts/supported-ufs')
  })

  it('lets a coded 422 through untouched, for the status helpers to read', async () => {
    const failure = { response: { status: 422, data: { detail: { code: 'check_digit' } } } }
    http.post.mockRejectedValue(failure)
    await expect(receipts.scan('3226…')).rejects.toBe(failure)
  })
})
