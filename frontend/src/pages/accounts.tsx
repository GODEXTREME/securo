import { useEffect, useState } from 'react'
import { getAccountName } from '@/lib/account-utils'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { accounts, currencies } from '@/lib/api'
import { invalidateFinancialQueries } from '@/lib/invalidate-queries'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { DatePickerInput } from '@/components/ui/date-picker-input'
import { Skeleton } from '@/components/ui/skeleton'
import type { Account } from '@/types'
import {
  Building2,
  PiggyBank,
  CreditCard,
  TrendingUp,
  Wallet,
  Pencil,
  Trash2,
  Plus,
  Archive,
} from 'lucide-react'
import { PageHeader } from '@/components/page-header'
import { BankConnectDialog } from '@/components/bank-connect-dialog'
import { ConnectorSelectDialog } from '@/components/connector-select-dialog'
import { usePrivacyMode } from '@/hooks/use-privacy-mode'
import { useAuth } from '@/contexts/auth-context'

function formatCurrency(value: number, currency = 'USD', locale = 'en-US') {
  return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(value)
}

function daysUntil(dateStr: string | null): number | null {
  if (!dateStr) return null
  const due = new Date(dateStr + 'T00:00:00')
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.round((due.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))
}

const ACCOUNT_TYPE_CONFIG: Record<string, { icon: React.ElementType; color: string; bg: string; label: string }> = {
  checking:    { icon: Building2,   color: 'text-indigo-600',    bg: 'bg-indigo-100',    label: 'accounts.typeChecking' },
  savings:     { icon: PiggyBank,   color: 'text-emerald-600', bg: 'bg-emerald-100', label: 'accounts.typeSavings' },
  credit_card: { icon: CreditCard,  color: 'text-violet-600', bg: 'bg-violet-100', label: 'accounts.typeCreditCard' },
  investment:  { icon: TrendingUp,  color: 'text-amber-600',  bg: 'bg-amber-100',  label: 'accounts.typeInvestment' },
  wallet:      { icon: Wallet,      color: 'text-rose-600',   bg: 'bg-rose-100',   label: 'accounts.typeWallet' },
}

function getTypeConfig(type: string) {
  return ACCOUNT_TYPE_CONFIG[type] ?? ACCOUNT_TYPE_CONFIG['checking']
}

export default function AccountsPage() {
  const { t, i18n } = useTranslation()
  const locale = i18n.language === 'en' ? 'en-US' : i18n.language
  const { mask } = usePrivacyMode()
  const { user } = useAuth()
  const userCurrency = user?.preferences?.currency_display ?? 'USD'
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingAccount, setEditingAccount] = useState<Account | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [connectorSelectOpen, setConnectorSelectOpen] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)
  const [closingAccountId, setClosingAccountId] = useState<string | null>(null)

  const { data: accountsList, isLoading: accountsLoading } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => accounts.list(),
  })


  const { data: closedAccountsList } = useQuery({
    queryKey: ['accounts', 'closed'],
    queryFn: () => accounts.list(true),
  })
  const closedAccounts = closedAccountsList?.filter((a) => a.is_closed) ?? []



  const createMutation = useMutation({
    mutationFn: (data: { name: string; type: string; balance?: number; currency?: string }) =>
      accounts.create(data),
    onSuccess: () => {
      invalidateFinancialQueries(queryClient)
      setDialogOpen(false)
      toast.success(t('accounts.created'))
    },
    onError: () => toast.error(t('common.error')),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, ...data }: Partial<Account> & { id: string }) =>
      accounts.update(id, data),
    onSuccess: () => {
      invalidateFinancialQueries(queryClient)
      setDialogOpen(false)
      setEditingAccount(null)
      toast.success(t('accounts.updated'))
    },
    onError: () => toast.error(t('common.error')),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => accounts.delete(id),
    onSuccess: () => {
      invalidateFinancialQueries(queryClient)
      queryClient.invalidateQueries({ queryKey: ['import-logs'] })
      setDeletingId(null)
      toast.success(t('accounts.deleted'))
    },
    onError: () => toast.error(t('common.error')),
  })

  const closeMutation = useMutation({
    mutationFn: (id: string) => accounts.close(id),
    onSuccess: () => {
      invalidateFinancialQueries(queryClient)
      setClosingAccountId(null)
      toast.success(t('accounts.accountClosed'))
    },
    onError: () => toast.error(t('common.error')),
  })

  const reopenMutation = useMutation({
    mutationFn: (id: string) => accounts.reopen(id),
    onSuccess: () => {
      invalidateFinancialQueries(queryClient)
      toast.success(t('accounts.accountReopened'))
    },
    onError: () => toast.error(t('common.error')),
  })

  const isLoading = accountsLoading

  // Separate accounts by type and connection
  const allAccounts = accountsList ?? []
  const bankingAccounts = allAccounts.filter((a) => a.type !== 'credit_card' && !a.is_closed)
  const creditCardAccounts = allAccounts.filter((a) => a.type === 'credit_card' && !a.is_closed)

  // Calculate totals for Banking Accounts
  const bankingTotal = bankingAccounts.reduce((sum, acc) => sum + Number(acc.current_balance), 0)

  // Calculate totals for Credit Cards
  const creditCardSpent = creditCardAccounts.reduce((sum, acc) => sum + Number(acc.current_balance), 0)
  const creditCardLimit = creditCardAccounts.reduce((sum, acc) => sum + (Number(acc.credit_limit) || 0), 0)
  const creditCardAvailable = creditCardLimit - creditCardSpent

  // Component to render an account card
  const AccountCard = ({ acc }: { acc: Account }) => {
    const cfg = getTypeConfig(acc.type)
    const Icon = cfg.icon
    const bal = Number(acc.current_balance)
    const isCC = acc.type === 'credit_card'
    const dueIn = isCC ? daysUntil(acc.next_due_date) : null
    const dueText =
      dueIn == null ? null
        : dueIn < 0 ? t('accounts.overdue')
        : dueIn === 0 ? t('accounts.dueToday')
        : t('accounts.dueIn', { count: dueIn })
    const dueClass = dueIn != null && dueIn <= 3 ? 'text-amber-600' : 'text-muted-foreground'

    return (
      <div className="group flex flex-col px-5 py-3 hover:bg-muted/50 transition-colors border-b border-muted last:border-0">
        {/* First row: Icon + Name */}
        <Link to={`/accounts/${acc.id}`} className="flex items-center gap-3 mb-2">
          <div className={`w-8 h-8 rounded-lg ${cfg.bg} flex items-center justify-center shrink-0`}>
            <Icon size={14} className={cfg.color} />
          </div>
          <p className="text-sm font-medium text-foreground">{getAccountName(acc)}</p>
        </Link>

        {/* Second row: Type + Value */}
        <div className="flex items-center justify-between mb-2 ml-11">
          <p className="text-xs text-muted-foreground">
            {t(cfg.label)}
            {dueText && <> · <span className={dueClass}>{dueText}</span></>}
          </p>
          <p className={`text-xs sm:text-sm font-semibold tabular-nums ${(isCC ? bal > 0 : bal < 0) ? 'text-rose-500' : 'text-foreground'}`}>
            {mask(formatCurrency(bal, acc.currency, locale))}
          </p>
        </div>

        {/* Third row: Additional info (for CC) + Buttons */}
        <div className="flex items-center justify-between ml-11">
          <div className="text-xs text-muted-foreground">
            {isCC && acc.available_credit != null && (
              <p>{t('accounts.availableCredit')}: {mask(formatCurrency(Number(acc.available_credit), acc.currency, locale))}</p>
            )}
          </div>

          {/* Buttons */}
          <div className="flex items-center gap-1 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-opacity">
            <button
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              onClick={() => { setEditingAccount(acc); setDialogOpen(true) }}
              title={t('common.edit')}
            >
              <Pencil size={13} />
            </button>
            <button
              className="p-1.5 rounded-md text-muted-foreground hover:text-amber-600 hover:bg-amber-50 transition-colors"
              onClick={() => setClosingAccountId(acc.id)}
              title={t('accounts.close')}
            >
              <Archive size={13} />
            </button>
            {!acc.connection_id && (
              <button
                className="p-1.5 rounded-md text-muted-foreground hover:text-rose-500 hover:bg-rose-50 transition-colors"
                onClick={() => setDeletingId(acc.id)}
                disabled={deleteMutation.isPending}
                title={t('common.delete')}
              >
                <Trash2 size={13} />
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        section={t('accounts.title')}
        title={t('accounts.title')}
        action={
          <div className="flex gap-2 items-center">
            <Button variant="outline" className="gap-1.5" onClick={() => setConnectorSelectOpen(true)}>
              <Plus size={16} />
              {t('accounts.connectBank')}
            </Button>
            <Button onClick={() => { setEditingAccount(null); setDialogOpen(true) }} className="gap-1.5">
              <Plus size={16} />
              {t('accounts.addManual')}
            </Button>
          </div>
        }
      />

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}
        </div>
      ) : (
        <div className="space-y-6">
          {/* Banking Accounts Section */}
          {bankingAccounts.length > 0 || creditCardAccounts.length > 0 ? (
            <>
              {bankingAccounts.length > 0 && (
                <div className="bg-card rounded-xl border border-border shadow-sm">
                  <div className="flex items-center justify-between px-5 py-3.5 border-b border-border">
                    <div className="flex-1">
                      <h2 className="text-sm font-medium text-muted-foreground">{t('accounts.bankingAccounts')}</h2>
                    </div>
                    <div className="text-right">
                      <p className="text-xs sm:text-sm font-semibold tabular-nums text-foreground">
                        {mask(formatCurrency(bankingTotal, userCurrency, locale))}
                      </p>
                      <p className="text-[10px] text-muted-foreground">{t('accounts.total')}</p>
                    </div>
                  </div>
                  <div className="divide-y divide-muted">
                    {bankingAccounts.map((acc) => (
                      <AccountCard key={acc.id} acc={acc} />
                    ))}
                  </div>
                </div>
              )}

              {creditCardAccounts.length > 0 && (
                <div className="bg-card rounded-xl border border-border shadow-sm">
                  <div className="px-5 py-3.5 border-b border-border">
                    <h2 className="text-sm font-medium text-muted-foreground mb-3">{t('accounts.creditCards')}</h2>
                    <div className="grid grid-cols-3 gap-4">
                      <div>
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{t('accounts.spent')}</p>
                        <p className="text-sm font-semibold tabular-nums text-foreground">
                          {mask(formatCurrency(creditCardSpent, userCurrency, locale))}
                        </p>
                      </div>
                      <div>
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{t('accounts.limit')}</p>
                        <p className="text-sm font-semibold tabular-nums text-foreground">
                          {mask(formatCurrency(creditCardLimit, userCurrency, locale))}
                        </p>
                      </div>
                      <div>
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{t('accounts.available')}</p>
                        <p className={`text-sm font-semibold tabular-nums ${creditCardAvailable < 0 ? 'text-rose-500' : 'text-foreground'}`}>
                          {mask(formatCurrency(creditCardAvailable, userCurrency, locale))}
                        </p>
                      </div>
                    </div>
                  </div>
                  <div className="divide-y divide-muted">
                    {creditCardAccounts.map((acc) => (
                      <AccountCard key={acc.id} acc={acc} />
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="bg-card rounded-xl border border-dashed border-border p-8 text-center">
              <p className="text-sm text-muted-foreground">{t('accounts.noAccountsFound')}</p>
            </div>
          )}

          {/* Closed Accounts */}
          {closedAccounts.length > 0 && (
            <div className="bg-card rounded-xl border border-border shadow-sm opacity-60">
              <div className="flex items-center justify-between px-5 py-3.5 border-b border-border">
                <h2 className="text-sm font-medium text-muted-foreground">{t('accounts.closedAccounts')}</h2>
              </div>
              <div className="divide-y divide-muted">
                {closedAccounts.map((acc) => {
                  const cfg = getTypeConfig(acc.type)
                  const Icon = cfg.icon
                  return (
                    <div key={acc.id} className="flex items-center px-5 py-3">
                      <div className="flex items-center gap-3 flex-1 min-w-0">
                        <div className={`w-8 h-8 rounded-lg ${cfg.bg} flex items-center justify-center shrink-0`}>
                          <Icon size={14} className={cfg.color} />
                        </div>
                        <p className="text-sm font-medium text-muted-foreground truncate">{getAccountName(acc)}</p>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-xs text-muted-foreground hover:text-foreground h-7 px-2 mr-3"
                        onClick={() => reopenMutation.mutate(acc.id)}
                        disabled={reopenMutation.isPending}
                      >
                        {t('accounts.reopen')}
                      </Button>
                      <p className="text-sm font-semibold tabular-nums text-muted-foreground w-32 text-right">
                        {mask(formatCurrency(Number(acc.current_balance), acc.currency, locale))}
                      </p>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Confirm delete dialog */}
      <Dialog open={!!deletingId} onOpenChange={() => setDeletingId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('accounts.confirmDeleteTitle')}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {t('accounts.confirmDeleteDesc')}
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeletingId(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => deletingId && deleteMutation.mutate(deletingId)}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? t('common.loading') : t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>


      {/* Confirm close dialog */}
      <Dialog open={!!closingAccountId} onOpenChange={() => setClosingAccountId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('accounts.close')}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {t('accounts.confirmClose')}
          </p>
          {accountsList?.find(a => a.id === closingAccountId)?.connection_id && (
            <p className="text-sm text-amber-600 font-medium">
              {t('accounts.confirmCloseBank')}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setClosingAccountId(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="default"
              onClick={() => closingAccountId && closeMutation.mutate(closingAccountId)}
              disabled={closeMutation.isPending}
            >
              {closeMutation.isPending ? t('common.loading') : t('accounts.close')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Connector Select Dialog */}
      <ConnectorSelectDialog
        open={connectorSelectOpen}
        onClose={() => setConnectorSelectOpen(false)}
        onSelect={(provider) => setSelectedProvider(provider)}
      />

      {/* Bank Connect Dialog */}
      <BankConnectDialog
        open={!!selectedProvider}
        onClose={() => setSelectedProvider(null)}
        provider={selectedProvider ?? undefined}
      />


      {/* Account Dialog */}
      <AccountDialog
        open={dialogOpen}
        onClose={() => { setDialogOpen(false); setEditingAccount(null) }}
        account={editingAccount}
        onSave={(data) => {
          if (editingAccount) {
            updateMutation.mutate({ id: editingAccount.id, ...data })
          } else {
            createMutation.mutate(data as { name: string; type: string; balance?: number; balance_date?: string; currency?: string })
          }
        }}
        loading={createMutation.isPending || updateMutation.isPending}
      />
    </div>
  )
}

function AccountDialog({
  open,
  onClose,
  account,
  onSave,
  loading,
}: {
  open: boolean
  onClose: () => void
  account: Account | null
  onSave: (data: {
    name?: string
    display_name?: string | null
    type?: string
    balance?: number
    balance_date?: string
    currency?: string
    credit_limit?: number | null
    statement_close_day?: number | null
    payment_due_day?: number | null
  }) => void
  loading: boolean
}) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const userCurrency = user?.preferences?.currency_display ?? 'USD'
  const { data: supportedCurrencies } = useQuery({
    queryKey: ['currencies'],
    queryFn: currencies.list,
    staleTime: Infinity,
  })
  const [name, setName] = useState(account?.name ?? '')
  const [displayName, setDisplayName] = useState(account?.display_name ?? '')
  const [type, setType] = useState(account?.type ?? 'checking')
  const [balance, setBalance] = useState(account?.balance?.toString() ?? '0')
  const [currency, setCurrency] = useState(account?.currency ?? userCurrency)
  const [balanceDate, setBalanceDate] = useState(new Date().toISOString().slice(0, 10))
  const [creditLimit, setCreditLimit] = useState(account?.credit_limit?.toString() ?? '')
  const [statementCloseDay, setStatementCloseDay] = useState(account?.statement_close_day?.toString() ?? '')
  const [paymentDueDay, setPaymentDueDay] = useState(account?.payment_due_day?.toString() ?? '')

  useEffect(() => {
    setName(account?.name ?? '')
    setDisplayName(account?.display_name ?? '')
    setType(account?.type ?? 'checking')
    setBalance(account?.balance?.toString() ?? '0')
    setCurrency(account?.currency ?? userCurrency)
    setBalanceDate(new Date().toISOString().slice(0, 10))
    setCreditLimit(account?.credit_limit?.toString() ?? '')
    setStatementCloseDay(account?.statement_close_day?.toString() ?? '')
    setPaymentDueDay(account?.payment_due_day?.toString() ?? '')
  }, [account])

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {account ? t('accounts.editAccount') : t('accounts.addManual')}
          </DialogTitle>
        </DialogHeader>
        <form
          key={account?.id ?? 'new'}
          onSubmit={(e) => {
            e.preventDefault()
            const isCC = type === 'credit_card'
            const parseDay = (v: string) => {
              const n = parseInt(v, 10)
              return Number.isFinite(n) && n >= 1 && n <= 31 ? n : null
            }
            const isConnected = !!account?.connection_id
            onSave({
              ...(!isConnected && { name, type, balance: parseFloat(balance), balance_date: balanceDate, currency }),
              display_name: displayName.trim() || null,
              ...(isCC && {
                credit_limit: creditLimit !== '' ? parseFloat(creditLimit) : null,
                statement_close_day: parseDay(statementCloseDay),
                payment_due_day: parseDay(paymentDueDay),
              }),
            })
          }}
          className="space-y-4"
        >
          <div className="space-y-2">
            <Label>{t('accounts.accountName')}</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} required disabled={!!account?.connection_id} />
          </div>
          {account?.connection_id && (
            <div className="space-y-2">
              <Label>{t('accounts.displayName')}</Label>
              <Input
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder={name}
              />
              <p className="text-xs text-muted-foreground">{t('accounts.displayNameHint')}</p>
            </div>
          )}
          {!account?.connection_id && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>{t('accounts.accountType')}</Label>
                  <select
                    className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                    value={type}
                    onChange={(e) => setType(e.target.value)}
                  >
                    <option value="checking">{t('accounts.typeChecking')}</option>
                    <option value="savings">{t('accounts.typeSavings')}</option>
                    <option value="credit_card">{t('accounts.typeCreditCard')}</option>
                    <option value="investment">{t('accounts.typeInvestment')}</option>
                    <option value="wallet">{t('accounts.typeWallet')}</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <Label>{t('accounts.currency')}</Label>
                  <select
                    className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                    value={currency}
                    onChange={(e) => setCurrency(e.target.value)}
                  >
                    {(supportedCurrencies ?? [{ code: userCurrency, symbol: userCurrency, name: userCurrency, flag: '' }]).map((c) => (
                      <option key={c.code} value={c.code}>{c.flag} {c.name}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>
                    {type === 'credit_card'
                      ? t('accounts.balanceCreditCard')
                      : t('accounts.balance')}
                  </Label>
                  <Input
                    type="number"
                    step="0.01"
                    min={type === 'credit_card' ? '0' : undefined}
                    value={balance}
                    onChange={(e) => setBalance(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label>{t('accounts.balanceDate')}</Label>
                  <DatePickerInput
                    value={balanceDate}
                    onChange={setBalanceDate}
                    className="w-full justify-start"
                  />
                </div>
              </div>
              {type === 'credit_card' && (
                <p className="text-xs text-muted-foreground -mt-2">
                  {t('accounts.balanceCreditCardHint')}
                </p>
              )}
            </>
          )}
          {type === 'credit_card' && (
            <div className="space-y-4 rounded-lg border border-border bg-muted/30 p-4">
              <div className="space-y-2">
                <Label>{t('accounts.creditLimit')}</Label>
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  value={creditLimit}
                  onChange={(e) => setCreditLimit(e.target.value)}
                  placeholder="0.00"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>{t('accounts.statementCloseDay')}</Label>
                  <Input
                    type="number"
                    min="1"
                    max="31"
                    value={statementCloseDay}
                    onChange={(e) => setStatementCloseDay(e.target.value)}
                    placeholder={t('accounts.dayOfMonthHint')}
                  />
                </div>
                <div className="space-y-2">
                  <Label>{t('accounts.paymentDueDay')}</Label>
                  <Input
                    type="number"
                    min="1"
                    max="31"
                    value={paymentDueDay}
                    onChange={(e) => setPaymentDueDay(e.target.value)}
                    placeholder={t('accounts.dayOfMonthHint')}
                  />
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? t('common.loading') : t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
