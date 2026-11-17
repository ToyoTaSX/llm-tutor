// SSE поверх fetch: EventSource умеет только GET, а вопрос отправляется POST-ом (design D8)
import { ApiError, McpStatus, Mode, Source, WebSource } from "./api";

export interface DoneInfo {
  qa_id: number;
  no_answer: boolean;
  mode: Mode;
  t_search_ms: number | null;
  t_llm_ms: number | null;
  t_mcp_ms: number | null;
  t_total_ms: number | null;
}

export interface AskHandlers {
  onWebStatus?(d: { state: "searching" }): void;
  onSources(sources: Source[]): void;
  onWebSources?(d: { status: McpStatus; query: string; results: WebSource[]; t_mcp_ms: number | null }): void;
  onToken(t: string): void;
  onDone(d: DoneInfo): void;
  onError(message: string): void;
}

export async function askStream(question: string, mode: Mode, h: AskHandlers, signal: AbortSignal): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ question, mode }),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    h.onError("Сервер недоступен");
    return;
  }
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* ignore */
    }
    if (res.status === 401) window.dispatchEvent(new Event("unauthorized"));
    h.onError(new ApiError(res.status, detail).message);
    return;
  }
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let finished = false;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let i: number;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, i);
        buf = buf.slice(i + 2);
        let event = "message";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7);
          else if (line.startsWith("data: ")) data += line.slice(6);
        }
        if (!data) continue;
        const payload = JSON.parse(data);
        if (event === "web_status") h.onWebStatus?.(payload);
        else if (event === "sources") h.onSources(payload);
        else if (event === "web_sources") h.onWebSources?.(payload);
        else if (event === "token") h.onToken(payload.t);
        else if (event === "done") {
          finished = true;
          h.onDone(payload);
        } else if (event === "error") {
          finished = true;
          h.onError(payload.message);
        }
      }
    }
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    finished = true;
    h.onError("Соединение прервано");
  }
  if (!finished && !signal.aborted) h.onError("Ответ оборвался");
}
