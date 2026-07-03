import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { installments as installmentsApi, categories as categoriesApi, categoryGroups as categoryGroupsApi, type InstallmentPlan } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { CategoryGroupedSelect } from '@/components/category-grouped-select'
import { Skeleton } from '@/components/ui/skeleton'
import type { CategoryGroup } from '@/types'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { formatCurrency } from '@/lib/format'
import { Layers, AlertCircle } from 'lucide-react'

export default function InstallmentsPage() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const queryClient = useQueryClient()
  const [onlyUncategorized, setOnlyUncategorized] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['installments', onlyUncategorized],
    queryFn: () => installmentsApi.list(onlyUncategorized),
  })
  const { data: categories } = useQuery({
    queryKey: ['categories'],
    queryFn: categoriesApi.list,
  })
  const { data: categoryGroups } = useQuery({
    queryKey: ['category-groups'],
    queryFn: categoryGroupsApi.list,
  })

  const categorize = useMutation({
    mutationFn: ({ ids, categoryId }: { ids: string[]; categoryId: string }) =>
      installmentsApi.categorize(ids, categoryId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['installments'] })
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
      toast.success(t('installments.categorized'))
    },
    onError: () => toast.error(t('common.error')),
  })

  const plans = data?.plans ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        section={t('nav.installments')}
        title={t('installments.title')}
        action={
          <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer">
            <input
              type="checkbox"
              checked={onlyUncategorized}
              onChange={(e) => setOnlyUncategorized(e.target.checked)}
              className="rounded border-border"
            />
            {t('installments.onlyUncategorized')}
          </label>
        }
      />

      {data && (
        <div className="flex gap-4 text-sm">
          <div className="bg-card rounded-xl border border-border px-4 py-3">
            <p className="text-xs text-muted-foreground">{t('installments.plans')}</p>
            <p className="text-lg font-semibold tabular-nums">{data.count}</p>
          </div>
          <div className="bg-card rounded-xl border border-border px-4 py-3">
            <p className="text-xs text-muted-foreground">{t('installments.needsCategory')}</p>
            <p className="text-lg font-semibold tabular-nums text-amber-600">{data.uncategorized_count}</p>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-3">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}</div>
      ) : plans.length === 0 ? (
        <div className="bg-card rounded-xl border border-dashed border-border p-10 text-center">
          <Layers size={28} className="mx-auto mb-2 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">{t('installments.empty')}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {plans.map((plan) => (
            <PlanCard
              key={plan.key}
              plan={plan}
              locale={locale}
              categories={categories ?? []}
              categoryGroups={categoryGroups ?? []}
              onCategorize={(categoryId) => categorize.mutate({ ids: plan.transaction_ids, categoryId })}
              pending={categorize.isPending}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function PlanCard({
  plan, locale, categories, categoryGroups, onCategorize, pending,
}: {
  plan: InstallmentPlan
  locale: string
  categories: { id: string; name: string; color?: string | null; group_id?: string | null }[]
  categoryGroups: CategoryGroup[]
  onCategorize: (categoryId: string) => void
  pending: boolean
}) {
  const { t } = useTranslation()
  return (
    <div className="bg-card rounded-xl border border-border shadow-sm p-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium text-foreground truncate">{plan.name}</p>
            {plan.uncategorized && (
              <span className="inline-flex items-center gap-1 text-[10px] font-medium text-amber-700 bg-amber-100 rounded-full px-1.5 py-0.5">
                <AlertCircle size={11} /> {plan.mixed_categories ? t('installments.mixed') : t('installments.uncategorized')}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            {plan.account_name} · {t('installments.paidOf', { paid: plan.paid_count, total: plan.total_installments })} · {plan.purchase_date}
          </p>
        </div>
        <div className="text-right">
          <p className="text-sm font-semibold tabular-nums">{formatCurrency(plan.total_amount, plan.currency, locale)}</p>
          <p className="text-[11px] text-muted-foreground tabular-nums">
            {plan.total_installments}× {formatCurrency(plan.per_installment, plan.currency, locale)}
          </p>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <span className="text-xs text-muted-foreground">{t('installments.setCategoryForAll')}:</span>
        <CategoryGroupedSelect
          className="text-sm border border-border rounded-lg px-2 py-1 bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
          value={plan.category_id ?? ''}
          disabled={pending}
          onChange={(e) => e.target.value && onCategorize(e.target.value)}
          categories={categories}
          categoryGroups={categoryGroups}
          placeholder={plan.category_name ?? t('installments.choose')}
        />
      </div>
    </div>
  )
}
