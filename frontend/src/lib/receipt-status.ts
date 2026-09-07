/**
 * What a receipt's state means to a person, and which i18n key says it.
 *
 * Pure: the pages and the paste panel read these so that "is this one still
 * being fetched", "may it be retried", "does it want the page pasted" and
 * "what does error code X mean" are decided in one place and tested once.
 * Mirrors the constants in backend/app/services/receipt_service.py.
 */
import type { Receipt, ReceiptStatus, ReceiptStatusReason } from '@/types'

/** What the "waiting on the state" block lists. */
export const PENDING_STATUSES: readonly ReceiptStatus[] = [
  'pending',
  'fetching',
  'waiting_sefaz',
  'parse_error',
  'gave_up',
]

/** Statuses `POST /retry` accepts. */
export const RETRYABLE_STATUSES: readonly ReceiptStatus[] = [
  'waiting_sefaz',
  'gave_up',
  'parse_error',
  'invalid',
]

export function isPending(status: ReceiptStatus): boolean {
  return PENDING_STATUSES.includes(status)
}

/** True while the worker may still change this receipt on its own, which
 *  is when a screen should keep polling. */
export function hasPending(receipts: readonly Pick<Receipt, 'status'>[] | undefined): boolean {
  return (receipts ?? []).some((r) => isPending(r.status))
}

export function canRetry(receipt: Pick<Receipt, 'status'>): boolean {
  return RETRYABLE_STATUSES.includes(receipt.status)
}

/**
 * Whether the paste panel belongs on screen. For Espírito Santo this is the
 * normal path, not a fallback: the portal answers a machine with a Turnstile
 * challenge, the receipt lands in `waiting_sefaz`/`captcha`, and the person
 * opens the page in a browser and pastes it here. Also offered when the
 * automatic route has given up or read the page wrong, since a browser copy
 * is a second chance either way.
 */
export function wantsPaste(receipt: Pick<Receipt, 'status' | 'status_reason'>): boolean {
  if (receipt.status === 'waiting_sefaz') {
    return (
      receipt.status_reason === 'captcha' ||
      receipt.status_reason === 'qr_rejected' ||
      receipt.status_reason === 'needs_browser'
    )
  }
  return receipt.status === 'gave_up' || receipt.status === 'parse_error'
}

/** The store as a person names it: the sign over the door, else the legal
 *  name, else whatever the caller wants shown before the note is read. */
export function storeName(receipt: Pick<Receipt, 'store'>, fallback: string): string {
  return receipt.store?.trade_name || receipt.store?.legal_name || fallback
}

export const RECEIPT_REASONS: ReadonlySet<ReceiptStatusReason> = new Set<ReceiptStatusReason>([
  'not_published',
  'portal_down',
  'rate_limited',
  'captcha',
  'http_error',
  'timeout',
  'parser_failed',
  'key_mismatch',
  'invalid_dv',
  'unsupported_uf',
  'unsupported_host',
  'not_nfce',
  'homolog',
  'cancelled_by_sefaz',
  'needs_qr',
  'qr_rejected',
  'needs_browser',
])

/**
 * The i18n key for the one line under a receipt that says what is going on.
 * The reason wins when there is one; otherwise the status carries its own
 * sentence (a fresh `pending` has no reason yet, and `gave_up` may keep the
 * last reason but the fact that retries ran out matters more).
 */
export function statusMessageKey(receipt: Pick<Receipt, 'status' | 'status_reason'>): string {
  if (receipt.status === 'gave_up') return 'receipts.statusMessage.gave_up'
  if (receipt.status_reason && RECEIPT_REASONS.has(receipt.status_reason)) {
    return `receipts.reason.${receipt.status_reason}`
  }
  return `receipts.statusMessage.${receipt.status}`
}

/** Codes the backend puts in `{ detail: { code } }` on 409/422. Anything
 *  else falls back to the generic line rather than showing a raw code. */
export const RECEIPT_ERROR_CODES: ReadonlySet<string> = new Set([
  // QR / key parsing (POST /scan)
  'empty',
  'not_digits',
  'length',
  'check_digit',
  'unknown_uf',
  'bad_month',
  'unrecognized',
  'qr_format',
  'qr_fields',
  'qr_version',
  'qr_tpamb',
  // POST /retry
  'not_retryable',
  'still_invalid',
  // POST /html: what kind of page was pasted
  'page_not_found_yet',
  'page_cancelled',
  'page_captcha',
  'page_error_page',
  'key_mismatch',
  'unsupported_uf',
  // POST /html: the parser's own codes
  'layout_changed',
  'no_items',
  'no_totals',
  'no_issuer',
  'no_access_key',
  'no_number_series',
  'item_fields',
  // PATCH
  'transaction_not_found',
])

/** Pull `detail.code` out of an axios error, or null when the failure was
 *  not one the receipts API describes (network, 500, validation list). */
export function apiErrorCode(error: unknown): string | null {
  if (!error || typeof error !== 'object' || !('response' in error)) return null
  const response = (error as { response?: { data?: unknown } }).response
  const data = response?.data
  if (!data || typeof data !== 'object' || !('detail' in data)) return null
  const detail = (data as { detail: unknown }).detail
  if (!detail || typeof detail !== 'object' || !('code' in detail)) return null
  const code = (detail as { code: unknown }).code
  return typeof code === 'string' ? code : null
}

export function errorMessageKey(code: string | null): string {
  return code && RECEIPT_ERROR_CODES.has(code) ? `receipts.errors.${code}` : 'receipts.errors.generic'
}

/** One call for the mutation `onError` handlers. */
export function apiErrorKey(error: unknown): string {
  return errorMessageKey(apiErrorCode(error))
}

/** The 44 digits as printed on the paper: eleven groups of four. */
export function formatAccessKey(key: string): string {
  return key.replace(/(\d{4})(?=\d)/g, '$1 ')
}

/** Digits only, `00.000.000/0000-00` as Brazilians read it. */
export function formatCnpj(cnpj: string): string {
  const d = cnpj.replace(/\D/g, '')
  if (d.length !== 14) return cnpj
  return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`
}
