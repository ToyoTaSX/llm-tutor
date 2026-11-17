import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, FileText, LogOut, MessageSquare, Cpu, Loader2, AlertTriangle } from "lucide-react";
import { api, Health } from "../api";
import { useAuth } from "../auth";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => api<Health>("/api/health"),
    refetchInterval: (q) => (q.state.data?.llm === "ready" && q.state.data?.embedder !== "loading" ? 15000 : 3000),
  });
}

function RailLink({ to, icon: Icon, label }: { to: string; icon: typeof MessageSquare; label: string }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      title={label}
      className={({ isActive }) =>
        `group relative grid h-10 w-10 place-items-center rounded-lg transition-colors ${
          isActive ? "bg-accent-soft text-accent-fg" : "text-dim hover:bg-hover hover:text-fg"
        }`
      }
    >
      <Icon size={20} />
      <span className="pointer-events-none absolute left-12 z-50 hidden whitespace-nowrap rounded bg-panel2 px-2 py-1 text-xs text-fg shadow group-hover:block">
        {label}
      </span>
    </NavLink>
  );
}

function StatusDot({ state }: { state: string }) {
  const color = state === "ready" ? "bg-ok" : state === "loading" ? "bg-warn animate-pulse" : "bg-bad";
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}

export default function Layout() {
  const { me, logout } = useAuth();
  const { data: h } = useHealth();
  const lecturer = me?.role === "lecturer";
  const banner =
    h && h.llm !== "ready"
      ? h.llm === "loading"
        ? "Модель загружается — вопросы можно будет задать через несколько секунд"
        : "Языковая модель недоступна"
      : h?.embedder === "loading"
        ? "Загружается модель поиска…"
        : h?.embedder === "error"
          ? `Модель поиска не загрузилась: ${h.embedder_error}`
          : null;

  return (
    <div className="flex h-full">
      <nav className="flex w-14 shrink-0 flex-col items-center gap-2 border-r border-line bg-rail py-3">
        <div className="mb-3 grid h-9 w-9 place-items-center rounded-lg bg-accent font-mono text-xs font-bold text-white">
          AI
        </div>
        <RailLink to="/" icon={MessageSquare} label="Чат" />
        {lecturer && <RailLink to="/documents" icon={FileText} label="Документы" />}
        {lecturer && <RailLink to="/stats" icon={BarChart3} label="Статистика" />}
        <div className="flex-1" />
        <button title="Выйти" onClick={logout} className="grid h-10 w-10 place-items-center rounded-lg text-dim hover:bg-hover hover:text-fg">
          <LogOut size={18} />
        </button>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-11 shrink-0 items-center gap-4 border-b border-line bg-panel px-4 text-xs">
          <div className="flex items-center gap-2 rounded-md border border-line bg-panel2 px-2.5 py-1 font-mono text-muted">
            <Cpu size={14} className="text-accent-fg" />
            <span className="text-fg">{h?.model.replace(/\.gguf$/i, "") ?? "…"}</span>
            {h && <StatusDot state={h.llm} />}
          </div>
          {h && (
            <span className="font-mono text-dim">
              лекций: <span className="text-muted">{h.documents_ready}</span>
              {h.documents_indexing > 0 && <span className="text-warn"> (+{h.documents_indexing} индексируется)</span>}
            </span>
          )}
          {h?.gpu && <span className="hidden font-mono text-dim md:inline">{h.gpu}</span>}
          <div className="flex-1" />
          <span className="text-muted">
            {me?.login} · <span className={lecturer ? "text-accent-fg" : ""}>{lecturer ? "лектор" : "студент"}</span>
          </span>
        </header>
        {banner && (
          <div className="flex items-center gap-2 border-b border-line bg-warn/10 px-4 py-1.5 text-xs text-warn">
            {h?.llm === "down" || h?.embedder === "error" ? <AlertTriangle size={14} /> : <Loader2 size={14} className="animate-spin" />}
            {banner}
          </div>
        )}
        <main className="min-h-0 flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
