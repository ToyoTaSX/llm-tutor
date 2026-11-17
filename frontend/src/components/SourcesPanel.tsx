import { ReactNode, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, PanelRightClose, PanelRightOpen, BookOpen, Globe, ExternalLink, FlaskConical } from "lucide-react";
import { McpStatus, Source, WebSource } from "../api";

const KEY = "sourcesCollapsed";

export function useSourcesCollapsed(): [boolean, (v: boolean) => void] {
  const [v, setV] = useState(() => {
    try {
      return localStorage.getItem(KEY) === "1";
    } catch {
      return false;
    }
  });
  const set = (x: boolean) => {
    setV(x);
    try {
      localStorage.setItem(KEY, x ? "1" : "0");
    } catch {
      /* приватный режим */
    }
  };
  return [v, set];
}

// Qwen2.5-3B иногда пишет кириллическую «Л» вместо L ([Л1]) — принимаем её как L
export const CITE_RE = /\[\s*([LWЛ]\d+(?:\s*[,;]\s*[LWЛ]?\d+)*)\s*\]/gi;

/** Разбор содержимого метки: "L1, 2; W3" → ["L1", "L2", "W3"] (буква наследуется) */
export function splitLabels(list: string): string[] {
  let prefix = "L";
  return list.split(/[,;]/).map((part) => {
    const p = part.trim().toUpperCase().replace("Л", "L");
    if (p[0] === "L" || p[0] === "W") {
      prefix = p[0];
      return `${prefix}${Number(p.slice(1))}`;
    }
    return `${prefix}${Number(p)}`;
  });
}

/** Метки источников, на которые ссылается ответ: [L1], [W2], [L1, L2], [L1][W3] */
export function citedLabels(answer: string): Set<string> {
  const out = new Set<string>();
  for (const m of answer.matchAll(CITE_RE)) for (const l of splitLabels(m[1])) out.add(l);
  return out;
}

export const lectureLabel = (s: Source) => s.label ?? `L${s.n}`;

/** Ссылка открывается только по клику и только для http/https */
export function safeHref(url: string): string | null {
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

export type WebState = McpStatus | "searching" | null;

interface Props {
  sources: Source[];
  webSources?: WebSource[] | null; // null/undefined — режим «Только курс», секция «Источники в интернете» не показывается
  webState?: WebState;
  cited: Set<string>;
  active: string | null;
  pulse: number; // меняется при каждом клике по ссылке, чтобы повторно подсветить
  collapsed: boolean;
  onCollapse(v: boolean): void;
  loading?: boolean;
  embedded?: boolean; // внутри модального окна лектора: без сворачивания
}

function useActiveScroll(active: boolean, setOpen: (v: boolean) => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (active) {
      ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      setOpen(true);
    }
  }, [active, setOpen]);
  return ref;
}

function cardClass(active: boolean, dimmed: boolean) {
  return `rounded-lg border p-3 transition-all ${active ? "border-accent bg-accent-soft ring-1 ring-accent" : "border-line bg-panel2"} ${
    dimmed ? "opacity-45 hover:opacity-90" : ""
  }`;
}

function LabelBadge({ label, cited }: { label: string; cited: boolean }) {
  return (
    <span className={`mt-0.5 shrink-0 rounded px-1.5 font-mono text-xs ${cited ? "bg-accent text-white" : "bg-hover text-muted"}`}>{label}</span>
  );
}

function SourceCard({ s, cited, active, maxScore, anyCited }: { s: Source; cited: boolean; active: boolean; maxScore: number; anyCited: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useActiveScroll(active, setOpen);
  const rel = maxScore > 0 ? s.score / maxScore : 0;
  return (
    <div ref={ref} className={cardClass(active, anyCited && !cited)}>
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-start gap-2 text-left">
        <LabelBadge label={lectureLabel(s)} cited={cited} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-medium text-fg" title={s.doc_title}>
            {s.doc_title}
          </div>
          <div className="mt-0.5 flex items-center gap-2 font-mono text-[11px] text-dim">
            <span>фрагмент #{s.chunk_no}</span>
            <span className="flex items-center gap-1" title={`RRF score: ${s.score.toFixed(4)} · ранг ${s.rank}`}>
              <span className="inline-block h-1.5 w-14 overflow-hidden rounded bg-hover">
                <span className="block h-full rounded bg-accent" style={{ width: `${Math.max(6, rel * 100)}%` }} />
              </span>
              ранг {s.rank}
            </span>
          </div>
        </div>
        {open ? <ChevronDown size={14} className="mt-1 text-dim" /> : <ChevronRight size={14} className="mt-1 text-dim" />}
      </button>
      <p className={`mt-2 whitespace-pre-wrap text-xs leading-relaxed text-muted ${open ? "" : "line-clamp-3"}`}>{s.text}</p>
    </div>
  );
}

function WebCard({ w, cited, active, anyCited }: { w: WebSource; cited: boolean; active: boolean; anyCited: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useActiveScroll(active, setOpen);
  const href = safeHref(w.url);
  return (
    <div ref={ref} className={cardClass(active, anyCited && !cited)}>
      <div className="flex items-start gap-2">
        <LabelBadge label={w.label} cited={cited} />
        <div className="min-w-0 flex-1">
          {/* только текстовые узлы: HTML из выдержек не исполняется */}
          <div className="line-clamp-2 text-xs font-medium text-fg" title={w.title}>
            {w.title}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 font-mono text-[11px] text-dim">
            <span>{w.domain}</span>
            {w.synthetic && (
              <span className="flex items-center gap-1 rounded bg-warn/10 px-1 text-warn" title="Синтетический результат для проверки на инъекцию">
                <FlaskConical size={10} /> тест
              </span>
            )}
          </div>
          {href ? (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="mt-1 flex items-center gap-1 break-all text-[11px] text-accent-fg hover:underline"
            >
              <ExternalLink size={11} className="shrink-0" />
              {w.url}
            </a>
          ) : (
            <div className="mt-1 break-all text-[11px] text-dim">{w.url}</div>
          )}
        </div>
        <button type="button" onClick={() => setOpen(!open)} className="text-dim" title={open ? "Свернуть" : "Показать выдержку"}>
          {open ? <ChevronDown size={14} className="mt-1" /> : <ChevronRight size={14} className="mt-1" />}
        </button>
      </div>
      <p className={`mt-2 whitespace-pre-wrap text-xs leading-relaxed text-muted ${open ? "" : "line-clamp-3"}`}>{w.content}</p>
    </div>
  );
}

const WEB_STATE_TEXT: Record<string, string> = {
  searching: "Ищу дополнительные источники…",
  empty: "В интернете ничего не найдено.",
  timeout: "Интернет-поиск временно недоступен (тайм-аут).",
  error: "Интернет-поиск временно недоступен.",
};

function SectionTitle({ icon, title, count }: { icon: ReactNode; title: string; count: number }) {
  return (
    <div className="flex items-center gap-1.5 px-0.5 pb-1 pt-2 first:pt-0">
      {icon}
      <span className="label">
        {title} {count > 0 && `(${count})`}
      </span>
    </div>
  );
}

export default function SourcesPanel({ sources, webSources, webState, cited, active, pulse, collapsed, onCollapse, loading, embedded }: Props) {
  const webMode = webSources != null || webState === "searching";
  const web = webSources ?? [];
  const total = sources.length + web.length;
  if (collapsed && !embedded) {
    return (
      <aside className="flex w-10 shrink-0 flex-col items-center border-l border-line bg-panel py-3">
        <button title="Показать источники" onClick={() => onCollapse(false)} className="btn-ghost px-1.5">
          <PanelRightOpen size={18} />
        </button>
        {total > 0 && <span className="mt-2 font-mono text-xs text-dim">{total}</span>}
      </aside>
    );
  }
  const maxScore = Math.max(0, ...sources.map((s) => s.score));
  const anyCited = sources.some((s) => cited.has(lectureLabel(s))) || web.some((w) => cited.has(w.label));
  return (
    <aside className={`flex min-h-0 flex-col ${embedded ? "" : "w-80 shrink-0 border-l border-line bg-panel xl:w-96"}`}>
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-line px-3">
        <BookOpen size={15} className="text-accent-fg" />
        <span className="label">Источники {total > 0 && `(${total})`}</span>
        <div className="flex-1" />
        {!embedded && (
          <button title="Свернуть" onClick={() => onCollapse(true)} className="btn-ghost px-1.5">
            <PanelRightClose size={16} />
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {webMode && <SectionTitle icon={<BookOpen size={13} className="text-dim" />} title="Материалы курса" count={sources.length} />}
        {loading && sources.length === 0 && <div className="text-xs text-dim">Ищу фрагменты лекций…</div>}
        {!loading && sources.length === 0 && (
          <div className="text-xs text-dim">Здесь появятся фрагменты лекций, на которых основан ответ.</div>
        )}
        {sources.map((s) => {
          const l = lectureLabel(s);
          return (
            <SourceCard key={`${l}-${l === active ? pulse : 0}`} s={s} cited={cited.has(l)} active={l === active} maxScore={maxScore} anyCited={anyCited} />
          );
        })}
        {webMode && (
          <>
            <SectionTitle icon={<Globe size={13} className="text-dim" />} title="Источники в интернете" count={web.length} />
            {webState && webState !== "ok" && WEB_STATE_TEXT[webState] && (
              <div
                className={`text-xs ${webState === "timeout" || webState === "error" ? "rounded-md border border-warn/30 bg-warn/10 px-2 py-1.5 text-warn" : "text-dim"}`}
              >
                {WEB_STATE_TEXT[webState]}
              </div>
            )}
            {web.map((w) => (
              <WebCard key={`${w.label}-${w.label === active ? pulse : 0}`} w={w} cited={cited.has(w.label)} active={w.label === active} anyCited={anyCited} />
            ))}
          </>
        )}
      </div>
    </aside>
  );
}
