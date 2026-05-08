import { forwardRef } from 'react'

interface Category {
  id: string
  name: string
  group_id?: string | null
}

interface CategoryGroup {
  id: string
  name: string
  categories?: Category[]
}

interface CategoryGroupedSelectProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'children'> {
  categories: Category[]
  categoryGroups?: CategoryGroup[]
  placeholder?: string
}

export const CategoryGroupedSelect = forwardRef<
  HTMLSelectElement,
  CategoryGroupedSelectProps
>(({ categories, categoryGroups, placeholder, ...props }, ref) => {
  // Build a map of grouped and ungrouped categories
  const groupedCategoryIds = new Set(
    categoryGroups?.flatMap((g) => g.categories?.map((c) => c.id) ?? []) ?? []
  )

  const ungroupedCategories = categories.filter(
    (c) => !c.group_id && !groupedCategoryIds.has(c.id)
  )

  const hasUngrouped = ungroupedCategories.length > 0

  return (
    <select ref={ref} {...props}>
      {placeholder && <option value="">{placeholder}</option>}

      {/* Render category groups */}
      {categoryGroups?.map((group) => (
        <optgroup key={group.id} label={group.name}>
          {group.categories?.map((cat) => (
            <option key={cat.id} value={cat.id}>
              {cat.name}
            </option>
          ))}
        </optgroup>
      ))}

      {/* Render ungrouped categories */}
      {hasUngrouped && (
        <optgroup label="Sem Grupo">
          {ungroupedCategories.map((cat) => (
            <option key={cat.id} value={cat.id}>
              {cat.name}
            </option>
          ))}
        </optgroup>
      )}
    </select>
  )
})

CategoryGroupedSelect.displayName = 'CategoryGroupedSelect'
