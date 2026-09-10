/**
 * How a chart looks in Securo.
 *
 * The pages that draw charts had each grown their own copy of the same axis
 * and tooltip settings, so a chart written later drifted from the ones
 * written earlier. These are those settings, named once: recessive axes with
 * no rules of their own, a tooltip that is the card surface, and reference
 * lines in the muted ink so they read as a guide rather than as data.
 *
 * `CHART` is the design system's own series palette (`--chart-1` … `--chart-5`
 * in `index.css`), which is deliberately the same in light and dark.
 */

/** The series palette, in the order series should take it. */
export const CHART = {
  primary: 'var(--chart-1)',
  second: 'var(--chart-2)',
  positive: 'var(--chart-3)',
  emphasis: 'var(--chart-4)',
  negative: 'var(--chart-5)',
} as const

/** Axis ticks: small, muted, and without an axis or tick rule. */
export const AXIS = {
  tick: { fontSize: 10, fill: 'var(--muted-foreground)' },
  axisLine: false,
  tickLine: false,
} as const

/** The card surface, so a tooltip belongs to the page it floats over. */
export const TOOLTIP_STYLE = {
  background: 'var(--card)',
  color: 'var(--foreground)',
  border: '1px solid var(--border)',
  borderRadius: '0.75rem',
  boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
  fontSize: '12px',
} as const

/** A guide line — an average, a target, a threshold — never a series. */
export const REFERENCE_LINE = {
  stroke: 'var(--muted-foreground)',
  strokeDasharray: '4 4',
  strokeOpacity: 0.5,
} as const
