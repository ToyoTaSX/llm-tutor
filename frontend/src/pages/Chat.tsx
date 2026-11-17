import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Plus, Square, MessageSquareDashed, AlertCircle, Globe, BookOpen } from "lucide-react";
import { api, fmtDate, HistoryItem, Mode, Page, post, QaFull, Source, WebSource } from "../api";
import { askStream } from "../sse";
import QaView from "../components/QaView";
import SourcesPanel, { citedLabels, lectureLabel, useSourcesCollapsed, WebState } from "../components/SourcesPanel";
import StarRating from "../components/StarRating";
import { useHealth } from "../components/Layout";

const MAX_LEN = 2000;

interface Live {
  question: string;
  answer: string;
  sources: Source[];
  mode: Mode;
  webSources: WebSource[] | null;
  webState: WebState;
  waiting: boolean;
  streaming: boolean;
  error: string | null;
  qaId: number | null;
  noAnswer: boolean;
  rating: number | null;
  timing: { t_search_ms: number | null; t_llm_ms: number | null; t_mcp_ms: number | null; t_total_ms: number | null } | null;
}

const MODES: { id: Mode; label: string; icon: typeof Globe; hint: string }[] = [
  { id: "course", label: "Только курс", icon: BookOpen, hint: "Ответ только по фрагментам лекций" },
  { id: "web", label: "Курс + интернет", icon: Globe, hint: "Лекции и до 3 результатов веб-поиска через MCP" },
];

function HistoryColumn({ selected, onNew }: { selected: number | null; onNew(): void }) {
  const nav = useNavigate();
  const q = useInfiniteQuery({
    queryKey: ["history"],
    queryFn: ({ pageParam }) => api<Page<HistoryItem>>(`/api/history?page=${pageParam}&limit=30`),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.page * last.limit < last.total ? last.page + 1 : undefined),
  });
  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-line bg-panel">
      <div className="p-3">
        <button onClick={onNew} className="btn w-full justify-center border border-line bg-panel2 text-fg hover:bg-hover">
          <Plus size={16} /> Новый вопрос
        </button>
      </div>
      <div className="label px-4 pb-2">История вопросов</div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {q.isLoading && <div className="px-2 text-xs text-dim">Загрузка…</div>}
        {!q.isLoading && items.length === 0 && <div className="px-2 text-xs text-dim">Пока нет вопросов</div>}
        {items.map((it) => (
          <button
            key={it.id}
            onClick={() => nav(`/qa/${it.id}`)}
            className={`mb-0.5 block w-full rounded-md px-2.5 py-2 text-left ${
              selected === it.id ? "bg-hover text-fg" : "text-muted hover:bg-panel2 hover:text-fg"
            }`}
          >
            <div className="line-clamp-2 text-[13px] leading-snug">{it.question}</div>
            <div className="mt-1 flex items-center gap-2 text-[11px] text-dim">
              <span className="font-mono">{fmtDate(it.created_at)}</span>
              {it.mode === "web" && <Globe size={11} className="text-muted" aria-label="Курс + интернет" />}
              {it.status === "error" && <AlertCircle size={11} className="text-bad" />}
              {it.rating && <StarRating value={it.rating} size={10} />}
            </div>
          </button>
        ))}
        {q.hasNextPage && (
          <button onClick={() => q.fetchNextPage()} className="btn-ghost w-full justify-center text-xs" disabled={q.isFetchingNextPage}>
            Показать ещё
          </button>
        )}
      </div>
    </aside>
  );
}

export default function Chat() {
  const { id } = useParams();
  const viewId = id ? Number(id) : null;
  const nav = useNavigate();
  const qc = useQueryClient();
  const { data: health } = useHealth();
  const [collapsed, setCollapsed] = useSourcesCollapsed();
  const [live, setLive] = useState<Live | null>(null);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<Mode>("course");
  const [active, setActive] = useState<string | null>(null);
  const [pulse, setPulse] = useState(0);
  const [ratingBusy, setRatingBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const saved = useQuery({
    queryKey: ["qa", viewId],
    queryFn: () => api<QaFull>(`/api/history/${viewId}`),
    enabled: viewId !== null,
  });

  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => setActive(null), [viewId]);

  // отображаемый вопрос: сохранённый из истории или текущий «живой»
  const view = useMemo(() => {
    if (viewId !== null) {
      const d = saved.data;
      if (!d) return null;
      return {
        question: d.question,
        answer: d.answer,
        sources: d.sources,
        mode: d.mode,
        webSources: d.mode === "web" ? d.web_sources : null,
        webState: (d.mode === "web" ? d.mcp_status : null) as WebState,
        createdAt: d.created_at,
        waiting: false,
        streaming: false,
        error: d.status === "error" ? "Ответ не был получен из-за ошибки модели" : null,
        qaId: d.id,
        noAnswer: d.no_answer,
        rating: d.rating,
        timing: { t_search_ms: d.t_search_ms, t_llm_ms: d.t_llm_ms, t_mcp_ms: d.t_mcp_ms, t_total_ms: d.t_total_ms },
      };
    }
    return live ? { ...live, createdAt: null } : null;
  }, [viewId, saved.data, live]);

  const cited = useMemo(() => citedLabels(view?.answer ?? ""), [view?.answer]);
  const labels = useMemo(
    () => new Set([...(view?.sources ?? []).map(lectureLabel), ...(view?.webSources ?? []).map((w) => w.label)]),
    [view?.sources, view?.webSources],
  );
  const busy = !!live && (live.waiting || live.streaming);
  const notReady =
    !health || health.llm !== "ready" || health.embedder !== "ready" ? true : health.documents_ready === 0;
  const notReadyText = !health
    ? ""
    : health.documents_ready === 0
      ? "Лекции ещё не загружены"
      : health.llm !== "ready" || health.embedder !== "ready"
        ? "Модель загружается…"
        : "";

  useEffect(() => {
    if (busy) scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [live?.answer, busy]);

  const send = () => {
    const q = input.trim();
    if (!q || q.length > MAX_LEN || busy || notReady) return;
    setInput("");
    setActive(null);
    if (viewId !== null) nav("/");
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLive({
      question: q,
      answer: "",
      sources: [],
      mode,
      webSources: null,
      webState: null,
      waiting: true,
      streaming: false,
      error: null,
      qaId: null,
      noAnswer: false,
      rating: null,
      timing: null,
    });
    const upd = (f: (l: Live) => Live) => setLive((l) => (l ? f(l) : l));
    askStream(
      q,
      mode,
      {
        onWebStatus: () => upd((l) => ({ ...l, webState: "searching" })),
        onSources: (sources) => upd((l) => ({ ...l, sources })),
        onWebSources: (d) => upd((l) => ({ ...l, webSources: d.results, webState: d.status })),
        onToken: (t) => upd((l) => ({ ...l, waiting: false, streaming: true, answer: l.answer + t })),
        onDone: (d) => {
          upd((l) => ({
            ...l,
            waiting: false,
            streaming: false,
            qaId: d.qa_id,
            noAnswer: d.no_answer,
            timing: { t_search_ms: d.t_search_ms, t_llm_ms: d.t_llm_ms, t_mcp_ms: d.t_mcp_ms, t_total_ms: d.t_total_ms },
          }));
          qc.invalidateQueries({ queryKey: ["history"] });
        },
        onError: (message) => {
          upd((l) => ({ ...l, waiting: false, streaming: false, error: message }));
          qc.invalidateQueries({ queryKey: ["history"] });
          qc.invalidateQueries({ queryKey: ["health"] });
        },
      },
      ctrl.signal,
    ).finally(() => {
      setLive((l) => (l && (l.waiting || l.streaming) ? { ...l, waiting: false, streaming: false, error: l.error ?? "Остановлено" } : l));
      setTimeout(() => inputRef.current?.focus(), 0);
    });
  };

  const stop = () => {
    abortRef.current?.abort();
    qc.invalidateQueries({ queryKey: ["history"] });
  };

  const rate = async (stars: number) => {
    const qaId = view?.qaId;
    if (!qaId) return;
    setRatingBusy(true);
    try {
      await post(`/api/qa/${qaId}/rating`, { stars });
      if (viewId === null) setLive((l) => (l ? { ...l, rating: stars } : l));
      qc.setQueryData<QaFull>(["qa", qaId], (d) => (d ? { ...d, rating: stars } : d));
      qc.invalidateQueries({ queryKey: ["history"] });
    } finally {
      setRatingBusy(false);
    }
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };

  const newQuestion = () => {
    if (busy) return;
    setLive(null);
    nav("/");
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const cite = (n: string) => {
    setCollapsed(false);
    setActive(n);
    setPulse((p) => p + 1);
  };

  return (
    <div className="flex h-full">
      <HistoryColumn selected={view?.qaId ?? null} onNew={newQuestion} />

      <section className="flex min-w-0 flex-1 flex-col">
        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-6 py-8">
            {viewId !== null && saved.isLoading && <div className="text-muted">Загрузка…</div>}
            {viewId !== null && saved.isError && <div className="text-bad">Вопрос не найден</div>}
            {view ? (
              <QaView
                question={view.question}
                answer={view.answer}
                createdAt={view.createdAt}
                waiting={view.waiting}
                streaming={view.streaming}
                error={view.error}
                noAnswer={view.noAnswer}
                labels={labels}
                mode={view.mode}
                webState={view.webState}
                rating={view.rating}
                onRate={view.qaId ? rate : undefined}
                ratingBusy={ratingBusy}
                onCite={cite}
                timing={view.timing}
              />
            ) : (
              viewId === null && (
                <div className="mt-24 flex flex-col items-center text-center text-muted">
                  <MessageSquareDashed size={40} className="mb-4 text-dim" />
                  <div className="text-base text-fg">Задайте вопрос по лекциям курса</div>
                  <div className="mt-1 max-w-md text-xs">
                    В режиме «Только курс» ассистент отвечает по материалам лекций, в режиме «Курс + интернет» — ещё и по
                    результатам веб-поиска. Справа видны источники ответа. После ответа поставьте ему оценку — это помогает
                    улучшать курс.
                  </div>
                </div>
              )
            )}
          </div>
        </div>

        <div className="border-t border-line bg-bg px-6 py-4">
          <div className="mx-auto max-w-3xl">
            <div className="mb-2 flex items-center gap-2">
              <div className="flex rounded-md border border-line bg-panel p-0.5" role="radiogroup" aria-label="Режим ответа">
                {MODES.map((m) => (
                  <button
                    key={m.id}
                    role="radio"
                    aria-checked={mode === m.id}
                    title={m.hint}
                    disabled={busy}
                    onClick={() => setMode(m.id)}
                    className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs disabled:opacity-50 ${
                      mode === m.id ? "bg-hover text-fg" : "text-muted hover:text-fg"
                    }`}
                  >
                    <m.icon size={13} /> {m.label}
                  </button>
                ))}
              </div>
              {mode === "web" && <span className="text-[11px] text-dim">во внешний поиск уходит только текст вопроса</span>}
            </div>
            <div className="flex items-end gap-2 rounded-xl border border-line bg-panel2 p-2 focus-within:border-accent">
              <textarea
                ref={inputRef}
                rows={Math.min(6, Math.max(1, input.split("\n").length))}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKey}
                placeholder={notReadyText || "Спросите что-нибудь по лекциям…"}
                className="max-h-40 min-h-[36px] flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] outline-none placeholder:text-dim"
                autoFocus
              />
              {busy ? (
                <button onClick={stop} title="Остановить" className="grid h-9 w-9 place-items-center rounded-lg bg-hover text-fg hover:bg-line">
                  <Square size={14} className="fill-current" />
                </button>
              ) : (
                <button
                  onClick={send}
                  title="Отправить"
                  disabled={!input.trim() || input.length > MAX_LEN || notReady}
                  className="grid h-9 w-9 place-items-center rounded-lg bg-accent text-white hover:bg-violet-500 disabled:opacity-30"
                >
                  <ArrowUp size={18} />
                </button>
              )}
            </div>
            <div className="mt-1.5 flex justify-between gap-2 font-mono text-[11px] text-dim">
              <span>Enter — отправить · Shift+Enter — новая строка</span>
              <span className={input.length > MAX_LEN ? "text-bad" : ""}>
                {input.length}/{MAX_LEN}
              </span>
            </div>
          </div>
        </div>
      </section>

      <SourcesPanel
        sources={view?.sources ?? []}
        webSources={view?.webSources ?? null}
        webState={view?.webState ?? null}
        cited={cited}
        active={active}
        pulse={pulse}
        collapsed={collapsed}
        onCollapse={setCollapsed}
        loading={!!view?.waiting}
      />
    </div>
  );
}
