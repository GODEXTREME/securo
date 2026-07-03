import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { notifications as notificationsApi, type Notification } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Bell, Check, Trash2, AlertTriangle, AlertOctagon, Info } from 'lucide-react'

const SEVERITY_ICON = {
  info: { icon: Info, cls: 'text-sky-600 bg-sky-100' },
  warning: { icon: AlertTriangle, cls: 'text-amber-600 bg-amber-100' },
  critical: { icon: AlertOctagon, cls: 'text-rose-600 bg-rose-100' },
} as const

export default function NotificationsPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  // Recompute alerts when the page opens.
  useEffect(() => {
    notificationsApi.refresh().then(() => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
      queryClient.invalidateQueries({ queryKey: ['notifications', 'unread'] })
    }).catch(() => {})
  }, [queryClient])

  const { data, isLoading } = useQuery({
    queryKey: ['notifications', 'list'],
    queryFn: () => notificationsApi.list(),
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['notifications'] })
  }

  const markRead = useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onSuccess: invalidate,
  })
  const markAll = useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: string) => notificationsApi.remove(id),
    onSuccess: invalidate,
  })

  const items = data?.items ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        section={t('nav.notifications')}
        title={t('notifications.title')}
        action={
          (data?.unread ?? 0) > 0 ? (
            <Button variant="outline" className="gap-1.5" onClick={() => markAll.mutate()}>
              <Check size={16} /> {t('notifications.markAllRead')}
            </Button>
          ) : undefined
        }
      />

      {isLoading ? (
        <div className="space-y-3">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}</div>
      ) : items.length === 0 ? (
        <div className="bg-card rounded-xl border border-dashed border-border p-10 text-center">
          <Bell size={28} className="mx-auto mb-2 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">{t('notifications.empty')}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((n) => <Row key={n.id} n={n} onRead={() => markRead.mutate(n.id)} onRemove={() => remove.mutate(n.id)} />)}
        </div>
      )}
    </div>
  )
}

function Row({ n, onRead, onRemove }: { n: Notification; onRead: () => void; onRemove: () => void }) {
  const { t } = useTranslation()
  const cfg = SEVERITY_ICON[n.severity] ?? SEVERITY_ICON.info
  const Icon = cfg.icon
  const body = (
    <div className={`group flex items-start gap-3 px-4 py-3 rounded-xl border transition-colors ${n.is_read ? 'bg-card border-border' : 'bg-primary/5 border-primary/20'}`}>
      <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${cfg.cls}`}>
        <Icon size={15} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">{n.title}</p>
        {n.body && <p className="text-xs text-muted-foreground mt-0.5">{n.body}</p>}
        <p className="text-[10px] text-muted-foreground mt-1">{new Date(n.created_at).toLocaleString()}</p>
      </div>
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {!n.is_read && (
          <button className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted" title={t('notifications.markRead')} onClick={(e) => { e.preventDefault(); onRead() }}>
            <Check size={14} />
          </button>
        )}
        <button className="p-1.5 rounded-md text-muted-foreground hover:text-rose-500 hover:bg-rose-50" title={t('common.delete')} onClick={(e) => { e.preventDefault(); onRemove() }}>
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  )
  return n.link ? <Link to={n.link} onClick={onRead}>{body}</Link> : body
}
