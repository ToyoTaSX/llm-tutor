import { DragEvent, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload, Trash2, RefreshCw, FileText, X, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { api, ApiError, Doc, fmtDate } from "../api";

interface Pending {
  file: File;
  title: string;
}

function StatusBadge({ d }: { d: Doc }) {
  if (d.status === "ready")
    return (
      <span className="inline-flex items-center gap-1 rounded bg-ok/10 px-2 py-0.5 text-xs text-ok">
        <CheckCircle2 size={12} /> готов
      </span>
    );
  if (d.status === "indexing")
    return (
      <span className="inline-flex items-center gap-1 rounded bg-warn/10 px-2 py-0.5 text-xs text-warn">
        <Loader2 size={12} className="animate-spin" /> индексируется
      </span>
    );
  return (
    <span title={d.error ?? ""} className="inline-flex items-center gap-1 rounded bg-bad/10 px-2 py-0.5 text-xs text-bad">
      <AlertCircle size={12} /> ошибка
    </span>
  );
}

export default function Documents() {
  const qc = useQueryClient();
  const [pending, setPending] = useState<Pending[]>([]);
  const [drag, setDrag] = useState(false);
  const [messages, setMessages] = useState<{ ok: boolean; text: string }[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  const docs = useQuery({
    queryKey: ["documents"],
    queryFn: () => api<Doc[]>("/api/documents"),
    refetchInterval: (q) => (q.state.data?.some((d) => d.status === "indexing") ? 2000 : false),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["documents"] });
    qc.invalidateQueries({ queryKey: ["health"] });
  };

  const addFiles = (files: FileList | null) => {
    if (!files) return;
    const list = Array.from(files).map((f) => ({ file: f, title: f.name.replace(/\.[^.]+$/, "") }));
    setPending((p) => [...p, ...list]);
    setMessages([]);
  };

  const upload = useMutation({
    mutationFn: async (items: Pending[]) => {
      const fd = new FormData();
      items.forEach((p) => {
        fd.append("files", p.file);
        fd.append("titles", p.title);
      });
      return api<{ created: Doc[]; errors: { filename: string; message: string }[] }>("/api/documents", {
        method: "POST",
        body: fd,
      });
    },
    onSuccess: (r) => {
      setPending([]);
      setMessages([
        ...r.created.map((d) => ({ ok: true, text: `«${d.title}» загружен, идёт индексация` })),
        ...r.errors.map((e) => ({ ok: false, text: `${e.filename}: ${e.message}` })),
      ]);
      refresh();
    },
    onError: (e) => {
      const errs = e instanceof ApiError ? ((e.detail as { errors?: { filename: string; message: string }[] })?.errors ?? []) : [];
      setMessages(errs.length ? errs.map((x) => ({ ok: false, text: `${x.filename}: ${x.message}` })) : [{ ok: false, text: e.message }]);
      setPending([]);
    },
  });

  const del = useMutation({
    mutationFn: (id: number) => api(`/api/documents/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  const reindex = useMutation({
    mutationFn: (id: number) => api(`/api/documents/${id}/reindex`, { method: "POST" }),
    onSuccess: refresh,
  });

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    addFiles(e.dataTransfer.files);
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        <div>
          <h1 className="text-lg font-semibold">Документы</h1>
          <p className="text-xs text-muted">Лекции, по которым отвечает ассистент. Поддерживаются файлы .txt (UTF-8 или Windows-1251) до 10 МБ.</p>
        </div>

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          onClick={() => fileInput.current?.click()}
          className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
            drag ? "border-accent bg-accent-soft" : "border-line hover:border-dim"
          }`}
        >
          <Upload className="mx-auto mb-2 text-dim" />
          <div className="text-sm">Перетащите файлы лекций сюда или нажмите, чтобы выбрать</div>
          <div className="text-xs text-dim">.txt, можно несколько</div>
          <input
            ref={fileInput}
            type="file"
            accept=".txt,text/plain"
            multiple
            hidden
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        {pending.length > 0 && (
          <div className="card space-y-2 p-4">
            <div className="label">Будут загружены</div>
            {pending.map((p, i) => (
              <div key={i} className="flex items-center gap-3">
                <FileText size={16} className="shrink-0 text-dim" />
                <input
                  className="input py-1.5"
                  value={p.title}
                  onChange={(e) => setPending((ps) => ps.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))}
                />
                <span className="w-48 shrink-0 truncate font-mono text-xs text-dim" title={p.file.name}>
                  {p.file.name} · {(p.file.size / 1024).toFixed(0)} КБ
                </span>
                <button className="btn-ghost px-1.5" onClick={() => setPending((ps) => ps.filter((_, j) => j !== i))}>
                  <X size={14} />
                </button>
              </div>
            ))}
            <div className="flex justify-end gap-2 pt-2">
              <button className="btn-ghost" onClick={() => setPending([])}>
                Отмена
              </button>
              <button className="btn-primary" disabled={upload.isPending} onClick={() => upload.mutate(pending)}>
                <Upload size={14} /> Загрузить и проиндексировать
              </button>
            </div>
          </div>
        )}

        {messages.length > 0 && (
          <div className="space-y-1">
            {messages.map((m, i) => (
              <div key={i} className={`rounded-md px-3 py-2 text-xs ${m.ok ? "bg-ok/10 text-ok" : "bg-bad/10 text-bad"}`}>
                {m.text}
              </div>
            ))}
          </div>
        )}

        <div className="card overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line bg-panel2">
              <tr className="label">
                <th className="px-4 py-2.5 font-normal">Название</th>
                <th className="px-4 py-2.5 font-normal">Файл</th>
                <th className="px-4 py-2.5 font-normal">Статус</th>
                <th className="px-4 py-2.5 text-right font-normal">Фрагменты</th>
                <th className="px-4 py-2.5 text-right font-normal">Символы</th>
                <th className="px-4 py-2.5 font-normal">Загрузил</th>
                <th className="px-4 py-2.5 font-normal">Дата</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {docs.isLoading && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-muted">
                    Загрузка…
                  </td>
                </tr>
              )}
              {docs.data?.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-muted">
                    Документов пока нет
                  </td>
                </tr>
              )}
              {docs.data?.map((d) => (
                <tr key={d.id} className="border-b border-line last:border-0 hover:bg-panel2">
                  <td className="px-4 py-2.5">
                    <div className="font-medium">{d.title}</div>
                    {d.status === "error" && d.error && <div className="mt-0.5 text-xs text-bad">{d.error}</div>}
                  </td>
                  <td className="max-w-[12rem] truncate px-4 py-2.5 font-mono text-xs text-muted" title={d.filename}>
                    {d.filename}
                  </td>
                  <td className="px-4 py-2.5">
                    <StatusBadge d={d} />
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs">{d.status === "ready" ? d.chunks_count : "—"}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs text-muted">{d.chars.toLocaleString("ru-RU")}</td>
                  <td className="px-4 py-2.5 text-xs text-muted">{d.uploaded_by ?? "система"}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-muted">{fmtDate(d.created_at)}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-right">
                    <button
                      title="Переиндексировать"
                      className="btn-ghost px-1.5"
                      disabled={d.status === "indexing" || reindex.isPending}
                      onClick={() => reindex.mutate(d.id)}
                    >
                      <RefreshCw size={15} />
                    </button>
                    <button
                      title="Удалить"
                      className="btn-ghost px-1.5 hover:text-bad"
                      disabled={del.isPending}
                      onClick={() => {
                        if (window.confirm(`Удалить «${d.title}»? Его фрагменты перестанут использоваться в ответах.`)) del.mutate(d.id);
                      }}
                    >
                      <Trash2 size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
