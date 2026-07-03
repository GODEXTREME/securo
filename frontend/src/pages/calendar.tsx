import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { financeCalendar, type CalendarEvent } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { formatCurrency } from '@/lib/format'
import { ChevronLeft, ChevronRight, Receipt, ArrowDownRight, ArrowUpRight } from 'lucide-react'

const KIND_DOT: Record<string, string> = {
  bill: 'bg-rose-500',
  recurring_expense: 'bg-amber-500',
  recurring_income: 'bg-emerald-500',
}

export default function CalendarPage() {
  const { t, i18n } = useTranslation()
  const locale = useDisplayLocale()
  const now = new Date()
  const [ym, setYm] = useState({ year: now.getFullYear(), month: now.getMonth() + 1 })

  const { data, isLoading } = useQuery({
    queryKey: ['calendar', ym.year, ym.month],
    queryFn: () => financeCalendar.get(ym.year, ym.month),
  })

  const currency = data?.currency ?? 'USD'
  const firstWeekday = new Date(ym.year, ym.month - 1, 1).getDay() // 0=Sun
  const daysInMonth = new Date(ym.year, ym.month, 0).getDate()
  const cells: (number | null)[] = [...Array(firstWeekday).fill(null), ...Array.from({ length: daysInMonth }, (_, i) => i + 1)]
  const weekdays = Array.from({ length: 7 }, (_, i) => new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(new Date(2024, 8, 1 + i)))
  const monthName = new Intl.DateTimeFormat(i18n.language, { month: 'long', year: 'numeric' }).format(new Date(ym.year, ym.month - 1, 1))

  const eventsByDay = new Map<string, CalendarEvent[]>()
  for (const ev of data?.events ?? []) {
    const arr = eventsByDay.get(ev.date) ?? []
    arr.push(ev)
    eventsByDay.set(ev.date, arr)
  }

  const shift = (delta: number) => setYm((p) => {
    let m = p.month + delta, y = p.year
    if (m < 1) { m = 12; y-- } else if (m > 12) { m = 1; y++ }
    return { year: y, month: m }
  })

  const todayStr = new Date().toISOString().slice(0, 10)

  return (
    <div className="space-y-6">
      <PageHeader
        section={t('nav.calendar')}
        title={t('calendar.title')}
        action={
          <div className="flex items-center gap-2">
            <button onClick={() => shift(-1)} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted"><ChevronLeft size={16} /></button>
            <span className="text-sm font-medium capitalize min-w-36 text-center">{monthName}</span>
            <button onClick={() => shift(1)} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted"><ChevronRight size={16} /></button>
          </div>
        }
      />

      {data && (
        <div className="flex gap-3">
          <div className="bg-card rounded-xl border border-border px-4 py-2 flex items-center gap-2">
            <ArrowUpRight size={15} className="text-emerald-600" />
            <span className="text-sm font-semibold tabular-nums text-emerald-600">{formatCurrency(data.month_income, currency, locale)}</span>
          </div>
          <div className="bg-card rounded-xl border border-border px-4 py-2 flex items-center gap-2">
            <ArrowDownRight size={15} className="text-rose-600" />
            <span className="text-sm font-semibold tabular-nums text-rose-600">{formatCurrency(data.month_expense, currency, locale)}</span>
          </div>
        </div>
      )}

      {isLoading ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
          <div className="grid grid-cols-7 border-b border-border">
            {weekdays.map((w) => <div key={w} className="px-2 py-2 text-center text-[11px] font-medium text-muted-foreground uppercase">{w}</div>)}
          </div>
          <div className="grid grid-cols-7">
            {cells.map((day, i) => {
              if (day === null) return <div key={`e${i}`} className="min-h-20 border-b border-r border-border/50 bg-muted/20" />
              const dateStr = `${ym.year}-${String(ym.month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
              const dayData = data?.daily[dateStr]
              const evs = eventsByDay.get(dateStr) ?? []
              const isToday = dateStr === todayStr
              return (
                <div key={dateStr} className={`min-h-20 border-b border-r border-border/50 p-1.5 ${isToday ? 'bg-primary/5' : ''}`}>
                  <div className="flex items-center justify-between">
                    <span className={`text-[11px] tabular-nums ${isToday ? 'font-bold text-primary' : 'text-muted-foreground'}`}>{day}</span>
                    {dayData && dayData.net !== 0 && (
                      <span className={`text-[10px] tabular-nums font-medium ${dayData.net > 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
                        {dayData.net > 0 ? '+' : ''}{Math.round(dayData.net)}
                      </span>
                    )}
                  </div>
                  <div className="mt-1 space-y-0.5">
                    {evs.slice(0, 3).map((ev, j) => (
                      <div key={j} className="flex items-center gap-1" title={`${ev.title}: ${formatCurrency(ev.amount, ev.currency, locale)}`}>
                        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${KIND_DOT[ev.kind] ?? 'bg-slate-400'}`} />
                        <span className="text-[9px] text-muted-foreground truncate">{ev.title || (ev.kind === 'bill' ? t('calendar.bill') : '')}</span>
                      </div>
                    ))}
                    {evs.length > 3 && <span className="text-[9px] text-muted-foreground">+{evs.length - 3}</span>}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-rose-500" /> {t('calendar.legendBill')}</span>
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-amber-500" /> {t('calendar.legendRecurringExpense')}</span>
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-emerald-500" /> {t('calendar.legendRecurringIncome')}</span>
        <span className="flex items-center gap-1.5"><Receipt size={12} /> {t('calendar.legendActuals')}</span>
      </div>
    </div>
  )
}
