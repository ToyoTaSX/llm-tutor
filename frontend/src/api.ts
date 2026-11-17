// Клиент API: same-origin, сессия в httpOnly cookie

export type Role = "student" | "lecturer";
export interface Me {
  id: number;
  login: string;
  role: Role;
}

export type Mode = "course" | "web";
export type McpStatus = "ok" | "empty" | "timeout" | "error";

/** Фрагмент лекции, метка [L1]… */
export interface Source {
  n: number;
  label?: string;
  doc_id: number;
  doc_title: string;
  chunk_no: number;
  score: number;
  rank: number;
  text: string;
}

/** Результат веб-поиска через MCP, метка [W1]…; URL получен от инструмента, а не от модели */
export interface WebSource {
  label: string;
  title: string;
  url: string;
  domain: string;
  content: string;
  synthetic?: boolean;
}

export interface QaFull {
  id: number;
  created_at: string;
  question: string;
  answer: string;
  status: "ok" | "error";
  no_answer: boolean;
  sources: Source[];
  rating: number | null;
  t_search_ms: number | null;
  t_llm_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  mode: Mode;
  web_query: string | null;
  web_sources: WebSource[];
  mcp_status: McpStatus | null;
  mcp_error: string | null;
  t_mcp_ms: number | null;
  t_total_ms: number | null;
  login?: string;
}

export interface HistoryItem {
  id: number;
  created_at: string;
  question: string;
  rating: number | null;
  status: "ok" | "error";
  no_answer: boolean;
  mode: Mode;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
}

export interface Health {
  llm: "ready" | "loading" | "down";
  qdrant: "ready" | "down";
  embedder: "ready" | "loading" | "error";
  embedder_error: string | null;
  gpu: string | null;
  model: string;
  documents_ready: number;
  documents_indexing: number;
}

export interface Doc {
  id: number;
  title: string;
  filename: string;
  status: "indexing" | "ready" | "error";
  error: string | null;
  chunks_count: number;
  chars: number;
  uploaded_by: string | null;
  created_at: string;
  indexed_at: string | null;
}

export interface Summary {
  period: string;
  questions: number;
  active_users: number;
  avg_rating: number | null;
  rated_count: number;
  rated_share: number | null;
  no_answer_share: number | null;
  errors: number;
  avg_time_ms: number | null;
  histogram: Record<string, number>;
  daily: { date: string; count: number }[];
}

export type LogItem = Omit<QaFull, "sources" | "web_sources" | "mcp_error"> & { login: string };

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(errorText(detail) || `Ошибка ${status}`);
  }
  get field(): string | undefined {
    const d = this.detail as { field?: string } | null;
    return d && typeof d === "object" ? d.field : undefined;
  }
}

export function errorText(detail: unknown): string {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? "").join("; ");
  if (typeof detail === "object" && "message" in (detail as object)) return String((detail as { message: string }).message);
  return "";
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers, credentials: "include" });
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* пустое тело */
    }
    if (res.status === 401 && !path.startsWith("/api/auth/")) window.dispatchEvent(new Event("unauthorized"));
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const tzOffset = () => -new Date().getTimezoneOffset();

export function fmtDate(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: withTime ? undefined : "numeric",
    hour: withTime ? "2-digit" : undefined,
    minute: withTime ? "2-digit" : undefined,
  });
}
