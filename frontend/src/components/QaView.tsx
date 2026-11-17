import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertCircle, User, Sparkles, Clock, Globe, WifiOff } from "lucide-react";
import StarRating from "./StarRating";
import { fmtDate, McpStatus, Mode } from "../api";
import { CITE_RE, splitLabels } from "./SourcesPanel";

/** [L1], [W2, W3] → ссылки-кнопки, только для существующих источников; несуществующая метка остаётся текстом */
function linkCitations(text: string, labels: Set<string>): string {
  return text.replace(CITE_RE, (whole, list: string) => {
    const ls = splitLabels(list);
    if (ls.some((l) => !labels.has(l))) return whole;
    return ls.map((l) => `[${l}](#cite-${l})`).join("");
  });
}

export interface QaViewProps {
  question: string;
  answer: string;
  createdAt?: string | null;
  login?: string;
  streaming?: boolean;
  waiting?: boolean;
  error?: string | null;
  noAnswer?: boolean;
  labels: Set<string>; // метки найденных источников: L1…, W1…
  mode?: Mode;
  webState?: McpStatus | "searching" | null;
  rating: number | null;
  onRate?: (stars: number) => void;
  ratingBusy?: boolean;
  onCite(label: string): void;
  timing?: { t_search_ms: number | null; t_llm_ms: number | null; t_mcp_ms?: number | null; t_total_ms?: number | null } | null;
}

export default function QaView(p: QaViewProps) {
  const done = !p.streaming && !p.waiting;
  return (
    <div className="space-y-5">
      <div className="flex gap-3">
        <div className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-hover text-muted">
          <User size={15} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="label mb-1">
            {p.login ?? "Вы"} {p.createdAt && <span className="normal-case tracking-normal">· {fmtDate(p.createdAt)}</span>}
          </div>
          <div className="whitespace-pre-wrap text-[15px] leading-relaxed">{p.question}</div>
        </div>
      </div>

      <div className="flex gap-3">
        <div className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-accent-soft text-accent-fg">
          <Sparkles size={15} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="label mb-1 flex items-center gap-2">
            Ассистент
            {p.mode === "web" && (
              <span className="flex items-center gap-1 rounded bg-hover px-1.5 normal-case tracking-normal text-muted">
                <Globe size={11} /> курс + интернет
              </span>
            )}
          </div>
          {(p.webState === "timeout" || p.webState === "error") && (
            <div className="mb-2 flex items-center gap-2 rounded-md border border-warn/30 bg-warn/10 px-3 py-2 text-sm text-warn">
              <WifiOff size={15} /> Интернет-поиск временно недоступен. Ответ построен только по материалам курса.
            </div>
          )}
          {p.webState === "empty" && !p.waiting && (
            <div className="mb-2 text-xs text-dim">В интернете ничего не найдено — ответ по материалам курса.</div>
          )}
          {p.waiting && !p.answer && (
            <div className="cursor-blink text-muted">{p.webState === "searching" ? "Ищу дополнительные источники…" : "Ищу ответ в лекциях"}</div>
          )}
          {p.answer && (
            <div className={`md text-[15px] ${p.streaming ? "cursor-blink" : ""}`}>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ href, children }) => {
                    const m = href?.match(/^#cite-([LW]\d+)$/);
                    if (m) {
                      return (
                        <button
                          type="button"
                          onClick={() => p.onCite(m[1])}
                          className="mx-0.5 rounded bg-accent-soft px-1 font-mono text-xs text-accent-fg hover:bg-accent hover:text-white"
                        >
                          {m[1]}
                        </button>
                      );
                    }
                    return (
                      <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-accent-fg underline">
                        {children}
                      </a>
                    );
                  },
                }}
              >
                {linkCitations(p.answer, p.labels)}
              </ReactMarkdown>
            </div>
          )}
          {p.error && (
            <div className="mt-2 flex items-center gap-2 rounded-md border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad">
              <AlertCircle size={16} /> {p.error}
            </div>
          )}
          {done && !p.error && p.answer && (
            <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-3">
              {p.onRate ? (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted">{p.rating ? "Ваша оценка:" : "Оцените ответ:"}</span>
                  <StarRating value={p.rating} onRate={p.onRate} busy={p.ratingBusy} />
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted">Оценка:</span>
                  {p.rating ? <StarRating value={p.rating} size={15} /> : <span className="text-xs text-dim">нет</span>}
                </div>
              )}
              {p.noAnswer && <span className="rounded bg-warn/10 px-2 py-0.5 text-xs text-warn">тема не разбиралась</span>}
              {p.timing && p.timing.t_llm_ms != null && (
                <span className="ml-auto flex items-center gap-1 font-mono text-[11px] text-dim">
                  <Clock size={12} />
                  поиск {p.timing.t_search_ms} мс
                  {p.timing.t_mcp_ms != null && <> · веб {(p.timing.t_mcp_ms / 1000).toFixed(1)} с</>} · ответ{" "}
                  {(p.timing.t_llm_ms / 1000).toFixed(1)} с
                  {p.timing.t_total_ms != null && <> · всего {(p.timing.t_total_ms / 1000).toFixed(1)} с</>}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
