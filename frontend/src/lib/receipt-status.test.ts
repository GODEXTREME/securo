import { describe, expect, it } from 'vitest'
import en from '@/locales/en.json'
import {
  PENDING_STATUSES,
  RECEIPT_ERROR_CODES,
  RECEIPT_REASONS,
  apiErrorCode,
  apiErrorKey,
  canRetry,
  errorMessageKey,
  formatAccessKey,
  formatCnpj,
  hasPending,
  isPending,
  statusMessageKey,
  storeName,
  wantsPaste,
} from './receipt-status'
import type { ReceiptStatus, ReceiptStatusReason } from '@/types'

const ALL_STATUSES: ReceiptStatus[] = [
  'invalid', 'pending', 'fetching', 'waiting_sefaz', 'authorized', 'parse_error', 'cancelled', 'gave_up',
]

function lookup(key: string): unknown {
  return key.split('.').reduce<unknown>((node, part) => {
    return node && typeof node === 'object' ? (node as Record<string, unknown>)[part] : undefined
  }, en)
}

function receipt(status: ReceiptStatus, status_reason: ReceiptStatusReason | null = null) {
  return { status, status_reason, uf: 'ES' }
}

function axiosError(detail: unknown) {
  return { response: { status: 422, data: { detail } } }
}

describe('pending and retryable', () => {
  it('lists what the "waiting on the state" block shows', () => {
    // Mirrors PENDING_STATUSES in backend/app/services/receipt_service.py.
    expect([...PENDING_STATUSES]).toEqual(['pending', 'fetching', 'waiting_sefaz', 'parse_error', 'gave_up'])
    expect(isPending('authorized')).toBe(false)
    expect(isPending('waiting_sefaz')).toBe(true)
  })

  it('polls only while something can still move on its own', () => {
    expect(hasPending(undefined)).toBe(false)
    expect(hasPending([receipt('authorized'), receipt('cancelled')])).toBe(false)
    expect(hasPending([receipt('authorized'), receipt('fetching')])).toBe(true)
  })

  it('offers retry for exactly the statuses POST /retry accepts', () => {
    const retryable = ALL_STATUSES.filter((status) => canRetry(receipt(status)))
    expect(retryable.sort()).toEqual(['gave_up', 'invalid', 'parse_error', 'waiting_sefaz'])
  })
})

describe('wantsPaste', () => {
  it('is the normal path once the portal asked for a person', () => {
    expect(wantsPaste(receipt('waiting_sefaz', 'captcha'))).toBe(true)
  })

  it('is offered when the portal refused the QR, since the key still works', () => {
    expect(wantsPaste(receipt('waiting_sefaz', 'qr_rejected'))).toBe(true)
  })

  it('stays out of the way while the worker is still going to retry', () => {
    expect(wantsPaste(receipt('waiting_sefaz', 'not_published'))).toBe(false)
    expect(wantsPaste(receipt('waiting_sefaz', 'rate_limited'))).toBe(false)
    expect(wantsPaste(receipt('pending'))).toBe(false)
    expect(wantsPaste(receipt('fetching'))).toBe(false)
  })

  it('is a second chance when the automatic route failed for good', () => {
    expect(wantsPaste(receipt('gave_up', 'portal_down'))).toBe(true)
    expect(wantsPaste(receipt('parse_error', 'parser_failed'))).toBe(true)
    expect(wantsPaste(receipt('authorized'))).toBe(false)
    expect(wantsPaste(receipt('cancelled', 'cancelled_by_sefaz'))).toBe(false)
  })
})

describe('statusMessageKey', () => {
  it('prefers the reason when there is one', () => {
    expect(statusMessageKey(receipt('waiting_sefaz', 'captcha'))).toBe('receipts.reason.captcha')
    expect(statusMessageKey(receipt('invalid', 'not_nfce'))).toBe('receipts.reason.not_nfce')
  })

  it('falls back to the status when there is no reason yet', () => {
    expect(statusMessageKey(receipt('pending'))).toBe('receipts.statusMessage.pending')
    expect(statusMessageKey(receipt('authorized'))).toBe('receipts.statusMessage.authorized')
  })

  it('says that retries ran out even when the last reason is kept', () => {
    expect(statusMessageKey(receipt('gave_up', 'portal_down'))).toBe('receipts.statusMessage.gave_up')
  })

  it('never points at a reason it does not know', () => {
    const unknown = { status: 'waiting_sefaz', status_reason: 'brand_new', uf: 'ES' } as unknown as ReturnType<typeof receipt>
    expect(statusMessageKey(unknown)).toBe('receipts.statusMessage.waiting_sefaz')
  })

  it('has an English sentence for every reason and every status', () => {
    for (const reason of RECEIPT_REASONS) {
      expect(lookup(`receipts.reason.${reason}`), reason).toBeTypeOf('string')
    }
    for (const status of ALL_STATUSES) {
      expect(lookup(`receipts.statusMessage.${status}`), status).toBeTypeOf('string')
      expect(lookup(`receipts.status.${status}`), status).toBeTypeOf('string')
    }
  })
})

describe('API error codes', () => {
  it('reads detail.code out of an axios error', () => {
    expect(apiErrorCode(axiosError({ code: 'check_digit' }))).toBe('check_digit')
  })

  it('answers null for anything that is not a coded error', () => {
    expect(apiErrorCode(axiosError('Receipt not found'))).toBeNull()
    expect(apiErrorCode(axiosError([{ loc: ['body', 'payload'], msg: 'too long' }]))).toBeNull()
    expect(apiErrorCode(axiosError({ code: 42 }))).toBeNull()
    expect(apiErrorCode(new Error('Network Error'))).toBeNull()
    expect(apiErrorCode(null)).toBeNull()
  })

  it('maps a known code to its message and everything else to the generic one', () => {
    expect(errorMessageKey('page_captcha')).toBe('receipts.errors.page_captcha')
    expect(errorMessageKey('something_new')).toBe('receipts.errors.generic')
    expect(errorMessageKey(null)).toBe('receipts.errors.generic')
    expect(apiErrorKey(axiosError({ code: 'not_retryable' }))).toBe('receipts.errors.not_retryable')
    expect(apiErrorKey(new Error('boom'))).toBe('receipts.errors.generic')
  })

  it('has an English sentence for every code the backend can send', () => {
    // The scan parser, the retry gate, the page classifier, the ES parser
    // and the link PATCH, as listed in backend/app/api/receipts.py and
    // backend/app/receipts/adapters/tabresult.py.
    const expected = [
      'empty', 'not_digits', 'length', 'check_digit', 'unknown_uf', 'bad_month', 'unrecognized',
      'qr_format', 'qr_fields', 'qr_version', 'qr_tpamb',
      'not_retryable', 'still_invalid',
      'page_not_found_yet', 'page_cancelled', 'page_captcha', 'page_error_page', 'key_mismatch', 'unsupported_uf',
      'layout_changed', 'no_items', 'no_totals', 'no_issuer', 'no_access_key', 'no_number_series', 'item_fields',
      'transaction_not_found',
    ]
    for (const code of expected) expect(RECEIPT_ERROR_CODES.has(code), code).toBe(true)
    for (const code of RECEIPT_ERROR_CODES) {
      expect(lookup(`receipts.errors.${code}`), code).toBeTypeOf('string')
    }
    expect(lookup('receipts.errors.generic')).toBeTypeOf('string')
  })
})

describe('display helpers', () => {
  it('names the store the way the sign does', () => {
    const store = {
      id: '1', cnpj: '00063960006050', cnpj_root: '00063960', legal_name: 'ACME COMERCIO LTDA',
      trade_name: 'Acme', street: null, number: null, district: null, city: null, uf: null, zip: null,
    }
    expect(storeName({ store }, 'fallback')).toBe('Acme')
    expect(storeName({ store: { ...store, trade_name: null } }, 'fallback')).toBe('ACME COMERCIO LTDA')
    expect(storeName({ store: null }, 'fallback')).toBe('fallback')
  })

  it('groups the access key in fours, as printed', () => {
    expect(formatAccessKey('32260800063960006050650050003784571128411294')).toBe(
      '3226 0800 0639 6000 6050 6500 5000 3784 5711 2841 1294',
    )
  })

  it('punctuates a CNPJ and leaves anything else alone', () => {
    expect(formatCnpj('00063960006050')).toBe('00.063.960/0060-50')
    expect(formatCnpj('123')).toBe('123')
  })
})
