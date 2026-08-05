// Thin fetch wrapper around the FastAPI backend the Tauri shell spawns as a
// localhost sidecar (see ../../backend). Kept dependency-free (no axios) so
// the frontend scaffold has zero extra install surface.

const BASE_URL = "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = "";
    try {
      detail = JSON.stringify(await res.json());
    } catch {
      // response body wasn't JSON; fall through with an empty detail
    }
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${res.status} ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface MessageSummary {
  id: string;
  account_id: string;
  folder: string;
  subject: string;
  sender_name: string;
  sender_address: string;
  is_read: boolean;
  is_flagged: boolean;
  received_at: string | null;
}

export interface AttachmentInfo {
  id: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  classified_kind: string | null;
}

export interface BusinessCardContact {
  id: string;
  company_id: string | null;
  name: string;
  email_address: string;
  phone: string | null;
  department: string | null;
  title: string | null;
}

export interface MessageDetail extends MessageSummary {
  body_text: string;
  body_html: string;
  to_addresses: string[];
  cc_addresses: string[];
  classification: Record<string, unknown> | null;
  extraction: Record<string, unknown> | null;
  summary_3line: string | null;
  attachments: AttachmentInfo[];
}

export interface DashboardData {
  deals_today: number;
  candidates_today: number;
  reply_required_open: number;
  open_deal_count: number;
  open_candidate_count: number;
  top_companies: { name: string; deal_count: number }[];
  reply_rate: number | null;
  avg_reply_speed_hours: number | null;
  deal_win_rate: number | null;
  weekly_contact_frequency: number;
}

export interface AccountSummary {
  id: string;
  display_name: string;
  email_address: string;
  protocol: string;
  is_active: boolean;
  forced_llm_provider: string | null;
}

export interface AccountCreateInput {
  display_name: string;
  email_address: string;
  protocol?: string;
  imap_host?: string;
  imap_port?: number;
  smtp_host?: string;
  smtp_port?: number;
  use_ssl?: boolean;
  password?: string;
}

export interface SettingsData {
  app_name: string;
  ai_enabled: boolean;
  llm_provider: string;
  embedding_provider: string;
  openai_compatible_base_url: string;
  openai_compatible_model: string;
  anthropic_model: string;
  anonymize_before_send: boolean;
  duplicate_similarity_threshold: number;
  available_llm_providers: string[];
  has_openai_compatible_key: boolean;
  has_anthropic_key: boolean;
}

export interface SettingsUpdateInput {
  ai_enabled?: boolean;
  llm_provider?: string;
  embedding_provider?: string;
  openai_compatible_base_url?: string;
  openai_compatible_model?: string;
  anthropic_model?: string;
  anonymize_before_send?: boolean;
  duplicate_similarity_threshold?: number;
  openai_compatible_api_key?: string;
  anthropic_api_key?: string;
}

export interface CompanySummary {
  id: string;
  name: string;
  domain: string | null;
  evaluation: string | null;
  notes: string;
  last_contact_at: string | null;
  reply_rate: number | null;
  deal_count: number;
  candidate_count: number;
  contract_count: number;
}

export interface CompanyDetail extends CompanySummary {
  contacts: { id: string; name: string; email_address: string; phone: string | null; title: string | null }[];
  deal_ids: string[];
  candidate_ids: string[];
}

export interface DealSummary {
  id: string;
  title: string;
  company_id: string | null;
  location: string | null;
  unit_price_min: number | null;
  unit_price_max: number | null;
  status: string;
  duplicate_of_id: string | null;
  duplicate_relation: string | null;
}

export interface CandidateSummary {
  id: string;
  display_name: string;
  company_id: string | null;
  location_preference: string | null;
  unit_price_min: number | null;
  unit_price_max: number | null;
  status: string;
  duplicate_of_id: string | null;
  duplicate_relation: string | null;
}

export interface MeetingSummary {
  id: string;
  title: string;
  platform: string;
  join_url: string;
  starts_at: string | null;
  is_rescheduled: boolean;
  supersedes_meeting_id: string | null;
}

export interface MessageHit {
  id: string;
  subject: string;
  sender_address: string;
}

export interface AuditLogEntry {
  id: string;
  action: string;
  provider_used: string;
  rationale: string;
  data_sent_summary: string;
  anonymized: boolean;
  created_at: string;
}

export interface RelatedData {
  company: {
    id: string;
    name: string;
    evaluation: string | null;
    deal_count: number;
    candidate_count: number;
    last_contact_at: string | null;
  } | null;
  deals: {
    id: string;
    title: string;
    unit_price_min: number | null;
    unit_price_max: number | null;
    location: string | null;
    status: string;
  }[];
  candidates: {
    id: string;
    display_name: string;
    unit_price_min: number | null;
    unit_price_max: number | null;
    location_preference: string | null;
    status: string;
  }[];
  meetings: {
    id: string;
    title: string;
    platform: string;
    join_url: string;
    starts_at: string | null;
    is_rescheduled: boolean;
  }[];
}

export interface PromptVersion {
  id: string;
  version_number: number;
  system_prompt: string;
  user_prompt_template: string;
  notes: string;
}

export interface PromptTemplate {
  id: string;
  name: string;
  task: string;
  is_active: boolean;
  active_version_id: string | null;
  versions: PromptVersion[];
}

export interface RuleCondition {
  field: string;
  operator: string;
  value: string;
}

export interface RuleAction {
  type: string;
  params: Record<string, string>;
}

export interface Rule {
  id: string;
  name: string;
  is_active: boolean;
  priority: number;
  match_mode: string;
  conditions: RuleCondition[];
  actions: RuleAction[];
}

export interface DealNetworkNode {
  id: string;
  title: string;
  company_name: string;
  unit_price_min: number | null;
  unit_price_max: number | null;
  business_flow: string | null;
  relation: "root" | "exact" | "candidate";
}

export interface DealNetwork {
  root_id: string;
  nodes: DealNetworkNode[];
  company_count: number;
}

export interface DealMatch {
  candidate_id: string;
  candidate_name?: string;
  score: number;
  similarity?: number;
  rationale: string;
}

export interface CandidateMatch {
  deal_id: string;
  deal_title?: string;
  score: number;
  similarity?: number;
  rationale: string;
}

export interface PluginInfo {
  key: string;
  name: string;
  version: string;
  is_enabled: boolean;
}

export const api = {
  listMessages: (folder = "INBOX") => request<MessageSummary[]>(`/mail?folder=${encodeURIComponent(folder)}`),
  getMessage: (id: string) => request<MessageDetail>(`/mail/${id}`),
  getRelated: (id: string) => request<RelatedData>(`/mail/${id}/related`),
  getAuditLog: (id: string) => request<AuditLogEntry[]>(`/mail/${id}/audit-log`),
  updateMessage: (id: string, input: { is_read?: boolean; is_flagged?: boolean; folder?: string }) =>
    request<MessageSummary>(`/mail/${id}`, { method: "PATCH", body: JSON.stringify(input) }),
  registerBusinessCard: (attachmentId: string) =>
    request<BusinessCardContact>(`/mail/attachments/${attachmentId}/register-business-card`, { method: "POST" }),
  syncAccount: (accountId: string, folder = "INBOX") =>
    request<MessageSummary[]>(`/mail/accounts/${accountId}/sync?folder=${encodeURIComponent(folder)}`, {
      method: "POST",
    }),
  saveDraft: (input: { account_id: string; to: string[]; cc?: string[]; subject: string; body_text: string }) =>
    request<MessageSummary>(`/mail/draft`, { method: "POST", body: JSON.stringify(input) }),
  updateDraft: (
    id: string,
    input: { account_id: string; to: string[]; cc?: string[]; subject: string; body_text: string }
  ) => request<MessageSummary>(`/mail/draft/${id}`, { method: "PUT", body: JSON.stringify(input) }),
  sendReply: (
    messageId: string,
    input: { to: string[]; cc?: string[]; subject: string; body_text: string; in_reply_to?: string }
  ) => request<{ status: string }>(`/mail/${messageId}/send`, { method: "POST", body: JSON.stringify(input) }),

  analyze: (id: string) => request(`/ai/messages/${id}/analyze`, { method: "POST" }),
  classify: (id: string) => request(`/ai/messages/${id}/classify`, { method: "POST" }),
  summarize: (id: string, level: "3line" | "10line" | "detailed") =>
    request<{ level: string; summary: string }>(`/ai/messages/${id}/summarize`, {
      method: "POST",
      body: JSON.stringify({ level }),
    }),
  suggestReply: (id: string, tone: string) =>
    request<{ tone: string; draft: string }>(`/ai/messages/${id}/reply-suggestion`, {
      method: "POST",
      body: JSON.stringify({ tone }),
    }),
  replyTones: () => request<string[]>("/ai/reply-tones"),
  correctClassification: (id: string, correctedMailType: string, note = "") =>
    request<{ id: string; corrected_mail_type: string }>(`/ai/messages/${id}/correct-classification`, {
      method: "POST",
      body: JSON.stringify({ corrected_mail_type: correctedMailType, note }),
    }),
  chat: (question: string) =>
    request<{ answer: string; source_message_ids: string[] }>(`/chat`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
  dashboard: () => request<DashboardData>("/dashboard"),

  listAccounts: () => request<AccountSummary[]>("/accounts"),
  getAccountFolders: (accountId: string) => request<string[]>(`/accounts/${accountId}/folders`),
  createAccount: (input: AccountCreateInput) =>
    request<AccountSummary>("/accounts", { method: "POST", body: JSON.stringify(input) }),
  deleteAccount: (id: string) => request<{ status: string }>(`/accounts/${id}`, { method: "DELETE" }),

  getSettings: () => request<SettingsData>("/settings"),
  updateSettings: (input: SettingsUpdateInput) =>
    request<SettingsData>("/settings", { method: "PUT", body: JSON.stringify(input) }),

  listCompanies: () => request<CompanySummary[]>("/companies"),
  getCompany: (id: string) => request<CompanyDetail>(`/companies/${id}`),

  listDeals: () => request<DealSummary[]>("/deals"),
  listCandidates: () => request<CandidateSummary[]>("/candidates"),
  listMeetings: () => request<MeetingSummary[]>("/meetings"),

  search: (q: string) => request<MessageHit[]>(`/search?q=${encodeURIComponent(q)}`),
  searchNatural: (q: string) => request<MessageHit[]>(`/search/natural?q=${encodeURIComponent(q)}`),

  listPrompts: () => request<PromptTemplate[]>("/prompts"),
  createPrompt: (input: { name: string; task: string; system_prompt: string; user_prompt_template: string }) =>
    request<PromptTemplate>("/prompts", { method: "POST", body: JSON.stringify(input) }),
  addPromptVersion: (
    templateId: string,
    input: { system_prompt: string; user_prompt_template: string; notes?: string; activate?: boolean }
  ) => request<PromptVersion>(`/prompts/${templateId}/versions`, { method: "POST", body: JSON.stringify(input) }),

  listRules: () => request<Rule[]>("/rules"),
  createRule: (input: { name: string; priority?: number; match_mode?: string; conditions: RuleCondition[]; actions: RuleAction[] }) =>
    request<Rule>("/rules", { method: "POST", body: JSON.stringify(input) }),
  toggleRule: (id: string) => request<Rule>(`/rules/${id}/toggle`, { method: "PATCH" }),

  findDealDuplicates: (dealId: string) =>
    request<{ other_id: string; similarity: number; relation: string; reason: string }[]>(
      `/deals/${dealId}/find-duplicates`,
      { method: "POST" }
    ),
  getDealNetwork: (dealId: string) => request<DealNetwork>(`/deals/${dealId}/network`),
  findDealMatches: (dealId: string) => request<DealMatch[]>(`/deals/${dealId}/find-matches`, { method: "POST" }),
  findCandidateMatches: (candidateId: string) =>
    request<CandidateMatch[]>(`/candidates/${candidateId}/find-matches`, { method: "POST" }),

  listPlugins: () => request<PluginInfo[]>("/plugins"),
  updatePlugin: (key: string, input: { is_enabled: boolean; config?: Record<string, string> }) =>
    request<PluginInfo>(`/plugins/${key}`, { method: "PUT", body: JSON.stringify(input) }),
};
