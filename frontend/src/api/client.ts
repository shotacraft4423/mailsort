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
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${res.status}`);
  }
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

export interface MessageDetail extends MessageSummary {
  body_text: string;
  body_html: string;
  classification: Record<string, unknown> | null;
  extraction: Record<string, unknown> | null;
  summary_3line: string | null;
}

export interface DashboardData {
  deals_today: number;
  candidates_today: number;
  reply_required_open: number;
  open_deal_count: number;
  open_candidate_count: number;
  top_companies: { name: string; deal_count: number }[];
}

export const api = {
  listMessages: (folder = "INBOX") => request<MessageSummary[]>(`/mail?folder=${encodeURIComponent(folder)}`),
  getMessage: (id: string) => request<MessageDetail>(`/mail/${id}`),
  classify: (id: string) => request(`/ai/messages/${id}/classify`, { method: "POST" }),
  summarize: (id: string, level: "3line" | "10line" | "detailed") =>
    request(`/ai/messages/${id}/summarize`, { method: "POST", body: JSON.stringify({ level }) }),
  suggestReply: (id: string, tone: string) =>
    request<{ tone: string; draft: string }>(`/ai/messages/${id}/reply-suggestion`, {
      method: "POST",
      body: JSON.stringify({ tone }),
    }),
  chat: (question: string) =>
    request<{ answer: string; source_message_ids: string[] }>(`/chat`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
  dashboard: () => request<DashboardData>("/dashboard"),
};
