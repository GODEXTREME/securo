/**
 * How a product and its prices read on screen.
 *
 * Pure and separate because the same two questions come up on the product
 * page, in the barcode scanner's answer and next to a receipt line: what
 * size is this, and what does the price mean once size is taken out of it.
 */
import { formatCurrency } from '@/lib/format'
import type { PricePoint, Product } from '@/types'

const CURRENCY = 'BRL'

/** `1,5 L`, `6 × 350 ml`, `450 g` — or null when the size is unknown. */
export function describeSize(product: Pick<Product, 'size_value' | 'size_unit' | 'pack_count'>): string | null {
  const value = product.size_value === null ? null : Number(product.size_value)
  if (value === null || Number.isNaN(value)) {
    return product.pack_count ? `${product.pack_count} ×` : null
  }
  const amount = Number.isInteger(value) ? String(value) : String(value).replace(/\.?0+$/, '')
  const size = `${amount.replace('.', ',')}${product.size_unit ? ` ${product.size_unit}` : ''}`
  return product.pack_count && product.pack_count > 1 ? `${product.pack_count} × ${size}` : size
}

/**
 * The comparable price: `R$ 12,90/kg`. Null normalisation means the line
 * could not be reduced to a base unit — a weighed item priced per piece,
 * a size the parser did not recognise — and saying nothing is better than
 * implying a comparison that was never made.
 */
export function priceLabel(
  point: Pick<PricePoint, 'normalized_price' | 'base_unit'>,
  locale: string,
  t: (key: string) => string,
): string {
  if (point.normalized_price === null || point.base_unit === null) return t('products.notComparable')
  const price = formatCurrency(Number(point.normalized_price), CURRENCY, locale)
  return `${price}/${point.base_unit}`
}
