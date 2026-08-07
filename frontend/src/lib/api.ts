import axios from 'axios'
import type { NumberFormat, DateFormat } from '@/lib/format'
import type {
  User,
  AdminUser,
  AdminUserList,
  Passkey,
  PasskeyOptionsResponse,
  AppSetting,
  Category,
  CategoryGroup,
  BankConnection,
  ConnectionSettings,
  Account,
  AccountSummary,
  Collection,
  CreditCardBill,
  Transaction,
  Payee,
  PayeeSummary,
  RecurringTransaction,
  ProjectedTransaction,
  TransactionCalendarResponse,
  Budget,
  BudgetVsActual,
  Rule,
  RuleExportPayload,
  RuleImportResponse,
  ImportLog,
  ImportPreviewTransaction,
  Workspace,
  WorkspaceMember,
  WorkspaceRole,
  Asset,
  AssetGroup,
  AssetTransaction,
  AssetValue,
  AssetReturns,
  MarketSymbolMatch,
  MarketSymbolQuote,
  Attachment,
  Goal,
  GoalSummary,
  DashboardSummary,
  SpendingByCategory,
  MonthlyTrend,
  BalanceHistory,
  PaginatedTransactions,
  ReportResponse,
  Group,
  GroupKind,
  GroupMember,
  GroupSettlement,
  GroupBalances,
  TransactionSplitsInput,
} from '@/types'

const api = axios.create({
  baseURL: '/api',
})

// Storage key for the currently-selected workspace ID. Lives in
// localStorage so reloads + new tabs stay on the same workspace until
// the user picks another one.
export const WORKSPACE_STORAGE_KEY = 'workspace_id'

// Add auth token + active workspace header to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  const workspaceId = localStorage.getItem(WORKSPACE_STORAGE_KEY)
  if (workspaceId) {
    config.headers['X-Workspace-Id'] = workspaceId
  }
  return config
})

// Handle auth errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// Workspaces
export const workspaces = {
  list: async (): Promise<Workspace[]> => {
    const { data } = await api.get('/workspaces')
    return data
  },
  current: async (): Promise<Workspace> => {
    const { data } = await api.get('/workspaces/current')
    return data
  },
  create: async (payload: {
    name: string
    kind?: string
    default_currency?: string
    locale?: string
    icon?: string
    color?: string
    self_membership?: boolean
  }): Promise<Workspace> => {
    const { data } = await api.post('/workspaces', payload)
    return data
  },
  update: async (id: string, payload: Partial<Pick<Workspace, 'name' | 'icon' | 'color' | 'default_currency' | 'locale'>>): Promise<Workspace> => {
    const { data } = await api.patch(`/workspaces/${id}`, payload)
    return data
  },
  listMembers: async (id: string): Promise<WorkspaceMember[]> => {
    const { data } = await api.get(`/workspaces/${id}/members`)
    return data
  },
  invite: async (id: string, payload: { email: string; role?: WorkspaceRole; password?: string }): Promise<WorkspaceMember> => {
    const { data } = await api.post(`/workspaces/${id}/members`, payload)
    return data
  },
  changeRole: async (id: string, memberUserId: string, role: WorkspaceRole): Promise<WorkspaceMember> => {
    const { data } = await api.patch(`/workspaces/${id}/members/${memberUserId}`, { role })
    return data
  },
  removeMember: async (id: string, memberUserId: string): Promise<void> => {
    await api.delete(`/workspaces/${id}/members/${memberUserId}`)
  },
  stats: async (id: string): Promise<{ members: number; accounts: number; transactions: number }> => {
    const { data } = await api.get(`/workspaces/${id}/stats`)
    return data
  },
  archive: async (id: string): Promise<Workspace> => {
    const { data } = await api.post(`/workspaces/${id}/archive`)
    return data
  },
}

// Setup
export const setup = {
  status: async (): Promise<{ has_users: boolean }> => {
    const { data } = await api.get('/setup/status')
    return data
  },
  createAdmin: async (email: string, password: string, currency = 'USD', name = '', language = 'en'): Promise<{ access_token: string }> => {
    const { data } = await api.post('/setup/create-admin', { email, password, currency, name, language })
    return data
  },
}

// Auth
export const auth = {
  login: async (email: string, password: string) => {
    const formData = new URLSearchParams()
    formData.append('username', email)
    formData.append('password', password)
    const { data } = await api.post('/auth/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    return data
  },
  register: async (email: string, password: string, preferences?: Record<string, string>) => {
    const { data } = await api.post('/auth/register', { email, password, preferences })
    return data
  },
  me: async (): Promise<User> => {
    const { data } = await api.get('/users/me')
    return data
  },
  updateMe: async (updates: Partial<User>): Promise<User> => {
    const { data } = await api.patch('/users/me', updates)
    return data
  },
  changePassword: async (password: string): Promise<User> => {
    const { data } = await api.patch('/users/me', { password })
    return data
  },
  setup2fa: async (): Promise<{ secret: string; otpauth_uri: string }> => {
    const { data } = await api.post('/auth/2fa/setup')
    return data
  },
  enable2fa: async (code: string): Promise<void> => {
    await api.post('/auth/2fa/enable', { code })
  },
  disable2fa: async (password: string, code: string): Promise<void> => {
    await api.post('/auth/2fa/disable', { password, code })
  },
  verify2fa: async (tempToken: string, code: string): Promise<{ access_token: string; token_type: string }> => {
    const { data } = await api.post('/auth/2fa/verify', { temp_token: tempToken, code })
    return data
  },
  listPasskeys: async (): Promise<Passkey[]> => {
    const { data } = await api.get('/auth/passkeys')
    return data
  },
  registerPasskeyOptions: async (name: string): Promise<PasskeyOptionsResponse> => {
    const { data } = await api.post('/auth/passkeys/register/options', { name })
    return data
  },
  verifyPasskeyRegistration: async (
    challengeId: string,
    name: string,
    credential: Record<string, unknown>,
  ): Promise<Passkey> => {
    const { data } = await api.post('/auth/passkeys/register/verify', {
      challenge_id: challengeId,
      name,
      credential,
    })
    return data
  },
  deletePasskey: async (id: string): Promise<void> => {
    await api.delete(`/auth/passkeys/${id}`)
  },
  passkeyAuthenticationOptions: async (email?: string): Promise<PasskeyOptionsResponse> => {
    const { data } = await api.post('/auth/passkeys/authenticate/options', { email })
    return data
  },
  verifyPasskeyAuthentication: async (
    challengeId: string,
    credential: Record<string, unknown>,
  ): Promise<{ access_token: string; token_type: string }> => {
    const { data } = await api.post('/auth/passkeys/authenticate/verify', {
      challenge_id: challengeId,
      credential,
    })
    return data
  },
  passkeySecondFactorOptions: async (tempToken: string): Promise<PasskeyOptionsResponse> => {
    const { data } = await api.post('/auth/passkeys/2fa/options', { temp_token: tempToken })
    return data
  },
  verifyPasskeySecondFactor: async (
    tempToken: string,
    challengeId: string,
    credential: Record<string, unknown>,
  ): Promise<{ access_token: string; token_type: string }> => {
    const { data } = await api.post('/auth/passkeys/2fa/verify', {
      temp_token: tempToken,
      challenge_id: challengeId,
      credential,
    })
    return data
  },
  oidcConfig: async (): Promise<{ enabled: boolean; provider_name: string }> => {
    const { data } = await api.get('/auth/oidc/config')
    return data
  },
}

// Categories
export const categories = {
  list: async (): Promise<Category[]> => {
    const { data } = await api.get('/categories')
    return data
  },
  create: async (category: Partial<Category>): Promise<Category> => {
    const { data } = await api.post('/categories', category)
    return data
  },
  update: async (id: string, category: Partial<Category>): Promise<Category> => {
    const { data } = await api.patch(`/categories/${id}`, category)
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/categories/${id}`)
  },
}

// Category Groups
export const categoryGroups = {
  list: async (): Promise<CategoryGroup[]> => {
    const { data } = await api.get('/category-groups')
    return data
  },
  create: async (group: Partial<CategoryGroup>): Promise<CategoryGroup> => {
    const { data } = await api.post('/category-groups', group)
    return data
  },
  update: async (id: string, group: Partial<CategoryGroup>): Promise<CategoryGroup> => {
    const { data } = await api.patch(`/category-groups/${id}`, group)
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/category-groups/${id}`)
  },
}

// Bank Connections
export const connections = {
  list: async (): Promise<BankConnection[]> => {
    const { data } = await api.get('/connections')
    return data
  },
  getProviders: async (): Promise<{ name: string; display_name: string; description: string; flow_type: string; configured: boolean; requires_institution_select?: boolean; supports_asset_sync?: boolean }[]> => {
    const { data } = await api.get('/connections/providers')
    return data.providers
  },
  getConnectToken: async (provider = 'pluggy'): Promise<string> => {
    const { data } = await api.post('/connections/connect-token', { provider })
    return data.access_token
  },
  getOAuthUrl: async (provider: string, flow_params?: Record<string, unknown>): Promise<string> => {
    const { data } = await api.post('/connections/oauth/url', { provider, flow_params })
    return data.url
  },
  listInstitutions: async (
    provider: string,
    country?: string,
  ): Promise<{
    countries: string[]
    institutions: {
      name: string
      display_name: string
      country: string
      logo?: string | null
      bic?: string | null
      psu_types: string[]
      max_consent_days?: number | null
      max_history_days?: number | null
    }[]
  }> => {
    const { data } = await api.get(`/connections/${provider}/institutions`, {
      params: country ? { country } : undefined,
    })
    return data
  },
  handleCallback: async (
    code: string,
    provider: string,
    state?: string,
    settings?: Pick<ConnectionSettings, 'sync_assets'>,
    reconnectConnectionId?: string,
  ): Promise<BankConnection> => {
    const { data } = await api.post('/connections/oauth/callback', {
      code,
      provider,
      state,
      reconnect_connection_id: reconnectConnectionId,
      ...settings,
    })
    return data
  },
  getReauthUrl: async (connectionId: string): Promise<string> => {
    const { data } = await api.post(`/connections/${connectionId}/oauth/reauth-url`)
    return data.url
  },
  sync: async (id: string): Promise<BankConnection> => {
    const { data } = await api.post(`/connections/${id}/sync`)
    return data
  },
  getReconnectToken: async (connectionId: string): Promise<string> => {
    const { data } = await api.post(`/connections/${connectionId}/reconnect-token`)
    return data.access_token
  },
  updateSettings: async (
    id: string,
    settings: Partial<ConnectionSettings> & { display_name?: string | null },
  ): Promise<BankConnection> => {
    const { data } = await api.patch(`/connections/${id}/settings`, settings)
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/connections/${id}`)
  },
}

// Accounts
export const accounts = {
  list: async (includeClosed = false): Promise<Account[]> => {
    const { data } = await api.get('/accounts', { params: { include_closed: includeClosed } })
    return data
  },
  get: async (id: string): Promise<Account> => {
    const { data } = await api.get(`/accounts/${id}`)
    return data
  },
  create: async (account: {
    name: string
    type: string
    balance?: number
    balance_date?: string
    currency?: string
    credit_limit?: number | null
    statement_close_day?: number | null
    payment_due_day?: number | null
  }): Promise<Account> => {
    const { data } = await api.post('/accounts', account)
    return data
  },
  update: async (id: string, account: Partial<Account>): Promise<Account> => {
    const { data } = await api.patch(`/accounts/${id}`, account)
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/accounts/${id}`)
  },
  summary: async (id: string, from?: string, to?: string, billId?: string, unbilledOnly?: boolean): Promise<AccountSummary> => {
    const { data } = await api.get(`/accounts/${id}/summary`, { params: { from, to, bill_id: billId, unbilled_only: unbilledOnly || undefined } })
    return data
  },
  balanceHistory: async (id: string, from?: string, to?: string): Promise<{ date: string; balance: number; balance_primary?: number }[]> => {
    const { data } = await api.get(`/accounts/${id}/balance-history`, { params: { from, to } })
    return data
  },
  bills: async (id: string, limit = 24): Promise<CreditCardBill[]> => {
    const { data } = await api.get(`/accounts/${id}/bills`, { params: { limit } })
    return data
  },
  close: async (id: string): Promise<Account> => {
    const { data } = await api.post(`/accounts/${id}/close`)
    return data
  },
  reopen: async (id: string): Promise<Account> => {
    const { data } = await api.post(`/accounts/${id}/reopen`)
    return data
  },
}

// Transactions
export const transactions = {
  list: async (params?: {
    account_id?: string
    account_ids?: string[]
    category_id?: string
    category_ids?: string[]
    payee_id?: string
    uncategorized?: boolean
    type?: string
    status?: string
    from?: string
    to?: string
    bill_id?: string
    group_id?: string
    unbilled_only?: boolean
    q?: string
    page?: number
    limit?: number
    include_opening_balance?: boolean
    exclude_transfers?: boolean
    user_pnl_only?: boolean
    tags?: string[]
    min_amount?: number
    max_amount?: number
    sort_by?: string
    sort_dir?: 'asc' | 'desc'
    date_basis?: 'effective' | 'purchase'
  }): Promise<PaginatedTransactions> => {
    const { data } = await api.get('/transactions', {
      params,
      paramsSerializer: { indexes: null },
    })
    return data
  },
  calendar: async (params?: {
    month?: string
    account_id?: string
    account_ids?: string[]
  }): Promise<TransactionCalendarResponse> => {
    const { data } = await api.get('/transactions/calendar', {
      params,
      paramsSerializer: { indexes: null },
    })
    return data
  },
  get: async (id: string): Promise<Transaction> => {
    const { data } = await api.get(`/transactions/${id}`)
    return data
  },
  create: async (transaction: Partial<Transaction>): Promise<Transaction> => {
    const { data } = await api.post('/transactions', transaction)
    return data
  },
  update: async (
    id: string,
    transaction: Partial<Transaction> & { apply_to_transfer_pair?: boolean },
  ): Promise<Transaction> => {
    const { data } = await api.patch(`/transactions/${id}`, transaction)
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/transactions/${id}`)
  },
  toggleIgnore: async (id: string): Promise<Transaction> => {
    const { data } = await api.patch(`/transactions/${id}/ignore`)
    return data
  },
  unlinkRecurring: async (id: string): Promise<Transaction> => {
    const { data } = await api.patch(`/transactions/${id}/unlink-recurring`)
    return data
  },
  createTransfer: async (transfer: {
    from_account_id: string
    to_account_id: string
    amount: number
    date: string
    description: string
    notes?: string
    fx_rate?: number
  }): Promise<{ debit: Transaction; credit: Transaction; transfer_pair_id: string }> => {
    const { data } = await api.post('/transactions/transfer', transfer)
    return data
  },
  bulkCategorize: async (transactionIds: string[], categoryId: string | null): Promise<{ updated: number }> => {
    const { data } = await api.patch('/transactions/bulk-categorize', {
      transaction_ids: transactionIds,
      category_id: categoryId,
    })
    return data
  },
  bulkAddTags: async (transactionIds: string[], tags: string[]): Promise<{ updated: number }> => {
    const { data } = await api.patch('/transactions/bulk-add-tags', {
      transaction_ids: transactionIds,
      tags,
    })
    return data
  },
  bulkRemoveTags: async (transactionIds: string[], tags: string[]): Promise<{ updated: number }> => {
    const { data } = await api.patch('/transactions/bulk-remove-tags', {
      transaction_ids: transactionIds,
      tags,
    })
    return data
  },
  bulkAddToGroup: async (
    transactionIds: string[],
    groupId: string,
    options?: {
      share_type?: 'equal' | 'percent'
      member_splits?: { group_member_id: string; share_pct?: number }[]
    },
  ): Promise<{ updated: number; skipped: number }> => {
    const { data } = await api.patch('/transactions/bulk-add-to-group', {
      transaction_ids: transactionIds,
      group_id: groupId,
      ...(options?.share_type ? { share_type: options.share_type } : {}),
      ...(options?.member_splits ? { member_splits: options.member_splits } : {}),
    })
    return data
  },
  linkTransfer: async (transactionIds: string[]): Promise<{ debit: Transaction; credit: Transaction; transfer_pair_id: string }> => {
    const { data } = await api.post('/transactions/link-transfer', {
      transaction_ids: transactionIds,
    })
    return data
  },
  createTransferCounterpart: async (
    transactionId: string,
    toAccountId: string,
  ): Promise<{ debit: Transaction; credit: Transaction; transfer_pair_id: string }> => {
    const { data } = await api.post(`/transactions/${transactionId}/create-counterpart`, {
      to_account_id: toAccountId,
    })
    return data
  },
  transferCandidates: async (transactionId: string, params?: { limit?: number; window_days?: number }): Promise<Transaction[]> => {
    const { data } = await api.get(`/transactions/${transactionId}/transfer-candidates`, { params })
    return data
  },
  transferPair: async (transactionId: string): Promise<Transaction | null> => {
    const { data } = await api.get(`/transactions/${transactionId}/transfer-pair`)
    return data
  },
  unlinkTransfer: async (pairId: string): Promise<void> => {
    await api.delete(`/connections/transfers/${pairId}`)
  },
  previewImport: async (file: File, options?: {
    date_format?: string
    flip_amount?: boolean
    inflow_column?: string
    outflow_column?: string
    column_mapping?: Record<string, string>
  }): Promise<{ transactions: ImportPreviewTransaction[]; detected_format: string; csv_columns?: string[]; parse_error?: string | null }> => {
    const formData = new FormData()
    formData.append('file', file)
    if (options?.date_format) formData.append('date_format', options.date_format)
    if (options?.flip_amount) formData.append('flip_amount', 'true')
    if (options?.inflow_column) formData.append('inflow_column', options.inflow_column)
    if (options?.outflow_column) formData.append('outflow_column', options.outflow_column)
    if (options?.column_mapping && Object.keys(options.column_mapping).length > 0) {
      formData.append('column_mapping', JSON.stringify(options.column_mapping))
    }
    const { data } = await api.post('/transactions/import/preview', formData)
    return data
  },
  import: async (
    account_id: string,
    transactions: ImportPreviewTransaction[],
    filename: string,
    detected_format: string,
    options?: { detect_duplicates?: boolean },
  ): Promise<{ imported: number; skipped: number; excluded: number; import_log_id: string }> => {
    const payload: {
      account_id: string
      transactions: ImportPreviewTransaction[]
      filename: string
      detected_format: string
      detect_duplicates?: boolean
    } = { account_id, transactions, filename, detected_format }

    if (typeof options?.detect_duplicates === 'boolean') {
      payload.detect_duplicates = options.detect_duplicates
    }

    const { data } = await api.post('/transactions/import', payload)
    return data
  },
  export: async (params?: {
    account_id?: string
    account_ids?: string[]
    category_id?: string
    category_ids?: string[]
    payee_id?: string
    uncategorized?: boolean
    type?: string
    status?: string
    from?: string
    to?: string
    q?: string
    tags?: string[]
    transaction_ids?: string[]
  }): Promise<void> => {
    const { data } = await api.get('/transactions/export', {
      params,
      responseType: 'blob',
      paramsSerializer: { indexes: null },
    })
    const blob = new Blob([data], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `transactions-${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  },
  attachments: {
    list: async (transactionId: string): Promise<Attachment[]> => {
      const { data } = await api.get(`/transactions/${transactionId}/attachments`)
      return data
    },
    upload: async (transactionId: string, file: File): Promise<Attachment> => {
      const formData = new FormData()
      formData.append('file', file)
      const { data } = await api.post(`/transactions/${transactionId}/attachments`, formData)
      return data
    },
    downloadUrl: async (transactionId: string, attachmentId: string): Promise<string> => {
      const { data } = await api.get(`/transactions/${transactionId}/attachments/${attachmentId}`, {
        responseType: 'blob',
      })
      return URL.createObjectURL(data)
    },
    rename: async (transactionId: string, attachmentId: string, filename: string): Promise<Attachment> => {
      const { data } = await api.patch(`/transactions/${transactionId}/attachments/${attachmentId}`, { filename })
      return data
    },
    delete: async (transactionId: string, attachmentId: string): Promise<void> => {
      await api.delete(`/transactions/${transactionId}/attachments/${attachmentId}`)
    },
  },
}

// Payees
export const payees = {
  list: async (params?: { q?: string; type?: string; is_favorite?: boolean } | Record<string, unknown>): Promise<Payee[]> => {
    const cleanParams = params && !('queryKey' in params) ? params : undefined
    const { data } = await api.get('/payees', { params: cleanParams })
    return data
  },
  get: async (id: string): Promise<Payee> => {
    const { data } = await api.get(`/payees/${id}`)
    return data
  },
  summary: async (id: string, from?: string, to?: string): Promise<PayeeSummary> => {
    const { data } = await api.get(`/payees/${id}/summary`, { params: { from, to } })
    return data
  },
  create: async (payee: { name: string; type?: string; notes?: string }): Promise<Payee> => {
    const { data } = await api.post('/payees', payee)
    return data
  },
  update: async (id: string, payee: Partial<Payee>): Promise<Payee> => {
    const { data } = await api.patch(`/payees/${id}`, payee)
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/payees/${id}`)
  },
  merge: async (targetId: string, sourceIds: string[]): Promise<{ merged: number; transactions_reassigned: number }> => {
    const { data } = await api.post('/payees/merge', { target_id: targetId, source_ids: sourceIds })
    return data
  },
  bulkDelete: async (ids: string[]): Promise<{ deleted: number }> => {
    const { data } = await api.post('/payees/bulk-delete', { ids })
    return data
  },
}

// Groups (split transactions)
export interface GroupCreatePayload {
  name: string
  kind?: GroupKind
  default_currency?: string
  icon?: string
  color?: string
  notes?: string | null
}

export interface GroupMemberPayload {
  name: string
  linked_user_id?: string | null
  email?: string | null
  is_self?: boolean
}

export interface GroupSettlementPayload {
  from_member_id: string
  to_member_id: string
  amount: number
  currency: string
  date: string
  transaction_id?: string | null
  notes?: string | null
  // When provided, the backend creates a debit transaction on this
  // account and links it via transaction_id. Mutually exclusive with
  // passing transaction_id directly.
  account_id?: string | null
  description?: string | null
}

export const groups = {
  list: async (includeArchived = false): Promise<Group[]> => {
    const { data } = await api.get('/groups', { params: { include_archived: includeArchived } })
    return data
  },
  get: async (id: string): Promise<Group> => {
    const { data } = await api.get(`/groups/${id}`)
    return data
  },
  create: async (payload: GroupCreatePayload): Promise<Group> => {
    const { data } = await api.post('/groups', payload)
    return data
  },
  update: async (id: string, payload: Partial<GroupCreatePayload> & { is_archived?: boolean }): Promise<Group> => {
    const { data } = await api.patch(`/groups/${id}`, payload)
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/groups/${id}`)
  },
  members: {
    list: async (groupId: string): Promise<GroupMember[]> => {
      const { data } = await api.get(`/groups/${groupId}/members`)
      return data
    },
    create: async (groupId: string, payload: GroupMemberPayload): Promise<GroupMember> => {
      const { data } = await api.post(`/groups/${groupId}/members`, payload)
      return data
    },
    update: async (groupId: string, memberId: string, payload: Partial<GroupMemberPayload>): Promise<GroupMember> => {
      const { data } = await api.patch(`/groups/${groupId}/members/${memberId}`, payload)
      return data
    },
    delete: async (groupId: string, memberId: string): Promise<void> => {
      await api.delete(`/groups/${groupId}/members/${memberId}`)
    },
  },
  settlements: {
    list: async (groupId: string): Promise<GroupSettlement[]> => {
      const { data } = await api.get(`/groups/${groupId}/settlements`)
      return data
    },
    create: async (groupId: string, payload: GroupSettlementPayload): Promise<GroupSettlement> => {
      const { data } = await api.post(`/groups/${groupId}/settlements`, payload)
      return data
    },
    update: async (groupId: string, settlementId: string, payload: Partial<GroupSettlementPayload>): Promise<GroupSettlement> => {
      const { data } = await api.patch(`/groups/${groupId}/settlements/${settlementId}`, payload)
      return data
    },
    delete: async (groupId: string, settlementId: string): Promise<void> => {
      await api.delete(`/groups/${groupId}/settlements/${settlementId}`)
    },
  },
  balances: async (groupId: string): Promise<GroupBalances> => {
    const { data } = await api.get(`/groups/${groupId}/balances`)
    return data
  },
  transactions: async (groupId: string, limit = 20): Promise<Transaction[]> => {
    const { data } = await api.get(`/groups/${groupId}/transactions`, {
      params: { limit },
    })
    return data
  },
}

// Helper re-export so transaction-creation forms have a typed entry point.
export type { TransactionSplitsInput }

// User lookup: exact-match resolution for linking group members to
// existing Securo users. Returns null on miss (404).
export interface UserLookupResult {
  id: string
  email: string
}

export const users = {
  lookupByEmail: async (email: string): Promise<UserLookupResult | null> => {
    try {
      const { data } = await api.get('/users/lookup', { params: { email } })
      return data
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 404) return null
      throw err
    }
  },
  directory: async (): Promise<UserLookupResult[]> => {
    const { data } = await api.get('/users/directory')
    return data
  },
}


// Categorization Rules
export const rules = {
  list: async (): Promise<Rule[]> => {
    const { data } = await api.get('/rules')
    return data
  },
  create: async (rule: Omit<Rule, 'id' | 'user_id'>): Promise<Rule & { applied_count: number }> => {
    const { data } = await api.post('/rules', rule)
    return data
  },
  update: async (id: string, rule: Partial<Rule>): Promise<Rule & { applied_count: number }> => {
    const { data } = await api.patch(`/rules/${id}`, rule)
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/rules/${id}`)
  },
  applyAll: async (): Promise<{ applied: number }> => {
    const { data } = await api.post('/rules/apply-all')
    return data
  },
  exportFile: async (): Promise<void> => {
    const { data } = await api.get('/rules/export', { responseType: 'blob' })
    const blob = new Blob([data], { type: 'application/json;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `securo-categorization-rules-${new Date().toISOString().slice(0, 10)}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  },
  importFile: async (payload: RuleExportPayload, overwrite = false): Promise<RuleImportResponse> => {
    const { data } = await api.post('/rules/import', { payload, overwrite })
    return data
  },
  packs: async (): Promise<{ code: string; name: string; flag: string; rule_count: number; installed: boolean }[]> => {
    const { data } = await api.get('/rules/packs')
    return data
  },
  installPack: async (
    packCode: string,
    createMissingCategories = false,
  ): Promise<{ installed: number; unresolved: number; categories_created: number }> => {
    const { data } = await api.post(`/rules/packs/${packCode}/install`, null, {
      params: { create_missing_categories: createMissingCategories },
    })
    return data
  },
}

// Recurring Transactions
export const recurring = {
  list: async (): Promise<RecurringTransaction[]> => {
    const { data } = await api.get('/recurring-transactions')
    return data
  },
  create: async (rt: Partial<RecurringTransaction>): Promise<RecurringTransaction> => {
    const { data } = await api.post('/recurring-transactions', rt)
    return data
  },
  update: async (id: string, rt: Partial<RecurringTransaction>): Promise<RecurringTransaction> => {
    const { data } = await api.patch(`/recurring-transactions/${id}`, rt)
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/recurring-transactions/${id}`)
  },
  generate: async (): Promise<{ generated: number }> => {
    const { data } = await api.post('/recurring-transactions/generate')
    return data
  },
}

// Budgets
export const budgets = {
  list: async (month?: string): Promise<Budget[]> => {
    const { data } = await api.get('/budgets', { params: { month } })
    return data
  },
  create: async (budget: { category_id: string; amount: number; month: string; is_recurring?: boolean; rollover?: boolean }): Promise<Budget> => {
    const { data } = await api.post('/budgets', budget)
    return data
  },
  update: async (id: string, budget: { amount?: number; rollover?: boolean }): Promise<Budget> => {
    const { data } = await api.patch(`/budgets/${id}`, budget)
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/budgets/${id}`)
  },
  comparison: async (month?: string): Promise<BudgetVsActual[]> => {
    const { data } = await api.get('/budgets/comparison', { params: { month } })
    return data
  },
  groupSummary: async (month?: string): Promise<{ month: string; groups: { id: string; name: string | null; budget: number; actual: number; remaining: number; percentage: number | null; categories: number; over: boolean }[] }> => {
    const { data } = await api.get('/budgets/group-summary', { params: { month } })
    return data
  },
  streak: async (): Promise<{ streak: number; best: number; months: { month: string; within: boolean; budget: number; spent: number }[] }> => {
    const { data } = await api.get('/budgets/streak')
    return data
  },
}

// Goals
export const goals = {
  list: async (status?: string): Promise<Goal[]> => {
    const { data } = await api.get('/goals', { params: { status } })
    return data
  },
  get: async (id: string): Promise<Goal> => {
    const { data } = await api.get(`/goals/${id}`)
    return data
  },
  create: async (goal: Partial<Goal>): Promise<Goal> => {
    const { data } = await api.post('/goals', goal)
    return data
  },
  update: async (id: string, goal: Partial<Goal>): Promise<Goal> => {
    const { data } = await api.patch(`/goals/${id}`, goal)
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/goals/${id}`)
  },
  summary: async (limit = 3): Promise<GoalSummary[]> => {
    const { data } = await api.get('/goals/summary', { params: { limit } })
    return data
  },
}

// Dashboard
// Repeated `account_ids=a&account_ids=b` (no [] brackets) so FastAPI's
// list[UUID] query param parses them. Only attached when a filter is active.
const acctIdsParam = (accountIds?: string[]) =>
  accountIds && accountIds.length > 0
    ? { params: { account_ids: accountIds }, paramsSerializer: { indexes: null as null } }
    : {}

export const dashboard = {
  summary: async (month?: string, balanceDate?: string, accountIds?: string[], assetGroupIds?: string[]): Promise<DashboardSummary> => {
    const hasFilter = (accountIds && accountIds.length > 0) || (assetGroupIds && assetGroupIds.length > 0)
    const { data } = await api.get('/dashboard/summary', {
      params: {
        month, balance_date: balanceDate,
        ...(accountIds && accountIds.length > 0 ? { account_ids: accountIds } : {}),
        ...(assetGroupIds && assetGroupIds.length > 0 ? { asset_group_ids: assetGroupIds } : {}),
      },
      ...(hasFilter ? { paramsSerializer: { indexes: null as null } } : {}),
    })
    return data
  },
  spendingByCategory: async (month?: string, accountIds?: string[]): Promise<SpendingByCategory[]> => {
    const extra = acctIdsParam(accountIds)
    const { data } = await api.get('/dashboard/spending-by-category', { params: { month, ...(extra.params ?? {}) }, ...(extra.paramsSerializer ? { paramsSerializer: extra.paramsSerializer } : {}) })
    return data
  },
  monthlyTrend: async (months = 6, accountIds?: string[]): Promise<MonthlyTrend[]> => {
    const extra = acctIdsParam(accountIds)
    const { data } = await api.get('/dashboard/monthly-trend', { params: { months, ...(extra.params ?? {}) }, ...(extra.paramsSerializer ? { paramsSerializer: extra.paramsSerializer } : {}) })
    return data
  },
  projectedTransactions: async (month?: string, dateBasis?: 'effective' | 'purchase'): Promise<ProjectedTransaction[]> => {
    const { data } = await api.get('/dashboard/projected-transactions', { params: { month, date_basis: dateBasis } })
    return data
  },
  balanceHistory: async (month?: string, accountIds?: string[]): Promise<BalanceHistory> => {
    const extra = acctIdsParam(accountIds)
    const { data } = await api.get('/dashboard/balance-history', { params: { month, ...(extra.params ?? {}) }, ...(extra.paramsSerializer ? { paramsSerializer: extra.paramsSerializer } : {}) })
    return data
  },
}

// Assets
export const assets = {
  list: async (includeArchived = false): Promise<Asset[]> => {
    const { data } = await api.get('/assets', { params: { include_archived: includeArchived } })
    return data
  },
  get: async (id: string): Promise<Asset> => {
    const { data } = await api.get(`/assets/${id}`)
    return data
  },
  create: async (asset: Partial<Asset> & { name: string; type: string; current_value?: number }): Promise<Asset> => {
    const { data } = await api.post('/assets', asset)
    return data
  },
  update: async (id: string, asset: Partial<Asset>, opts?: { regenerateGrowth?: boolean }): Promise<Asset> => {
    const { data } = await api.patch(`/assets/${id}`, asset, {
      params: opts?.regenerateGrowth ? { regenerate_growth: true } : undefined,
    })
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/assets/${id}`)
  },
  values: async (id: string): Promise<AssetValue[]> => {
    const { data } = await api.get(`/assets/${id}/values`)
    return data
  },
  valueTrend: async (id: string, months = 12): Promise<{ date: string; amount: number }[]> => {
    const { data } = await api.get(`/assets/${id}/value-trend`, { params: { months } })
    return data
  },
  addValue: async (id: string, value: { amount: number; date: string }): Promise<AssetValue> => {
    const { data } = await api.post(`/assets/${id}/values`, value)
    return data
  },
  deleteValue: async (valueId: string): Promise<void> => {
    await api.delete(`/assets/values/${valueId}`)
  },
  portfolioTrend: async (): Promise<{ assets: { id: string; name: string; type: string; group_id: string | null }[]; trend: Record<string, unknown>[]; total: number }> => {
    const { data } = await api.get('/assets/portfolio-trend')
    return data
  },
  returns: async (types?: string[]): Promise<AssetReturns> => {
    const { data } = await api.get('/assets/returns', { params: { types } })
    return data
  },
  marketSearch: async (q: string, limit = 15): Promise<MarketSymbolMatch[]> => {
    const { data } = await api.get('/assets/market/search', { params: { q, limit } })
    return data
  },
  marketQuote: async (symbol: string): Promise<MarketSymbolQuote> => {
    const { data } = await api.get('/assets/market/quote', { params: { symbol } })
    return data
  },
  refreshPrice: async (id: string): Promise<Asset> => {
    const { data } = await api.post(`/assets/${id}/refresh-price`)
    return data
  },
  // Transaction ledger (issue #235)
  transactions: async (id: string): Promise<AssetTransaction[]> => {
    const { data } = await api.get(`/assets/${id}/transactions`)
    return data
  },
  allTransactions: async (params?: { ticker?: string; kind?: 'buy' | 'sell' }): Promise<AssetTransaction[]> => {
    const { data } = await api.get('/assets/transactions', { params })
    return data
  },
  addTransaction: async (
    id: string,
    tx: { kind: 'buy' | 'sell'; quantity: number; price: number; fee?: number; date: string; notes?: string },
  ): Promise<Asset> => {
    const { data } = await api.post(`/assets/${id}/transactions`, tx)
    return data
  },
  updateTransaction: async (
    txId: string,
    tx: Partial<{ kind: 'buy' | 'sell'; quantity: number; price: number; fee: number; date: string; notes: string }>,
  ): Promise<Asset> => {
    const { data } = await api.patch(`/assets/transactions/${txId}`, tx)
    return data
  },
  deleteTransaction: async (txId: string): Promise<Asset> => {
    const { data } = await api.delete(`/assets/transactions/${txId}`)
    return data
  },
  buy: async (
    tx: { ticker: string; quantity: number; price: number; fee?: number; date: string; name?: string; group_id?: string | null; notes?: string },
  ): Promise<Asset> => {
    const { data } = await api.post('/assets/buy', tx)
    return data
  },
}

// Asset Groups ("wallets")
export const assetGroups = {
  list: async (): Promise<AssetGroup[]> => {
    const { data } = await api.get('/asset-groups')
    return data
  },
  create: async (group: Partial<AssetGroup> & { name: string }): Promise<AssetGroup> => {
    const { data } = await api.post('/asset-groups', group)
    return data
  },
  update: async (id: string, group: Partial<AssetGroup>): Promise<AssetGroup> => {
    const { data } = await api.patch(`/asset-groups/${id}`, group)
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/asset-groups/${id}`)
  },
}

// Collections — user-defined account groups for filtering (issue #105)
export const collections = {
  list: async (): Promise<Collection[]> => {
    const { data } = await api.get('/collections')
    return data
  },
  create: async (payload: { name: string; icon?: string; color?: string; account_ids?: string[]; wallet_ids?: string[] }): Promise<Collection> => {
    const { data } = await api.post('/collections', payload)
    return data
  },
  update: async (id: string, payload: Partial<{ name: string; icon: string; color: string; position: number; account_ids: string[]; wallet_ids: string[] }>): Promise<Collection> => {
    const { data } = await api.patch(`/collections/${id}`, payload)
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/collections/${id}`)
  },
}

// Reports
export const reports = {
  netWorth: async (months = 12, interval = 'monthly', accountIds?: string[], assetGroupIds?: string[], period?: 'ytd'): Promise<ReportResponse> => {
    const hasFilter = (accountIds && accountIds.length > 0) || (assetGroupIds && assetGroupIds.length > 0)
    const { data } = await api.get('/reports/net-worth', {
      params: {
        months, interval, period,
        ...(accountIds && accountIds.length > 0 ? { account_ids: accountIds } : {}),
        ...(assetGroupIds && assetGroupIds.length > 0 ? { asset_group_ids: assetGroupIds } : {}),
      },
      ...(hasFilter ? { paramsSerializer: { indexes: null as null } } : {}),
    })
    return data
  },
  // `days` requests an exact rolling window ending today, instead of the
  // month-aligned window `months` produces.
  incomeExpenses: async (months = 12, interval = 'monthly', accountIds?: string[], period?: 'ytd', days?: number): Promise<ReportResponse> => {
    const extra = acctIdsParam(accountIds)
    const { data } = await api.get('/reports/income-expenses', { params: { months, interval, period, days, ...(extra.params ?? {}) }, ...(extra.paramsSerializer ? { paramsSerializer: extra.paramsSerializer } : {}) })
    return data
  },
  cashFlow: async (months = 6, interval = 'daily', baseline = false, accountIds?: string[]): Promise<ReportResponse> => {
    const extra = acctIdsParam(accountIds)
    const { data } = await api.get('/reports/cash-flow', { params: { months, interval, baseline, ...(extra.params ?? {}) }, ...(extra.paramsSerializer ? { paramsSerializer: extra.paramsSerializer } : {}) })
    return data
  },
}

// Currencies
export const currencies = {
  list: async (): Promise<{ code: string; symbol: string; name: string; flag: string }[]> => {
    const { data } = await api.get('/currencies')
    return data
  },
}

// FX Rates
export const fxRates = {
  refresh: async (): Promise<{ synced: boolean; rates_count: number; date: string }> => {
    const { data } = await api.post('/fx-rates/refresh')
    return data
  },
  status: async (): Promise<{ last_sync_date: string | null; total_rates: number }> => {
    const { data } = await api.get('/fx-rates/status')
    return data
  },
}

// Import Logs
export const importLogs = {
  list: async (): Promise<ImportLog[]> => {
    const { data } = await api.get('/import-logs')
    return data
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/import-logs/${id}`)
  },
}

// Settings
export const settings = {
  attachments: async (): Promise<{ allowed_extensions: string[]; max_file_size_mb: number; max_attachments_per_transaction: number }> => {
    const { data } = await api.get('/settings/attachments')
    return data
  },
}

// Backup
export const backup = {
  download: async (): Promise<void> => {
    const { data } = await api.get('/export/backup', { responseType: 'blob' })
    const blob = new Blob([data], { type: 'application/zip' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `securo-backup-${new Date().toISOString().slice(0, 10)}.zip`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  },
}

// Admin
export const admin = {
  listUsers: async (params?: { search?: string; page?: number; limit?: number }): Promise<AdminUserList> => {
    const { data } = await api.get('/admin/users', { params })
    return data
  },
  getUser: async (id: string): Promise<AdminUser> => {
    const { data } = await api.get(`/admin/users/${id}`)
    return data
  },
  createUser: async (user: { email: string; password: string; is_superuser?: boolean; preferences?: Record<string, unknown> }): Promise<AdminUser> => {
    const { data } = await api.post('/admin/users', user)
    return data
  },
  updateUser: async (id: string, user: Partial<{ email: string; password: string; is_active: boolean; is_superuser: boolean; preferences: Record<string, unknown> }>): Promise<AdminUser> => {
    const { data } = await api.patch(`/admin/users/${id}`, user)
    return data
  },
  deleteUser: async (id: string): Promise<void> => {
    await api.delete(`/admin/users/${id}`)
  },
  getSetting: async (key: string): Promise<AppSetting> => {
    const { data } = await api.get(`/admin/settings/${key}`)
    return data
  },
  updateSetting: async (key: string, value: string): Promise<AppSetting> => {
    const { data } = await api.patch(`/admin/settings/${key}`, { value })
    return data
  },
  registrationStatus: async (): Promise<{ enabled: boolean }> => {
    const { data } = await api.get('/admin/registration-status')
    return data
  },
  accountingMode: async (): Promise<{ mode: 'cash' | 'accrual' }> => {
    const { data } = await api.get('/admin/accounting-mode')
    return data
  },
  accountsViewMode: async (): Promise<{ mode: 'grouped' | 'compact' }> => {
    const { data } = await api.get('/admin/accounts-view-mode')
    return data
  },
  numberFormat: async (): Promise<{ format: NumberFormat }> => {
    const { data } = await api.get('/admin/number-format')
    return data
  },
  dateFormat: async (): Promise<{ format: DateFormat }> => {
    const { data } = await api.get('/admin/date-format')
    return data
  },
  defaultColors: async (): Promise<{ light: string | null; dark: string | null }> => {
    const { data } = await api.get('/admin/default-colors')
    return data
  },
}

// Global search (powers the command palette)
export type SearchHitType =
  | 'transaction'
  | 'account'
  | 'payee'
  | 'category'
  | 'goal'
  | 'asset'

export interface SearchHit {
  type: SearchHitType
  id: string
  label: string
  subtitle: string | null
  amount: number | null
  currency: string | null
  date: string | null
  icon: string | null
  color: string | null
  meta: Record<string, unknown>
}

export const search = {
  query: async (q: string, limit = 5): Promise<SearchHit[]> => {
    if (!q.trim()) return []
    const { data } = await api.get('/search', { params: { q, limit } })
    return data.results as SearchHit[]
  },
}

// App-level feature flags (whether optional modules like agents are mounted)
export interface AppInfo {
  features: { agents: boolean; tesouro_direto?: boolean }
}

export const info = {
  get: async (): Promise<AppInfo> => {
    const { data } = await api.get('/info')
    return data
  },
}

// Agents / MCP / RAG -- only meaningful when info.features.agents === true.
export interface Agent {
  id: string
  name: string
  description: string | null
  system_prompt: string
  icon: string
  color: string
  connection_id: string | null
  provider: string | null
  model: string | null
  temperature: number
  max_history_messages: number
  top_n: number
  similarity_threshold: number
  extra: Record<string, unknown>
  auto_context: boolean
  is_archived: boolean
  is_default: boolean
  // Populated by GET /agents (list endpoint) for the agents page.
  // Single-agent endpoints leave them at 0 since the row-level page
  // already shows tabs for both lists.
  conversation_count: number
  knowledge_count: number
  created_at: string
  updated_at: string
}

export type LlmConnectionKind = 'ollama' | 'openai' | 'anthropic' | 'openai_compatible'

export interface LlmConnection {
  id: string
  name: string
  kind: LlmConnectionKind
  base_url: string | null
  default_model: string | null
  extra: Record<string, unknown>
  is_default: boolean
  has_api_key: boolean
  created_at: string
  updated_at: string
}

export interface LlmConnectionPayload {
  name: string
  kind: LlmConnectionKind
  base_url?: string | null
  api_key?: string | null
  default_model?: string | null
  extra?: Record<string, unknown>
  is_default?: boolean
}

export interface LlmConnectionTestResult {
  ok: boolean
  detail: string
  models?: string[]
}

export interface AgentConversation {
  id: string
  agent_id: string
  channel: string
  title: string | null
  created_at: string
  updated_at: string
}

export interface AgentMessage {
  id: string
  role: 'system' | 'user' | 'assistant' | 'tool'
  ordinal: number
  content: string | null
  tool_calls: Array<{ id: string; name: string; arguments: Record<string, unknown> }> | null
  tool_result: { tool_call_id?: string; name?: string; data?: unknown; ok?: boolean } | null
  citations: unknown[] | null
  input_tokens: number | null
  output_tokens: number | null
  created_at: string
}

export interface AgentToolHandle {
  server: string
  name: string
  description: string
  is_proposal: boolean
  enabled: boolean
}

export interface KnowledgeDoc {
  id: string
  agent_id: string
  title: string
  source: string | null
  mime: string
  size_bytes: number
  status: 'pending' | 'processing' | 'ready' | 'failed'
  error: string | null
  chunk_count: number
  pinned: boolean
  created_at: string
  updated_at: string
}

export const agents = {
  info: async () => {
    const { data } = await api.get('/agents/info')
    return data as {
      enabled: boolean
      providers: string[]
      embedding_dim: number
      default_top_n: number
      default_similarity_threshold: number
      extra_mcp_servers_configured: boolean
      mcp_external_ttl_days: number
      external_mcp_url: string
    }
  },
  mcpTokens: {
    create: async (): Promise<{ token: string; expires_in_seconds: number; expires_in_days: number }> => {
      const { data } = await api.post('/agents/mcp-tokens')
      return data
    },
  },
  list: async (includeArchived = false): Promise<Agent[]> => {
    const { data } = await api.get('/agents', { params: { include_archived: includeArchived } })
    return data
  },
  // Default agent for the global slide-over chat panel. Returns the
  // user-flagged default; falls back to the most recent agent.
  // Throws 404 if the user has no agents at all.
  getDefault: async (): Promise<Agent> => {
    const { data } = await api.get('/agents/default')
    return data
  },
  get: async (id: string): Promise<Agent> => {
    const { data } = await api.get(`/agents/${id}`)
    return data
  },
  create: async (payload: Partial<Agent> & { name: string }): Promise<Agent> => {
    const { data } = await api.post('/agents', payload)
    return data
  },
  update: async (id: string, payload: Partial<Agent>): Promise<Agent> => {
    const { data } = await api.patch(`/agents/${id}`, payload)
    return data
  },
  remove: async (id: string): Promise<void> => {
    await api.delete(`/agents/${id}`)
  },
  tools: async (id: string): Promise<{ servers: { name: string }[]; tools: AgentToolHandle[] }> => {
    const { data } = await api.get(`/agents/${id}/tools`)
    return data
  },
  setTools: async (id: string, items: { server: string; tool_name: string; enabled: boolean }[]): Promise<void> => {
    await api.put(`/agents/${id}/tools`, items)
  },
  knowledge: {
    list: async (id: string): Promise<{ items: KnowledgeDoc[]; total: number }> => {
      const { data } = await api.get(`/agents/${id}/knowledge`)
      return data
    },
    upload: async (id: string, file: File, pinned = false): Promise<KnowledgeDoc> => {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('pinned', String(pinned))
      const { data } = await api.post(`/agents/${id}/knowledge`, fd)
      return data
    },
    pin: async (agentId: string, docId: string, pinned: boolean): Promise<KnowledgeDoc> => {
      const { data } = await api.patch(`/agents/${agentId}/knowledge/${docId}/pin`, null, {
        params: { pinned },
      })
      return data
    },
    remove: async (agentId: string, docId: string): Promise<void> => {
      await api.delete(`/agents/${agentId}/knowledge/${docId}`)
    },
  },
  conversations: {
    list: async (agentId?: string, limit = 50): Promise<AgentConversation[]> => {
      const { data } = await api.get('/agents/conversations', { params: { agent_id: agentId, limit } })
      return data
    },
    get: async (id: string): Promise<AgentConversation> => {
      const { data } = await api.get(`/agents/conversations/${id}`)
      return data
    },
    messages: async (id: string, limit = 200): Promise<AgentMessage[]> => {
      const { data } = await api.get(`/agents/conversations/${id}/messages`, { params: { limit } })
      return data
    },
    rename: async (id: string, title: string): Promise<AgentConversation> => {
      const { data } = await api.patch(`/agents/conversations/${id}`, { title })
      return data
    },
    generateTitle: async (id: string): Promise<AgentConversation> => {
      const { data } = await api.post(`/agents/conversations/${id}/generate-title`)
      return data
    },
    remove: async (id: string): Promise<void> => {
      await api.delete(`/agents/conversations/${id}`)
    },
  },
  // Streaming chat endpoint — caller handles the SSE response themselves
  // (see lib/agents-stream.ts). We just expose the URL + body builder.
  chatUrl: (agentId: string) => `/api/agents/${agentId}/chat`,

  connections: {
    list: async (): Promise<LlmConnection[]> => {
      const { data } = await api.get('/agents/connections')
      return data
    },
    get: async (id: string): Promise<LlmConnection> => {
      const { data } = await api.get(`/agents/connections/${id}`)
      return data
    },
    create: async (payload: LlmConnectionPayload): Promise<LlmConnection> => {
      const { data } = await api.post('/agents/connections', payload)
      return data
    },
    update: async (id: string, payload: Partial<LlmConnectionPayload>): Promise<LlmConnection> => {
      const { data } = await api.patch(`/agents/connections/${id}`, payload)
      return data
    },
    remove: async (id: string): Promise<void> => {
      await api.delete(`/agents/connections/${id}`)
    },
    test: async (id: string): Promise<LlmConnectionTestResult> => {
      const { data } = await api.post(`/agents/connections/${id}/test`)
      return data
    },
  },
}

// ---------------------------------------------------------------------------
// Feature batch: notifications, subscriptions, insights, forecast, health
// score, debt planner, advanced reports, installment grouping.
// ---------------------------------------------------------------------------

export interface Notification {
  id: string
  type: string
  severity: 'info' | 'warning' | 'critical'
  title: string
  body: string | null
  link: string | null
  data_json: Record<string, unknown> | null
  is_read: boolean
  created_at: string
}

export const notifications = {
  list: async (unreadOnly = false, limit = 50): Promise<{ items: Notification[]; unread: number }> => {
    const { data } = await api.get('/notifications', { params: { unread_only: unreadOnly, limit } })
    return data
  },
  unreadCount: async (): Promise<{ unread: number }> => {
    const { data } = await api.get('/notifications/unread-count')
    return data
  },
  refresh: async (): Promise<{ unread: number }> => {
    const { data } = await api.post('/notifications/refresh')
    return data
  },
  markRead: async (id: string): Promise<void> => {
    await api.post(`/notifications/${id}/read`)
  },
  markAllRead: async (): Promise<{ unread: number }> => {
    const { data } = await api.post('/notifications/read-all')
    return data
  },
  remove: async (id: string): Promise<void> => {
    await api.delete(`/notifications/${id}`)
  },
}

export interface Subscription {
  key: string
  name: string
  frequency: string
  typical_amount: number
  last_amount: number
  currency: string
  monthly_cost: number
  yearly_cost: number
  occurrences: number
  last_date: string
  next_date: string
  price_change: boolean
  category_id: string | null
}

export const subscriptions = {
  list: async (): Promise<{ count: number; monthly_total: number; yearly_total: number; price_changes: number; subscriptions: Subscription[] }> => {
    const { data } = await api.get('/subscriptions')
    return data
  },
}

export const insights = {
  get: async (): Promise<{
    currency: string
    insights: { type: string; severity: string; category: string | null; title: string; detail: string; value: number }[]
    movers: { category: string; direction: string; current: number; previous: number; change_pct: number }[]
    savings_series: { month: string; income: number; expense: number; savings_rate: number }[]
    top_merchants: { name: string; total: number; count: number }[]
  }> => {
    const { data } = await api.get('/insights')
    return data
  },
}

export const forecast = {
  get: async (days = 90, incomeAdjust = 0, expenseAdjust = 0): Promise<{
    currency: string
    days: number
    starting_balance: number
    ending_balance: number
    lowest: { date: string; balance: number }
    first_shortfall: { date: string; balance: number } | null
    shortfall_days: number
    series: { date: string; balance: number }[]
  }> => {
    const { data } = await api.get('/forecast', { params: { days, income_adjust: incomeAdjust, expense_adjust: expenseAdjust } })
    return data
  },
}

export const roundups = {
  get: async (months = 1, multiplier = 1): Promise<{ currency: string; months: number; multiplier: number; transaction_count: number; roundup_total: number }> => {
    const { data } = await api.get('/roundups', { params: { months, multiplier } })
    return data
  },
}

export interface SavedSearch {
  id: string
  name: string
  filters_json: Record<string, unknown> | null
  position: number
  created_at: string
}

export const savedSearches = {
  list: async (): Promise<SavedSearch[]> => {
    const { data } = await api.get('/saved-searches')
    return data
  },
  create: async (name: string, filters: Record<string, unknown>): Promise<SavedSearch> => {
    const { data } = await api.post('/saved-searches', { name, filters_json: filters })
    return data
  },
  remove: async (id: string): Promise<void> => {
    await api.delete(`/saved-searches/${id}`)
  },
}

export const healthScore = {
  get: async (): Promise<{
    currency: string
    score: number
    band: string
    components: { key: string; label: string; score: number; detail: string }[]
    monthly_income: number
    monthly_expense: number
    liquid_balance: number
  }> => {
    const { data } = await api.get('/health-score')
    return data
  },
}

export interface DebtAccount {
  id?: string
  name: string
  balance: number
  apr: number
  min_payment: number
  currency?: string
}

export const debt = {
  accounts: async (): Promise<DebtAccount[]> => {
    const { data } = await api.get('/debt/accounts')
    return data
  },
  plan: async (extra_payment: number, debts?: DebtAccount[]): Promise<{
    debts: DebtAccount[]
    total_balance: number
    total_minimum: number
    extra_payment: number
    snowball: { months: number; total_interest: number; payoff_date: string; order: string[]; amortized: boolean }
    avalanche: { months: number; total_interest: number; payoff_date: string; order: string[]; amortized: boolean }
    recommended: string
  }> => {
    const { data } = await api.post('/debt/plan', { extra_payment, debts })
    return data
  },
}

export interface InstallmentPlan {
  key: string
  name: string
  account_id: string
  account_name: string
  total_installments: number
  paid_count: number
  per_installment: number
  total_amount: number
  currency: string
  purchase_date: string
  category_id: string | null
  category_name: string | null
  category_color: string | null
  mixed_categories: boolean
  uncategorized: boolean
  transaction_ids: string[]
}

export const installments = {
  list: async (onlyUncategorized = false, accountId?: string): Promise<{ count: number; uncategorized_count: number; plans: InstallmentPlan[] }> => {
    const { data } = await api.get('/installments', { params: { only_uncategorized: onlyUncategorized, account_id: accountId } })
    return data
  },
  categorize: async (transactionIds: string[], categoryId: string | null): Promise<{ updated: number }> => {
    const { data } = await api.patch('/installments/categorize', { transaction_ids: transactionIds, category_id: categoryId })
    return data
  },
}

export const advancedReports = {
  merchants: async (months = 3, categoryId?: string): Promise<{ currency: string; months: number; merchants: { merchant: string; total: number; count: number; average: number }[] }> => {
    const { data } = await api.get('/reports/merchants', { params: { months, category_id: categoryId } })
    return data
  },
  categoryTrends: async (months = 6): Promise<{ currency: string; months: string[]; categories: { id: string; name: string; color: string | null }[]; series: Record<string, string | number>[] }> => {
    const { data } = await api.get('/reports/category-trends', { params: { months } })
    return data
  },
  periodComparison: async (months = 1): Promise<{ currency: string; months: number; current_total: number; previous_total: number; rows: { category: string; current: number; previous: number; change: number; change_pct: number | null }[] }> => {
    const { data } = await api.get('/reports/period-comparison', { params: { months } })
    return data
  },
  categoryBreakdown: async (opts: { months?: number; period?: 'ytd'; accountIds?: string[]; flow?: 'expense' | 'income'; year?: number; month?: number; dateBasis?: 'effective' | 'purchase' } = {}): Promise<{
    currency: string
    flow: string
    total: number
    groups: { id: string; name: string | null; color: string; total: number; is_group: boolean; uncategorized: boolean; percentage: number }[]
    children: { id: string; name: string | null; color: string; total: number; uncategorized: boolean; parent: string; percentage: number }[]
    slices: { id: string; name: string | null; color: string; total: number; is_group: boolean; uncategorized: boolean; percentage: number }[]
  }> => {
    const { months = 1, period, accountIds, flow = 'expense', year, month, dateBasis } = opts
    const extra = acctIdsParam(accountIds)
    const { data } = await api.get('/reports/category-breakdown', {
      params: { months, period, flow, year, month, date_basis: dateBasis, ...(extra.params ?? {}) },
      ...(extra.paramsSerializer ? { paramsSerializer: extra.paramsSerializer } : {}),
    })
    return data
  },
}

export interface SinkingFund {
  id: string
  user_id: string
  name: string
  target_amount: number
  current_amount: number
  currency: string
  target_date: string | null
  monthly_contribution: number | null
  account_id: string | null
  status: string
  icon: string | null
  color: string | null
  position: number
  percentage: number
  suggested_monthly: number | null
  months_remaining: number | null
  account_name: string | null
}

export const sinkingFunds = {
  list: async (status?: string): Promise<SinkingFund[]> => {
    const { data } = await api.get('/sinking-funds', { params: { status } })
    return data
  },
  summary: async (): Promise<{ count: number; total_saved: number; total_target: number; monthly_needed: number }> => {
    const { data } = await api.get('/sinking-funds/summary')
    return data
  },
  create: async (payload: Partial<SinkingFund>): Promise<SinkingFund> => {
    const { data } = await api.post('/sinking-funds', payload)
    return data
  },
  update: async (id: string, payload: Partial<SinkingFund>): Promise<SinkingFund> => {
    const { data } = await api.patch(`/sinking-funds/${id}`, payload)
    return data
  },
  contribute: async (id: string, amount: number): Promise<SinkingFund> => {
    const { data } = await api.post(`/sinking-funds/${id}/contribute`, { amount })
    return data
  },
  remove: async (id: string): Promise<void> => {
    await api.delete(`/sinking-funds/${id}`)
  },
}

export interface CalendarEvent {
  date: string
  kind: 'bill' | 'recurring_income' | 'recurring_expense' | 'installment'
  title: string
  amount: number
  currency: string
}

export const financeCalendar = {
  get: async (year: number, month: number): Promise<{
    year: number
    month: number
    currency: string
    daily: Record<string, { income: number; expense: number; net: number }>
    events: CalendarEvent[]
    month_income: number
    month_expense: number
  }> => {
    const { data } = await api.get('/calendar', { params: { year, month } })
    return data
  },
}

// --- Loan simulator (Price / SAC) ---
export interface LoanScheduleRow { n: number; payment: number; interest: number; principal: number; balance: number }
export interface LoanResult {
  method: string
  months: number
  first_payment: number
  last_payment: number
  total_interest: number
  total_paid: number
  payoff_date: string
  amortized: boolean
  schedule: LoanScheduleRow[]
}
export interface LoanSimulation {
  currency: string
  principal: number
  monthly_rate: number
  annual_rate: number
  term_months: number
  extra_payment: number
  results: Record<string, LoanResult>
  recommended: string
}

export const loans = {
  simulate: async (payload: {
    principal: number; rate: number; months: number
    rate_period?: 'annual' | 'monthly'; extra_payment?: number; method?: 'both' | 'price' | 'sac'
  }): Promise<LoanSimulation> => {
    const { data } = await api.post('/loans/simulate', payload)
    return data
  },
}

// --- Retirement / FIRE ---
export interface RetirementProjection {
  currency: string
  current_net_worth: number
  monthly_contribution: number
  annual_return: number
  annual_expenses: number
  withdrawal_rate: number
  fire_number: number
  progress_pct: number
  years_to_fire: number | null
  fire_date: string | null
  age_at_fire: number | null
  reached: boolean
  total_contributed: number
  monthly_income_at_fire: number
  series: { year: number; month_index: number; value: number }[]
}

export const retirement = {
  defaults: async (): Promise<{ currency: string; current_net_worth: number; suggested_monthly_contribution: number }> => {
    const { data } = await api.get('/retirement/defaults')
    return data
  },
  project: async (payload: {
    monthly_contribution: number; annual_return: number; annual_expenses: number
    withdrawal_rate?: number; current_age?: number | null; current_net_worth?: number | null
  }): Promise<RetirementProjection> => {
    const { data } = await api.post('/retirement/project', payload)
    return data
  },
}

// --- Cashback / rewards ---
export interface RewardRule {
  id: string
  account_id: string
  category_id: string | null
  rate: number
  name: string | null
  account_name: string | null
  category_name: string | null
  category_color: string | null
}
export interface RewardSummary {
  currency: string
  total_earned: number
  total_spend: number
  effective_rate: number
  by_card: { account_id: string; name: string; earned: number; spend: number }[]
  by_category: { category_id: string | null; name: string | null; color: string | null; earned: number; spend: number }[]
  best_per_category: { category_id: string | null; category_name: string | null; category_color: string | null; account_name: string; rate: number }[]
}

export const rewards = {
  list: async (): Promise<RewardRule[]> => {
    const { data } = await api.get('/rewards')
    return data
  },
  summary: async (opts: { year?: number; month?: number; months?: number } = {}): Promise<RewardSummary> => {
    const { data } = await api.get('/rewards/summary', { params: opts })
    return data
  },
  create: async (payload: { account_id: string; category_id?: string | null; rate: number; name?: string | null }): Promise<RewardRule> => {
    const { data } = await api.post('/rewards', payload)
    return data
  },
  update: async (id: string, payload: Partial<{ account_id: string; category_id: string | null; rate: number; name: string | null }>): Promise<RewardRule> => {
    const { data } = await api.patch(`/rewards/${id}`, payload)
    return data
  },
  remove: async (id: string): Promise<void> => {
    await api.delete(`/rewards/${id}`)
  },
}

// --- Fixed-income comparator (renda fixa) ---
export interface FixedIncomeOption {
  id: string
  name: string
  institution: string | null
  product_type: string
  rate_kind: 'cdi' | 'prefixed' | 'ipca_plus'
  rate: number
  liquidity: 'daily' | 'maturity'
  maturity_date: string | null
  min_amount: number | null
  tax_exempt: boolean
}
export interface FixedIncomeComparison {
  amount: number
  horizon_days: number
  cdi: number
  ipca: number
  ir_rate: number
  best_id: string | null
  best_daily_id: string | null
  options: (FixedIncomeOption & {
    gross_annual: number; ir_rate: number; net_annual: number
    gross_earnings: number; net_earnings: number; final_amount: number
  })[]
}

export const fixedIncome = {
  list: async (): Promise<FixedIncomeOption[]> => {
    const { data } = await api.get('/fixed-income')
    return data
  },
  compare: async (opts: { amount?: number; horizon_days?: number; cdi?: number; ipca?: number } = {}): Promise<FixedIncomeComparison> => {
    const { data } = await api.get('/fixed-income/compare', { params: opts })
    return data
  },
  create: async (payload: Partial<FixedIncomeOption>): Promise<FixedIncomeOption> => {
    const { data } = await api.post('/fixed-income', payload)
    return data
  },
  update: async (id: string, payload: Partial<FixedIncomeOption>): Promise<FixedIncomeOption> => {
    const { data } = await api.patch(`/fixed-income/${id}`, payload)
    return data
  },
  remove: async (id: string): Promise<void> => {
    await api.delete(`/fixed-income/${id}`)
  },
}

// --- Cash vs installments ---
export interface CashVsInstallments {
  currency: string
  cash_price: number
  installment_total: number
  n_installments: number
  per_installment: number
  monthly_rate: number
  pv_cash: number
  pv_installments: number
  cheaper: 'cash' | 'installments'
  savings: number
  nominal_discount: number
  nominal_discount_pct: number
  breakeven_cash_price: number
  breakeven_discount_pct: number
}

export const purchase = {
  cashVsInstallments: async (payload: {
    cash_price: number; installment_total: number; n_installments: number
    investment_rate: number; rate_period?: 'annual' | 'monthly'; first_installment_today?: boolean
  }): Promise<CashVsInstallments> => {
    const { data } = await api.post('/purchase/cash-vs-installments', payload)
    return data
  },
}

// --- Dividends / asset income ---
export interface AssetIncome {
  id: string
  asset_id: string
  date: string
  amount: number
  currency: string
  kind: 'dividend' | 'jcp' | 'rent' | 'interest' | 'other'
  note: string | null
  asset_name: string | null
}
export interface AssetIncomeSummary {
  currency: string
  months: number
  total: number
  monthly_average: number
  by_asset: { asset_id: string; name: string; total: number; invested: number; yield_pct: number | null }[]
  series: { month: string; total: number }[]
}

export const assetIncome = {
  list: async (assetId?: string): Promise<AssetIncome[]> => {
    const { data } = await api.get('/asset-income', { params: { asset_id: assetId } })
    return data
  },
  summary: async (months = 12): Promise<AssetIncomeSummary> => {
    const { data } = await api.get('/asset-income/summary', { params: { months } })
    return data
  },
  create: async (payload: { asset_id: string; date: string; amount: number; kind?: string; note?: string | null }): Promise<AssetIncome> => {
    const { data } = await api.post('/asset-income', payload)
    return data
  },
  remove: async (id: string): Promise<void> => {
    await api.delete(`/asset-income/${id}`)
  },
}

// --- Emergency fund ---
export interface EmergencyFund {
  target_months: number
  current_amount: number
  account_id: string | null
  account_name: string | null
  monthly_contribution: number | null
  currency: string
  avg_monthly_expense: number
  target_amount: number
  saved_amount: number
  progress_pct: number
  months_covered: number
  shortfall: number
  months_to_complete: number | null
}

export const emergencyFund = {
  get: async (): Promise<EmergencyFund> => {
    const { data } = await api.get('/emergency-fund')
    return data
  },
  update: async (payload: Partial<{ target_months: number; current_amount: number; account_id: string | null; monthly_contribution: number | null }>): Promise<EmergencyFund> => {
    const { data } = await api.put('/emergency-fund', payload)
    return data
  },
}

export default api
