import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'

import { renderWithProviders, t } from '@/test/utils'
import { ReceiptPastePanel } from './receipt-paste-panel'

const api = vi.hoisted(() => ({ receipts: { submitHtml: vi.fn() } }))
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock('@/lib/api', () => api)
vi.mock('sonner', () => ({ toast }))

const QR_URL = 'http://app.sefaz.es.gov.br/ConsultaNFCe?p=32260800063960006050650050003784571128411294|2|1|1|abc'
const PAGE = 'NFC-e\nChave de acesso\n3226 0800 0639 6000 6050 6500 5000 3784 5711 2841 1294'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ReceiptPastePanel', () => {
  it('explains the flow and opens the QR link in a new tab', () => {
    renderWithProviders(<ReceiptPastePanel receipt={{ id: 'r1', qr_url: QR_URL, status_reason: 'captcha' }} />)

    expect(screen.getByText(t('receipts.paste.intro'))).toBeInTheDocument()
    const link = screen.getByRole('link', { name: t('receipts.paste.open') })
    expect(link).toHaveAttribute('href', QR_URL)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('says so when the receipt was typed by key and has no link', () => {
    renderWithProviders(<ReceiptPastePanel receipt={{ id: 'r1', qr_url: null, status_reason: 'captcha' }} />)

    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText(t('receipts.paste.noUrl'))).toBeInTheDocument()
  })

  it('withholds a link the portal has already refused', () => {
    renderWithProviders(<ReceiptPastePanel receipt={{ id: 'r1', qr_url: QR_URL, status_reason: 'qr_rejected' }} />)

    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText(t('receipts.paste.qrRefused'))).toBeInTheDocument()
  })

  it('sends what was pasted, verbatim, and hands back the receipt the server returned', async () => {
    const authorized = { id: 'r1', status: 'authorized', items: [] }
    api.receipts.submitHtml.mockResolvedValue(authorized)
    const onDone = vi.fn()
    const { user, queryClient } = renderWithProviders(
      <ReceiptPastePanel receipt={{ id: 'r1', qr_url: QR_URL, status_reason: 'captcha' }} onDone={onDone} />,
    )
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    const submit = screen.getByRole('button', { name: t('receipts.paste.submit') })
    expect(submit).toBeDisabled()

    const textarea = screen.getByRole('textbox', { name: t('receipts.paste.title') })
    await user.click(textarea)
    await user.paste(PAGE)
    expect(submit).toBeEnabled()

    await user.click(submit)

    await waitFor(() => expect(onDone).toHaveBeenCalledWith(authorized))
    expect(api.receipts.submitHtml).toHaveBeenCalledWith('r1', PAGE)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['receipts'] })
    expect(toast.success).toHaveBeenCalledWith(t('receipts.paste.success'))
    expect(textarea).toHaveValue('')
  })

  it('tells the person what kind of page they pasted when the server refuses it', async () => {
    api.receipts.submitHtml.mockRejectedValue({
      response: { status: 422, data: { detail: { code: 'page_captcha' } } },
    })
    const { user } = renderWithProviders(<ReceiptPastePanel receipt={{ id: 'r1', qr_url: QR_URL, status_reason: 'captcha' }} />)

    await user.click(screen.getByRole('textbox', { name: t('receipts.paste.title') }))
    await user.paste('<html>turnstile</html>')
    await user.click(screen.getByRole('button', { name: t('receipts.paste.submit') }))

    expect(await screen.findByRole('alert')).toHaveTextContent(t('receipts.errors.page_captcha'))
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('falls back to a generic line for a failure it cannot name', async () => {
    api.receipts.submitHtml.mockRejectedValue(new Error('Network Error'))
    const { user } = renderWithProviders(<ReceiptPastePanel receipt={{ id: 'r1', qr_url: QR_URL, status_reason: 'captcha' }} />)

    await user.click(screen.getByRole('textbox', { name: t('receipts.paste.title') }))
    await user.paste('whatever')
    await user.click(screen.getByRole('button', { name: t('receipts.paste.submit') }))

    expect(await screen.findByRole('alert')).toHaveTextContent(t('receipts.errors.generic'))
  })

  it('reports a cancelled note as read, not as a failure', async () => {
    api.receipts.submitHtml.mockResolvedValue({ id: 'r1', status: 'cancelled', items: [] })
    const { user } = renderWithProviders(<ReceiptPastePanel receipt={{ id: 'r1', qr_url: QR_URL, status_reason: 'captcha' }} />)

    await user.click(screen.getByRole('textbox', { name: t('receipts.paste.title') }))
    await user.paste(PAGE)
    await user.click(screen.getByRole('button', { name: t('receipts.paste.submit') }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith(t('receipts.paste.cancelled')))
  })
})
