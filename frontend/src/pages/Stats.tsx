import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Search, X, AlertCircle, Globe } from "lucide-react";
import { api, fmtDate, LogItem, Page, QaFull, Summary, tzOffset } from "../api";
import StarRating from "../components/StarRating";
import QaView from "../components/QaView";
import SourcesPanel, { citedLabels, lectureLabel, safeHref, WebState } from "../components/SourcesPanel";

const PERIODS = [
  { id: "7d", label: "7 дней" },
  { id: "30d", label: "30 дней" },
  { id: "all", label: "Всё время" },
];
const FILTERS = [
  { id: "", label: "Все" },
  { id: "low", label: "Оценка ≤ 2" },
  { id: "unrated", label: "Без оценки" },
  { id: "no_answer", label: "Тема не разбиралась" },
];
const MODE_FILTERS = [
  { id: "", label: "Все режимы" },
  { id: "course", label: "Только курс" },
  { id: "web", label: "Курс + интернет" },
];
const MCP_STATUS_TEXT: Record<string, string> = {
  ok: "успех",
  empty: "пустой результат",
  timeout: "тайм-аут",
  error: "ошибка",
};
const STAR_COLORS = ["#f87171", "#fb923c", "#fbbf24", "#a3e635", "#34d399"];
const NO_DATA = "нет данных";

function Card({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card p-4">
      <div className="label">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${value === NO_DATA ? "text-base text-dim" : ""}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-dim">{hint}</div>}
    </div>
  );
}

const pct = (v: number | null) => (v === null ? NO_DATA : `${Math.round(v * 100)}%`);

const tooltipStyle = {
  contentStyle: { background: "#26262a", border: "1px solid #323238", borderRadius: 6, fontSize: 12 },
  labelStyle: { color: "#9a9aa3" },
  cursor: { fill: "#ffffff08" },
};

function QaModal({ id, onClose }: { id: number; onClose(): void }) {
  const q = useQuery({ queryKey: ["log", id], queryFn: () => api<QaFull>(`/api/stats/log/${id}`) });
  const [active, setActive] = useState<string | null>(null);
  const [pulse, setPulse] = useState(0);
  const d = q.data;
  const labels = new Set([...(d?.sources ?? []).map(lectureLabel), ...(d?.web_sources ?? []).map((w) => w.label)]);
  const sec = (ms: number | null) => (ms == null ? "—" : `${(ms / 1000).toFixed(1)} с`);
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/60 p-6" onClick={onClose}>
      <div className="card flex h-[85vh] w-full max-w-6xl overflow-hidden shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex h-11 shrink-0 items-center border-b border-line px-4">
            <span className="label">Запись журнала #{id}</span>
            <div className="flex-1" />
            <button className="btn-ghost px-1.5" onClick={onClose}>
              <X size={16} />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-6">
            {d && (
              <QaView
                question={d.question}
                answer={d.answer}
                createdAt={d.created_at}
                login={d.login}
                error={d.status === "error" ? "Ответ не был получен из-за ошибки модели" : null}
                noAnswer={d.no_answer}
                labels={labels}
                mode={d.mode}
                webState={d.mode === "web" ? d.mcp_status : null}
                rating={d.rating}
                onCite={(n) => {
                  setActive(n);
                  setPulse((p) => p + 1);
                }}
                timing={{ t_search_ms: d.t_search_ms, t_llm_ms: d.t_llm_ms, t_mcp_ms: d.t_mcp_ms, t_total_ms: d.t_total_ms }}
              />
            )}
            {d && (
              <div className="mt-6 rounded-lg border border-line bg-panel2 p-4 text-xs">
                <div className="label mb-2 flex items-center gap-1.5">
                  {d.mode === "web" && <Globe size={12} />} Режим и время
                </div>
                <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
                  <dt className="text-dim">Режим</dt>
                  <dd>{d.mode === "web" ? "Курс + интернет" : "Только курс"}</dd>
                  {d.mode === "web" && (
                    <>
                      <dt className="text-dim">Поисковый запрос</dt>
                      <dd className="break-words">{d.web_query ?? "—"}</dd>
                      <dt className="text-dim">Статус MCP</dt>
                      <dd className={d.mcp_status === "ok" ? "" : "text-warn"}>
                        {d.mcp_status ? MCP_STATUS_TEXT[d.mcp_status] ?? d.mcp_status : "—"}
                        {d.mcp_error && <span className="ml-2 text-dim">({d.mcp_error})</span>}
                      </dd>
                      <dt className="text-dim">Длительность MCP</dt>
                      <dd className="font-mono">{sec(d.t_mcp_ms)}</dd>
                    </>
                  )}
                  <dt className="text-dim">Полное время ответа</dt>
                  <dd className="font-mono">{sec(d.t_total_ms)}</dd>
                  {d.mode === "web" && (
                    <>
                      <dt className="text-dim">Полученные URL</dt>
                      <dd>
                        {d.web_sources.length === 0 && "—"}
                        <ul className="space-y-0.5">
                          {d.web_sources.map((w) => {
                            const href = safeHref(w.url);
                            return (
                              <li key={w.label} className="break-all">
                                <span className="mr-1 font-mono text-dim">[{w.label}]</span>
                                {href ? (
                                  <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-accent-fg hover:underline">
                                    {w.url}
                                  </a>
                                ) : (
                                  w.url
                                )}
                                {w.synthetic && <span className="ml-1 text-warn">(синтетический)</span>}
                              </li>
                            );
                          })}
                        </ul>
                      </dd>
                    </>
                  )}
                </dl>
              </div>
            )}
          </div>
        </div>
        <div className="flex w-96 shrink-0 flex-col border-l border-line bg-panel">
          <SourcesPanel
            sources={d?.sources ?? []}
            webSources={d?.mode === "web" ? d.web_sources : null}
            webState={(d?.mode === "web" ? d.mcp_status : null) as WebState}
            cited={citedLabels(d?.answer ?? "")}
            active={active}
            pulse={pulse}
            collapsed={false}
            onCollapse={() => {}}
            embedded
          />
        </div>
      </div>
    </div>
  );
}

export default function Stats() {
  const [period, setPeriod] = useState("7d");
  const [filter, setFilter] = useState("");
  const [mode, setMode] = useState("");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      setQ(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const summary = useQuery({
    queryKey: ["summary", period],
    queryFn: () => api<Summary>(`/api/stats/summary?period=${period}&tz_offset=${tzOffset()}`),
    placeholderData: keepPreviousData,
  });
  const log = useQuery({
    queryKey: ["logList", filter, mode, q, page],
    queryFn: () =>
      api<Page<LogItem>>(`/api/stats/log?filter=${filter}&mode=${mode}&q=${encodeURIComponent(q)}&page=${page}&limit=20`),
    placeholderData: keepPreviousData,
  });

  const s = summary.data;
  const hist = useMemo(() => (s ? [1, 2, 3, 4, 5].map((i) => ({ stars: `${i}★`, count: s.histogram[String(i)] ?? 0 })) : []), [s]);
  const daily = useMemo(
    () => (s ? s.daily.map((d) => ({ ...d, label: new Date(d.date + "T00:00").toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }) })) : []),
    [s],
  );
  const pages = log.data ? Math.max(1, Math.ceil(log.data.total / log.data.limit)) : 1;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <h1 className="text-lg font-semibold">Статистика</h1>
            <p className="text-xs text-muted">Как студенты пользуются ассистентом и насколько довольны ответами</p>
          </div>
          <div className="flex-1" />
          <div className="flex rounded-md border border-line bg-panel p-0.5">
            {PERIODS.map((p) => (
              <button
                key={p.id}
                onClick={() => setPeriod(p.id)}
                className={`rounded px-3 py-1 text-xs ${period === p.id ? "bg-hover text-fg" : "text-muted hover:text-fg"}`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
          <Card label="Вопросов" value={s ? String(s.questions) : "…"} hint={s && s.errors ? `ошибок: ${s.errors}` : undefined} />
          <Card label="Активных студентов" value={s ? String(s.active_users) : "…"} />
          <Card
            label="Средняя оценка"
            value={s ? (s.avg_rating === null ? NO_DATA : `${s.avg_rating.toFixed(2)} ★`) : "…"}
            hint={s && s.rated_count ? `по ${s.rated_count} оценкам` : undefined}
          />
          <Card label="Оценено ответов" value={s ? pct(s.rated_share) : "…"} />
          <Card label="«Тема не разбиралась»" value={s ? pct(s.no_answer_share) : "…"} />
          <Card label="Среднее время ответа" value={s ? (s.avg_time_ms === null ? NO_DATA : `${(s.avg_time_ms / 1000).toFixed(1)} с`) : "…"} />
        </div>

        <div className="grid gap-3 lg:grid-cols-3">
          <div className="card p-4">
            <div className="label mb-3">Распределение оценок</div>
            {s && s.rated_count === 0 ? (
              <div className="grid h-48 place-items-center text-xs text-dim">{NO_DATA}</div>
            ) : (
              <ResponsiveContainer width="100%" height={192}>
                <BarChart data={hist}>
                  <CartesianGrid stroke="#323238" vertical={false} />
                  <XAxis dataKey="stars" stroke="#6b6b74" fontSize={12} tickLine={false} />
                  <YAxis allowDecimals={false} stroke="#6b6b74" fontSize={11} width={28} tickLine={false} />
                  <Tooltip {...tooltipStyle} formatter={(v) => [v, "ответов"]} />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                    {hist.map((_, i) => (
                      <Cell key={i} fill={STAR_COLORS[i]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="card p-4 lg:col-span-2">
            <div className="label mb-3">Вопросов по дням</div>
            {s && s.questions === 0 ? (
              <div className="grid h-48 place-items-center text-xs text-dim">{NO_DATA}</div>
            ) : (
              <ResponsiveContainer width="100%" height={192}>
                <BarChart data={daily}>
                  <CartesianGrid stroke="#323238" vertical={false} />
                  <XAxis dataKey="label" stroke="#6b6b74" fontSize={11} tickLine={false} minTickGap={12} />
                  <YAxis allowDecimals={false} stroke="#6b6b74" fontSize={11} width={28} tickLine={false} />
                  <Tooltip {...tooltipStyle} formatter={(v) => [v, "вопросов"]} />
                  <Bar dataKey="count" fill="#8b5cf6" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="card overflow-hidden">
          <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
            <span className="label mr-2">Журнал</span>
            {FILTERS.map((f) => (
              <button
                key={f.id}
                className={filter === f.id ? "chip-active" : "chip"}
                onClick={() => {
                  setFilter(f.id);
                  setPage(1);
                }}
              >
                {f.label}
              </button>
            ))}
            <select
              className="input w-auto py-1 text-xs"
              value={mode}
              aria-label="Фильтр по режиму"
              onChange={(e) => {
                setMode(e.target.value);
                setPage(1);
              }}
            >
              {MODE_FILTERS.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
            <div className="flex-1" />
            <div className="relative w-64">
              <Search size={14} className="absolute left-2.5 top-2.5 text-dim" />
              <input className="input py-1.5 pl-8" placeholder="Поиск по вопросам" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
          </div>
          <table className="w-full table-fixed text-left text-sm">
            <thead className="border-b border-line bg-panel2">
              <tr className="label">
                <th className="w-32 px-4 py-2.5 font-normal">Дата</th>
                <th className="w-28 px-4 py-2.5 font-normal">Логин</th>
                <th className="px-4 py-2.5 font-normal">Вопрос</th>
                <th className="px-4 py-2.5 font-normal">Ответ</th>
                <th className="w-28 px-4 py-2.5 font-normal">Оценка</th>
              </tr>
            </thead>
            <tbody>
              {log.data?.items.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-muted">
                    Записей нет
                  </td>
                </tr>
              )}
              {log.data?.items.map((r) => (
                <tr key={r.id} onClick={() => setOpen(r.id)} className="cursor-pointer border-b border-line align-top last:border-0 hover:bg-panel2">
                  <td className="px-4 py-2.5 font-mono text-xs text-muted">{fmtDate(r.created_at)}</td>
                  <td className="truncate px-4 py-2.5 text-xs">{r.login}</td>
                  <td className="px-4 py-2.5">
                    <div className="line-clamp-2">{r.question}</div>
                    {r.mode === "web" && (
                      <span className={`mt-1 inline-flex items-center gap-1 rounded px-1.5 text-[11px] ${r.mcp_status === "ok" ? "bg-hover text-muted" : "bg-warn/10 text-warn"}`}>
                        <Globe size={10} /> курс + интернет{r.mcp_status && r.mcp_status !== "ok" ? ` · ${MCP_STATUS_TEXT[r.mcp_status]}` : ""}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-muted">
                    {r.status === "error" ? (
                      <span className="flex items-center gap-1 text-bad">
                        <AlertCircle size={12} /> ошибка модели
                      </span>
                    ) : (
                      <>
                        {r.no_answer && <span className="mr-1 rounded bg-warn/10 px-1.5 text-warn">нет в курсе</span>}
                        <span className="line-clamp-2">{r.answer}</span>
                      </>
                    )}
                  </td>
                  <td className="px-4 py-2.5">{r.rating ? <StarRating value={r.rating} size={12} /> : <span className="text-xs text-dim">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {log.data && log.data.total > 0 && (
            <div className="flex items-center gap-3 border-t border-line px-4 py-2 text-xs text-muted">
              <span>всего: {log.data.total}</span>
              <div className="flex-1" />
              <button className="btn-ghost py-1" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                ←
              </button>
              <span className="font-mono">
                {page} / {pages}
              </span>
              <button className="btn-ghost py-1" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                →
              </button>
            </div>
          )}
        </div>
      </div>
      {open !== null && <QaModal id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
