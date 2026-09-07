import { describe, expect, it } from 'vitest'
import { describeSize, priceLabel } from './product-format'

const t = (key: string) => key

function product(size_value: string | null, size_unit: string | null, pack_count: number | null) {
  return { size_value, size_unit, pack_count }
}

describe('describeSize', () => {
  it('drops the trailing zeros the database keeps', () => {
    expect(describeSize(product('1.5000', 'l', null))).toBe('1,5 l')
    expect(describeSize(product('450.0000', 'g', null))).toBe('450 g')
  })

  it('writes a pack as a multiplication', () => {
    expect(describeSize(product('350.0000', 'ml', 6))).toBe('6 × 350 ml')
  })

  it('keeps a pack of one as a plain size', () => {
    expect(describeSize(product('2.0000', 'kg', 1))).toBe('2 kg')
  })

  it('says nothing it does not know', () => {
    expect(describeSize(product(null, null, null))).toBeNull()
    expect(describeSize(product(null, null, 12))).toBe('12 ×')
  })
})

describe('priceLabel', () => {
  it('reads as a price per base unit', () => {
    expect(priceLabel({ normalized_price: '12.9000', base_unit: 'kg' }, 'pt-BR', t)).toContain('/kg')
  })

  it('refuses to imply a comparison that was not made', () => {
    expect(priceLabel({ normalized_price: null, base_unit: 'kg' }, 'pt-BR', t)).toBe('products.notComparable')
    expect(priceLabel({ normalized_price: '1.0000', base_unit: null }, 'pt-BR', t)).toBe('products.notComparable')
  })
})
